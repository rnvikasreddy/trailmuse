import io
import json
import os
import struct
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from trails import elevation, geo, importer, osm
from trails.models import Activity, Trail

FIXTURES = Path(__file__).parent / "fixtures"


class GeoTests(TestCase):
    def test_haversine_one_degree_latitude(self):
        self.assertAlmostEqual(geo.haversine_m((0, 0), (0, 1)), 111195, delta=50)

    def test_sample_line_includes_ends_and_steps(self):
        pts = geo.sample_line([(0, 0), (0, 0.01)], step_m=100)
        self.assertEqual(pts[0][0], 0.0)
        self.assertAlmostEqual(pts[-1][0], 1111.95, delta=1)
        self.assertEqual(len(pts), 13)

    def test_chain_lines_joins_reversed_pieces(self):
        path = geo.chain_lines([[(0, 0), (0, 0.01)], [(0, 0.02), (0, 0.01)]])
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (0, 0.02))

    def test_elevation_gain_ignores_noise(self):
        profile = [(i, e) for i, e in enumerate([100, 101, 100, 102, 110, 109, 120, 115, 100])]
        stats = geo.elevation_stats(profile)
        self.assertEqual(stats["gain_m"], 20)
        self.assertEqual(stats["loss_m"], 20)

    def test_difficulty_scale(self):
        self.assertEqual(geo.difficulty(3000, 50), "easy")
        self.assertEqual(geo.difficulty(8000, 500), "moderate")
        self.assertEqual(geo.difficulty(15000, 900), "hard")


class OsmImportTests(TestCase):
    def setUp(self):
        self.data = json.load(open(FIXTURES / "overpass_sample.json"))

    def test_parse_rules(self):
        parsed = osm.parse(self.data)
        names = sorted(t["name"] for t in parsed["trails"])
        # relation + two separate Ridge Trail pieces; sidewalk, tiny spur and relation member way are skipped
        self.assertEqual(names, ["Ridge Trail", "Ridge Trail", "Test Falls Loop"])
        self.assertEqual(len(parsed["parks"]), 1)
        self.assertEqual(len(parsed["pois"]["waterfall"]), 1)

    def test_import_creates_trails_with_stats_park_and_muses(self):
        result = importer.import_parsed(osm.parse(self.data))
        self.assertEqual((result["created"], result["parks"]), (3, 1))
        loop = Trail.objects.get(name="Test Falls Loop")
        self.assertEqual(loop.route_type, "loop")
        self.assertEqual(loop.park.name, "Test Canyon Preserve")
        self.assertIn("waterfall", loop.muses)
        self.assertIs(loop.dogs_allowed, False)
        self.assertGreater(loop.length_m, 1500)
        ridge = Trail.objects.filter(name="Ridge Trail", park__isnull=False).get()
        self.assertEqual(ridge.route_type, "out_and_back")
        self.assertIs(ridge.dogs_allowed, True)

    def test_reimport_updates_instead_of_duplicating(self):
        importer.import_parsed(osm.parse(self.data))
        again = importer.import_parsed(osm.parse(self.data))
        self.assertEqual(again["created"], 0)
        self.assertEqual(Trail.objects.count(), 3)

    def test_staff_edits_survive_reimport(self):
        importer.import_parsed(osm.parse(self.data))
        t = Trail.objects.get(name="Test Falls Loop")
        t.name, t.source = "Renamed by staff", "staff"
        t.save()
        importer.import_parsed(osm.parse(self.data))
        self.assertTrue(Trail.objects.filter(name="Renamed by staff").exists())

    def test_merge_overpass_dedupes(self):
        merged = importer.merge_overpass([self.data, self.data])
        self.assertEqual(len(merged["elements"]), len(self.data["elements"]))

    def test_tile_bbox_covers_area(self):
        tiles = osm.tile_bbox(-123.0, 37.0, -122.5, 37.5, 0.25)
        self.assertEqual(len(tiles), 4)


def write_hgt(folder, lat0, lon0, size=121):
    """A synthetic SRTM tile whose height rises 1 m per row going south (test data only)."""
    ns, ew = ("N" if lat0 >= 0 else "S"), ("E" if lon0 >= 0 else "W")
    path = os.path.join(folder, f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}.hgt")
    with open(path, "wb") as f:
        for r in range(size):
            f.write(struct.pack(f">{size}h", *([r * 10] * size)))
    return path


