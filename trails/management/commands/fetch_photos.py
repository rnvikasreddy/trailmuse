import math
import os
import time
from collections import defaultdict

from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand
from django.utils import timezone

from trails import photos
from trails.models import Photo, Trail

CELL = 0.1  # degrees; one Commons search covers one cell (search radius 10 km)


class Command(BaseCommand):
    help = (
        "Attach free photos to trails from Wikimedia Commons and (with NPS_API_KEY set) the National Park Service. "
        "Resumable: trails already checked are skipped unless --redo."
    )

    def add_arguments(self, parser):
        parser.add_argument("--bbox", help="only trails starting inside west,south,east,north")
        parser.add_argument("--redo", action="store_true", help="look again at trails checked before")
        parser.add_argument("--max-minutes", type=float, default=0, help="stop cleanly after this long (0 = no limit)")

    def handle(self, *args, **opts):
        started = time.monotonic()
        commons = photos.Commons()
        nps_places = nps_parks = None
        key = os.environ.get("NPS_API_KEY")
        if key:
            nps = photos.NPS(key)
            places = nps.places()
            nps_places, nps_parks = photos.PointGrid(places), nps.parks()
            self.stdout.write(f"NPS: {len(places)} places and {len(nps_parks)} parks with public-domain photos")
        else:
            self.stdout.write("NPS_API_KEY is not set; using Wikimedia Commons only")

        qs = Trail.objects.filter(is_published=True)
        if not opts["redo"]:
            qs = qs.filter(photos_checked_at__isnull=True)
        if opts["bbox"]:
            box = Polygon.from_bbox(tuple(float(x) for x in opts["bbox"].split(",")))
            box.srid = 4326
            qs = qs.filter(start__within=box)
        cells = defaultdict(list)
        for pk, start in qs.values_list("id", "start").iterator():
            cells[(math.floor(start.x / CELL), math.floor(start.y / CELL))].append(pk)
        self.stdout.write(f"{sum(len(v) for v in cells.values())} trails to check in {len(cells)} map squares")

        done = added = with_photos = 0
        for n, ((cx, cy), ids) in enumerate(sorted(cells.items()), 1):
            if opts["max_minutes"] and time.monotonic() - started > opts["max_minutes"] * 60:
                self.stdout.write(f"Time limit reached; run again to continue ({len(cells) - n + 1} squares left).")
                break
            try:
                n_added, n_with = self.do_cell(commons, nps_places, nps_parks, cx, cy, ids)
            except Exception as exc:  # leave the square unchecked so the next run retries it
                self.stderr.write(self.style.WARNING(f"square {cx * CELL:.1f},{cy * CELL:.1f}: {exc}"))
                continue
            done += len(ids)
            added += n_added
            with_photos += n_with
            if n % 200 == 0:
                self.stdout.write(f"  {n}/{len(cells)} squares, {done} trails checked, {with_photos} got photos")
        self.stdout.write(self.style.SUCCESS(f"Checked {done} trails: {with_photos} got photos ({added} photos added)."))

    def do_cell(self, commons, nps_places, nps_parks, cx, cy, ids):
        trails = list(Trail.objects.filter(id__in=ids).select_related("park").only("id", "name", "geom", "start", "park__name"))
        found = commons.nearby((cx + 0.5) * CELL, (cy + 0.5) * CELL)
        grid = photos.PointGrid(found)
        paths = {t.id: t.main_path() or [(t.start.x, t.start.y)] for t in trails}
        candidates = {t.id: grid.nearest(paths[t.id])[:8] for t in trails}
        details = commons.details({title for c in candidates.values() for title in c}) if found else {}
        have = defaultdict(set)
        for trail_id, url in Photo.objects.filter(trail_id__in=ids).exclude(source="upload").values_list("trail_id", "remote_url"):
            have[trail_id].add(url)

        new, with_photos = [], 0
        for t in trails:
            chosen = list(nps_places.nearest(paths[t.id])) if nps_places else []
            chosen += [details[title] for title in candidates[t.id] if title in details]
            if not chosen and nps_parks and t.park_id:
                chosen = list(nps_parks.get(t.park.name.strip().lower(), []))
            picked = []
            for p in chosen:
                if p["remote_url"] not in have[t.id] and all(p["remote_url"] != q["remote_url"] for q in picked):
                    picked.append(p)
            picked = picked[: max(0, photos.PER_TRAIL - len(have[t.id]))]
            new += [Photo(trail=t, rank=1, **p) for p in picked]
            with_photos += bool(picked or have[t.id])
        Photo.objects.bulk_create(new)
        Trail.objects.filter(id__in=ids).update(photos_checked_at=timezone.now())
        return len(new), with_photos
