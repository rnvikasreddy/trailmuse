"""Save parsed OpenStreetMap data into the database."""
from django.contrib.gis.db.models.functions import Area
from django.contrib.gis.geos import LineString, MultiLineString, MultiPolygon, Point, Polygon
from django.db import transaction

from . import muses, osm
from .models import Park, Trail


def save_parks(parks):
    saved = 0
    for p in parks:
        polys = [Polygon(ring, srid=4326) for ring in p["rings"]]
        geom = MultiPolygon(polys, srid=4326)
        if not geom.valid:
            geom = geom.buffer(0)
            if geom.geom_type == "Polygon":
                geom = MultiPolygon([geom], srid=4326)
            if geom.geom_type != "MultiPolygon":
                continue
        tags = p["tags"]
        Park.objects.update_or_create(
            osm_type=p["osm_type"], osm_id=p["osm_id"],
            defaults={"name": p["name"], "geom": geom, "website": tags.get("website", "")[:200], "agency": tags.get("operator", "")[:200]},
        )
        saved += 1
    return saved


def park_for(point):
    """The smallest park containing the point (a preserve inside a bigger recreation area wins)."""
    return Park.objects.filter(geom__contains=point).annotate(a=Area("geom")).order_by("a").first()


@transaction.atomic
def save_trail(t, pois):
    lines = [LineString(line, srid=4326) for line in t["lines"]]
    geom = MultiLineString(lines, srid=4326)
    existing = Trail.objects.filter(osm_type=t["osm_type"], osm_id=t["osm_id"]).first()
    if existing and existing.source == "staff":
        return existing, False  # staff took this trail over; don't overwrite their edits
    trail = existing or Trail(osm_type=t["osm_type"], osm_id=t["osm_id"], source="osm")
    trail.name = t["name"][:200]
    trail.geom = geom
    path = trail.main_path() or t["lines"][0]
    trail.start = Point(*path[0], srid=4326)
    trail.park = park_for(trail.start)
    tags = dict(t["tags"])
    tags["_near"] = muses.near_features(path, pois)
    trail.osm_tags = tags
    trail.dogs_allowed = osm.dogs_from_tags(tags)
    if not trail.description and tags.get("description"):
        trail.description = tags["description"]
    trail.recompute_stats()
    trail.muses = muses.suggest(trail.name, trail.park.name if trail.park else "", trail.length_m, trail.gain_m, trail.difficulty, tags["_near"])
    trail.save()
    return trail, existing is None


def import_parsed(parsed):
    parks = save_parks(parsed["parks"])
    created = updated = 0
    for t in parsed["trails"]:
        _, is_new = save_trail(t, parsed["pois"])
        created += is_new
        updated += not is_new
    return {"parks": parks, "created": created, "updated": updated}


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
