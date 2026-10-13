"""Read trails, parks and points of interest from an OpenStreetMap .osm.pbf extract.

Country-sized imports use Geofabrik's per-state extracts instead of the Overpass API.
This module turns a (pre-filtered) extract into the same element list Overpass returns
with `out geom`, so `osm.parse` and the importer work unchanged.

Filter a raw extract first with osmium-tool (see FILTER_EXPRESSIONS); reading a whole
state through Python would be slow.
"""
import osmium

from .osm import TRAIL_HIGHWAYS

# osmium tags-filter expressions matching osm.overpass_query.
FILTER_EXPRESSIONS = [
    "r/route=hiking,foot",
    "w/highway=path,footway,track,bridleway",
    "n/natural=waterfall,peak",
    "n/tourism=viewpoint",
    "w/natural=beach",
    "wr/boundary=national_park,protected_area",
    "wr/leisure=nature_reserve,park",
]


def _is_route(tags):
    return tags.get("route") in ("hiking", "foot") and bool(tags.get("name"))


def _is_park(tags):
    return bool(tags.get("name")) and (
        tags.get("boundary") in ("national_park", "protected_area") or tags.get("leisure") in ("nature_reserve", "park")
    )


def _wanted_way(tags):
    return (tags.get("highway") in TRAIL_HIGHWAYS and bool(tags.get("name"))) or tags.get("natural") == "beach" or _is_park(tags)


class _Relations(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.relations = []
        self.member_ways = set()

    def relation(self, r):
        tags = dict(r.tags)
        if not (_is_route(tags) or _is_park(tags)):
            return
        members = [(m.ref, m.role) for m in r.members if m.type == "w"]
        self.relations.append({"id": r.id, "tags": tags, "members": members})
        self.member_ways.update(ref for ref, _ in members)


class _WaysAndNodes(osmium.SimpleHandler):
    def __init__(self, member_ways):
        super().__init__()
        self.member_ways = member_ways
        self.member_geom = {}
        self.elements = []

    def node(self, n):
        tags = n.tags
        if tags.get("natural") in ("waterfall", "peak") or tags.get("tourism") == "viewpoint":
            if n.location.valid():
                self.elements.append({"type": "node", "id": n.id, "lat": n.location.lat, "lon": n.location.lon, "tags": dict(tags)})

    def way(self, w):
        wanted = _wanted_way(w.tags)
        if not wanted and w.id not in self.member_ways:
            return
        geom = [{"lat": nd.location.lat, "lon": nd.location.lon} for nd in w.nodes if nd.location.valid()]
        if w.id in self.member_ways:
            self.member_geom[w.id] = geom
        if wanted:
            self.elements.append({"type": "way", "id": w.id, "tags": dict(w.tags), "geometry": geom})


def read_elements(path):
    """All wanted elements of a .osm.pbf file, shaped like Overpass `out geom` output."""
    rels = _Relations()
    rels.apply_file(path)
    ways = _WaysAndNodes(rels.member_ways)
    ways.apply_file(path, locations=True, idx="flex_mem")
    elements = ways.elements
    for r in rels.relations:
        members = [{"type": "way", "ref": ref, "role": role, "geometry": ways.member_geom.get(ref, [])} for ref, role in r["members"]]
        elements.append({"type": "relation", "id": r["id"], "tags": r["tags"], "members": members})
    return {"elements": elements}


def file_bbox(path):
    """The extract's bounding box from its header as (west, south, east, north), or None."""
    box = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING).header().box()
    if not box.valid():
        return None
    return (box.bottom_left.lon, box.bottom_left.lat, box.top_right.lon, box.top_right.lat)