class ElevationTests(TestCase):
    def test_hgt_lookup_interpolates(self):
        with tempfile.TemporaryDirectory() as d:
            write_hgt(d, 37, -123)
            p = elevation.HgtProvider(d)
            self.assertTrue(p.available())
            self.assertAlmostEqual(p.lookup(-122.5, 37.99999), 0, delta=0.1)
            self.assertAlmostEqual(p.lookup(-122.5, 37.5), 600, delta=0.5)
            self.assertIsNone(p.lookup(-120.5, 37.5))

    def test_compute_elevation_command(self):
        importer.import_parsed(osm.parse(json.load(open(FIXTURES / "overpass_sample.json"))))
        with tempfile.TemporaryDirectory() as d:
            write_hgt(d, 37, -123)
            with override_settings(ELEVATION_DIR=d):
                call_command("compute_elevation", stdout=io.StringIO())
        ridge = Trail.objects.filter(name="Ridge Trail", park__isnull=False).get()
        self.assertTrue(ridge.profile)
        self.assertEqual(ridge.elevation_source, "srtm-hgt")
        self.assertGreater(ridge.gain_m, 0)


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sample", stdout=io.StringIO())
        cls.user = User.objects.create_user("hiker", password="trail-pass-123")

    def test_list_filters(self):
        r = self.client.get("/api/trails", {"muse": "waterfall"}).json()
        self.assertEqual(r["count"], 3)
        r = self.client.get("/api/trails", {"difficulty": "hard", "dogs": "1"}).json()
        self.assertEqual([t["name"] for t in r["results"]], ["Mission Peak Trail"])
        r = self.client.get("/api/trails", {"q": "lands"}).json()
        self.assertEqual(r["results"][0]["slug"], "lands-end-trail")
        r = self.client.get("/api/trails", {"bbox": "-122.52,37.70,-122.40,37.80"}).json()
        self.assertEqual(sorted(t["name"] for t in r["results"]), ["Lands End Trail", "Twin Peaks Summit Trail"])
        r = self.client.get("/api/trails", {"max_miles": "1"}).json()
        self.assertEqual(r["count"], 2)

    def test_detail_and_pages(self):
        d = self.client.get("/api/trails/cataract-falls-trail").json()
        self.assertEqual(d["difficulty"], "moderate")
        self.assertTrue(d["profile"])
        self.assertEqual(self.client.get("/trail/cataract-falls-trail/").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/trail/nope/").status_code, 404)

    def test_actions_need_login(self):
        self.assertEqual(self.client.post("/api/trails/lands-end-trail/save").status_code, 401)

    def test_save_and_saved_filter(self):
        self.client.force_login(self.user)
        self.assertTrue(self.client.post("/api/trails/lands-end-trail/save").json()["saved"])
        r = self.client.get("/api/trails", {"saved": "1"}).json()
        self.assertEqual([t["slug"] for t in r["results"]], ["lands-end-trail"])
        self.assertTrue(r["results"][0]["saved"])
        self.assertFalse(self.client.post("/api/trails/lands-end-trail/save").json()["saved"])

    def test_review_validation_and_rating(self):
        self.client.force_login(self.user)
        bad = self.client.post("/api/trails/lands-end-trail/reviews", json.dumps({"rating": 6, "body": "x"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/trails/lands-end-trail/reviews", json.dumps({"rating": 5, "body": "Foggy but beautiful walk."}), content_type="application/json")
        self.assertEqual(ok.status_code, 201)
        again = self.client.post("/api/trails/lands-end-trail/reviews", json.dumps({"rating": 4, "body": "Second visit, still great."}), content_type="application/json")
        self.assertEqual(again.status_code, 201)
        d = self.client.get("/api/trails/lands-end-trail").json()
        self.assertEqual((d["review_count"], d["avg_rating"]), (1, 4.0))
        self.assertEqual(d["my_review"]["rating"], 4)

    def test_photo_upload_checks_image(self):
        self.client.force_login(self.user)
        fake = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        self.assertEqual(self.client.post("/api/trails/mori-point-loop/photos", {"image": fake}).status_code, 400)
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), (40, 120, 60)).save(buf, "JPEG")
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            good = SimpleUploadedFile("view.jpg", buf.getvalue(), content_type="image/jpeg")
            r = self.client.post("/api/trails/mori-point-loop/photos", {"image": good, "caption": "Sunset"})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(len(self.client.get("/api/trails/mori-point-loop").json()["photos"]), 1)

    def test_gpx_upload_matches_nearby_trail(self):
        Trail.objects.filter(slug="cataract-falls-trail").update(start=Point(-122.6, 37.9, srid=4326))
        self.client.force_login(self.user)
        with open(FIXTURES / "hike.gpx", "rb") as f:
            r = self.client.post("/api/activities/upload", {"gpx": f})
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertEqual(j["name"], "Morning hike")
        self.assertEqual(j["trail"]["slug"], "cataract-falls-trail")
        self.assertEqual(j["gain_ft"], round(90 * geo.FT_PER_M))  # climbs 20 + 30 + 40 m; the 10 m dip is loss
        self.assertEqual(Activity.objects.count(), 1)
        bad = self.client.post("/api/activities/upload", {"gpx": SimpleUploadedFile("x.gpx", b"hello")})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.get("/me/hikes/").status_code, 200)

    def test_trail_lines_geojson(self):
        importer.import_parsed(osm.parse(json.load(open(FIXTURES / "overpass_sample.json"))))
        fc = self.client.get("/api/trails/lines", {"bbox": "-122.7,37.85,-122.5,37.95", "z": "12"}).json()
        self.assertEqual(fc["type"], "FeatureCollection")
        self.assertEqual(len(fc["features"]), 2)

    def test_signup_flow(self):
        r = self.client.post("/accounts/signup/", {"username": "newhiker", "password1": "Redwood-Trails-42", "password2": "Redwood-Trails-42", "next": "/saved/"})
        self.assertRedirects(r, "/saved/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="newhiker").exists())
