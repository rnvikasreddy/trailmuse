"""Turn OpenStreetMap data (from the Overpass API) into Stigrr trails and parks.

The importer works on Overpass JSON with `out geom`, so every way and relation member
carries its own coordinates and no separate node lookup is needed.

Trail rules:
  * Every named hiking/foot route relation becomes one trail.
  * Named paths (highway=path/footway/track/bridleway) that are not part of such a relation
    are grouped by name, then split into connected pieces; each piece becomes one trail.
  * Named footways and tracks only count inside a park, so city sidewalks and farm roads stay out.
  * Anything shorter than MIN_TRAIL_M is skipped.
"""
from collections import defaultdict

import requests

from . import geo

MIN_TRAIL_M = 400
TRAIL_HIGHWAYS = {"path", "footway", "track", "bridleway"}
PARK_KEYS = {("boundary", "national_park"), ("boundary", "protected_area"), ("leisure", "nature_reserve"), ("leisure", "park")}


def overpass_query(south, west, north, east, timeout=180):
    bbox = f"{south},{west},{north},{east}"
    return f"""[out:json][timeout:{timeout}];
(
  relation["route"~"^(hiking|foot)$"]["name"]({bbox});
  way["highway"~"^(path|footway|track|bridleway)$"]["name"]({bbox});
  node["natural"="waterfall"]({bbox});
  node["tourism"="viewpoint"]({bbox});
  node["natural"="peak"]({bbox});
  way["natural"="beach"]({bbox});
  relation["boundary"~"^(national_park|protected_area)$"]["name"]({bbox});
  way["boundary"~"^(national_park|protected_area)$"]["name"]({bbox});
  relation["leisure"~"^(nature_reserve|park)$"]["name"]({bbox});
  way["leisure"~"^(nature_reserve|park)$"]["name"]({bbox});
);
out geom tags;"""


def fetch_overpass(url, query, timeout=300):
    resp = requests.post(url, data={"data": query}, timeout=timeout, headers={"User-Agent": "Stigrr importer"})
    resp.raise_for_status()
    return resp.json()


def tile_bbox(west, south, east, north, step):
    """Split a big bounding box into tiles so each Overpass request stays small."""
    tiles = []
    lat = south
    while lat < north:
        lon = west
        while lon < east:
            tiles.append((lat, lon, min(lat + step, north), min(lon + step, east)))
            lon += step
        lat += step
    return tiles


def _coords(geometry):
    return [(p["lon"], p["lat"]) for p in geometry or [] if p]


def _is_park(tags):
    return any(tags.get(k) == v for k, v in PARK_KEYS)


def assemble_rings(ways):
    """Stitch open way pieces into closed rings (for multipolygon relations)."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while pending:
        ring = pending.pop(0)
        progress = True
        while ring[0] != ring[-1] and progress:
            progress = False
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += list(reversed(w))[1:]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = list(reversed(w))[:-1] + ring
                else:
                    continue
                pending.pop(i)
                progress = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def point_in_ring(pt, ring):
    x, y = pt
    inside = False
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def parse(data):
    """Split Overpass elements into trails, parks and points of interest (plain Python dicts)."""
    elements = data.get("elements", [])
    relation_ways = set()
    route_relations, named_ways, parks = [], [], []
    pois = {"waterfall": [], "viewpoint": [], "peak": [], "beach": []}

    for el in elements:
        tags = el.get("tags", {})
        t = el["type"]
        if t == "node":
            pt = (el["lon"], el["lat"])
            if tags.get("natural") == "waterfall":
                pois["waterfall"].append(pt)
            elif tags.get("tourism") == "viewpoint":
                pois["viewpoint"].append(pt)
            elif tags.get("natural") == "peak":
                pois["peak"].append(pt)
        elif t == "relation" and tags.get("route") in ("hiking", "foot"):
            lines = [_coords(m.get("geometry")) for m in el.get("members", []) if m.get("type") == "way"]
            lines = [l for l in lines if len(l) >= 2]
            relation_ways.update(m["ref"] for m in el.get("members", []) if m.get("type") == "way")
            if lines:
                route_relations.append({"osm_type": "relation", "osm_id": el["id"], "name": tags["name"], "tags": tags, "lines": lines})
        elif _is_park(tags) and tags.get("name"):
            if t == "way":
                rings = [r for r in [_coords(el.get("geometry"))] if len(r) >= 4 and r[0] == r[-1]]
            else:
                outers = [_coords(m.get("geometry")) for m in el.get("members", []) if m.get("type") == "way" and m.get("role") in ("outer", "")]
                rings = assemble_rings(outers)
            if rings:
                parks.append({"osm_type": t, "osm_id": el["id"], "name": tags["name"], "tags": tags, "rings": rings})
        elif t == "way" and tags.get("natural") == "beach":
            c = _coords(el.get("geometry"))
            if c:
                pois["beach"].extend(c[:: max(1, len(c) // 10)])
        elif t == "way" and tags.get("highway") in TRAIL_HIGHWAYS and tags.get("name"):
            named_ways.append({"id": el["id"], "name": tags["name"], "tags": tags, "coords": _coords(el.get("geometry"))})

    def in_any_park(pt):
        return any(point_in_ring(pt, ring) for p in parks for ring in p["rings"])

    groups = defaultdict(list)
    for w in named_ways:
        if w["id"] in relation_ways or len(w["coords"]) < 2:
            continue
        mid = w["coords"][len(w["coords"]) // 2]
        if w["tags"].get("highway") != "path" and not in_any_park(mid):
            continue
        groups[w["name"].strip()].append(w)

    trails = list(route_relations)
    for name, ways in groups.items():
        for comp in connected_components(ways):
            lines = [w["coords"] for w in comp]
            anchor = min(w["id"] for w in comp)
            merged_tags = {}
            for w in comp:
                merged_tags.update(w["tags"])
            trails.append({"osm_type": "way", "osm_id": anchor, "name": name, "tags": merged_tags, "lines": lines})

    trails = [t for t in trails if geo.multiline_length_m(t["lines"]) >= MIN_TRAIL_M]
    return {"trails": trails, "parks": parks, "pois": pois}


def connected_components(ways, snap_m=30.0):
    """Group ways whose endpoints touch (within snap_m)."""
    n = len(ways)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends = [(w["coords"][0], w["coords"][-1]) for w in ways]
    for i in range(n):
        for j in range(i + 1, n):
            if any(geo.haversine_m(a, b) <= snap_m for a in ends[i] for b in ends[j]):
                parent[find(i)] = find(j)
    comps = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(ways[i])
    return list(comps.values())


def dogs_from_tags(tags):
    v = (tags.get("dog") or "").lower()
    if v in ("yes", "leashed", "unleashed", "designated"):
        return True
    if v == "no":
        return False
    return None
