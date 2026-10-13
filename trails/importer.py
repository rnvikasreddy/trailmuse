"""Save parsed OpenStreetMap data into the database."""
from django.contrib.gis.db.models.functions import Area
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from . import elevation, muses, osm
from .models import Park, Trail


BATCH = 500


class SlugMaker:
    """Unique slugs for many new rows without a database query per row."""

    def __init__(self, model):
        self.taken = set(model.objects.values_list("slug", flat=True))

    def make(self, text, fallback):
        base = slugify(text)[:70] or fallback
        slug, n = base, 2
        while slug in self.taken:
            slug = f"{base}-{n}"
            n += 1
        self.taken.add(slug)
        return slug


def _existing(model, items):
    """Rows already imported for these parsed items, keyed by (osm_type, osm_id)."""
    found = {}
    for kind in {i["osm_type"] for i in items}:
        ids = [i["osm_id"] for i in items if i["osm_type"] == kind]
        for n in range(0, len(ids), 5000):
            for row in model.objects.filter(osm_type=kind, osm_id__in=ids[n: n + 5000]):
                found[(row.osm_type, row.osm_id)] = row
    return found


def _park_geom(rings):
    geom = MultiPolygon([Polygon(ring, srid=4326) for ring in rings], srid=4326)
    if not geom.valid:
        geom = geom.buffer(0)
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom], srid=4326)
        if geom.geom_type != "MultiPolygon":
            return None
    return geom


def save_parks(parks):
    """Create or update parks. Returns {(osm_type, osm_id): Park} for the ones saved."""
    existing = _existing(Park, parks)
    slugs = None
    new, changed, saved = [], [], {}
    for p in parks:
        geom = _park_geom(p["rings"])
        if geom is None:
            continue
        key = (p["osm_type"], p["osm_id"])
        park = existing.get(key)
        if park is None:
            slugs = slugs or SlugMaker(Park)
            park = Park(osm_type=p["osm_type"], osm_id=p["osm_id"])
            park.slug = slugs.make(p["name"], "park")
            new.append(park)
        else:
            changed.append(park)
        tags = p["tags"]
        park.name = p["name"][:200]
        park.geom = geom
        park.website = tags.get("website", "")[:200]
        park.agency = tags.get("operator", "")[:200]
        saved[key] = park
    Park.objects.bulk_create(new, batch_size=BATCH)
    Park.objects.bulk_update(changed, ["name", "geom", "website", "agency"], batch_size=BATCH)
    return saved


def park_for(point):
    """The smallest park containing the point (a preserve inside a bigger recreation area wins)."""
    return Park.objects.filter(geom__contains=point).annotate(a=Area("geom")).order_by("a").first()


class ParkFinder:
    """Finds the smallest park around a trailhead, in memory for the parks in this import."""

    def __init__(self, parks, saved):
        rings, keys, self.area = [], [], {}
        for p in parks:
            key = (p["osm_type"], p["osm_id"])
            if key not in saved:
                continue
            self.area[key] = sum(osm.ring_area(r) for r in p["rings"])
            rings += p["rings"]
            keys += [key] * len(p["rings"])
        self.index = osm.RingIndex(rings, keys)
        self.saved = saved

    def find(self, pt):
        keys = self.index.containing(pt)
        if keys:
            return self.saved[min(keys, key=lambda k: self.area[k])]
        return park_for(Point(*pt, srid=4326))  # a park saved by an earlier import


def _fill_trail(trail, t, pois, parks, provider):
    trail.name = t["name"][:200]
    trail.geom = MultiLineString([LineString(line, srid=4326) for line in t["lines"]], srid=4326)
    path = trail.main_path() or t["lines"][0]
    trail.start = Point(*path[0], srid=4326)
    trail.park = parks.find(path[0])
    tags = dict(t["tags"])
    tags["_near"] = muses.near_features(path, pois)
    trail.osm_tags = tags
    trail.dogs_allowed = osm.dogs_from_tags(tags)
    if not trail.description and tags.get("description"):
        trail.description = tags["description"]
    if provider is not None:
        profile = elevation.build_profile(path, provider)
        if profile:
            trail.profile, trail.elevation_source = profile, provider.name
    trail.recompute_stats()
    trail.muses = muses.suggest(trail.name, trail.park.name if trail.park else "", trail.length_m, trail.gain_m, trail.difficulty, tags["_near"])


TRAIL_FIELDS = ["name", "geom", "start", "park", "osm_tags", "dogs_allowed", "description", "profile", "elevation_source",
                "length_m", "route_type", "gain_m", "min_elev_m", "max_elev_m", "difficulty", "muses", "updated_at"]


@transaction.atomic
def import_parsed(parsed, provider=None, log=None):
    """Save parsed parks and trails in batches.

    `provider` (an elevation provider) also builds each trail's elevation profile on the way in.
    Trails that staff took over are left alone.
    """
    saved_parks = save_parks(parsed["parks"])
    parks = ParkFinder(parsed["parks"], saved_parks)
    pois = muses.PoiIndex(parsed["pois"])
    # Trails near each other share elevation tiles; keeping them together avoids re-reading tiles.
    trails = sorted(parsed["trails"], key=lambda t: (int(t["lines"][0][0][1] // 1), int(t["lines"][0][0][0] // 1)))
    existing = _existing(Trail, trails)
    slugs = None
    new, changed = [], []
    for n, t in enumerate(trails, 1):
        trail = existing.get((t["osm_type"], t["osm_id"]))
        if trail is not None and trail.source == "staff":
            continue  # staff took this trail over; don't overwrite their edits
        if trail is None:
            slugs = slugs or SlugMaker(Trail)
            trail = Trail(osm_type=t["osm_type"], osm_id=t["osm_id"], source="osm")
            trail.slug = slugs.make(t["name"], "trail")
            new.append(trail)
        else:
            changed.append(trail)
        _fill_trail(trail, t, pois, parks, provider)
        trail.updated_at = timezone.now()
        if log and n % 5000 == 0:
            log(f"  prepared {n}/{len(trails)} trails")
    Trail.objects.bulk_create(new, batch_size=BATCH)
    Trail.objects.bulk_update(changed, TRAIL_FIELDS, batch_size=BATCH)
    return {"parks": len(saved_parks), "created": len(new), "updated": len(changed)}


# Once this many real trails are in, the illustrative sample trails are hidden.
MIN_REAL_TRAILS = 50


def hide_samples_if_ready():
    """Hide the sample trails once enough real ones exist. Returns (real trails, samples hidden)."""
    real = Trail.objects.filter(is_published=True).exclude(source="sample").count()
    hidden = 0
    if real >= MIN_REAL_TRAILS:
        hidden = Trail.objects.filter(source="sample", is_published=True).update(is_published=False)
    return real, hidden


def merge_overpass(responses):
    """Combine Overpass responses from several tiles, keeping each element once.

    Parsing the combined data (instead of each tile on its own) keeps a trail that crosses a
    tile edge in one piece.
    """
    seen, elements = set(), []
    for data in responses:
        for el in data.get("elements", []):
            key = (el["type"], el["id"])
            if key not in seen:
                seen.add(key)
                elements.append(el)
    return {"elements": elements}
