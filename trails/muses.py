"""Guess each trail's "muses" (reasons to hike) from its numbers, name, park and nearby features.

These are starting suggestions; staff can edit them in the admin.
"""
from . import geo

NEAR_M = 350


class PoiIndex:
    """Points of interest bucketed into a grid about 1 km wide, so state-sized imports stay fast."""

    CELL = 0.01  # degrees

    def __init__(self, pois):
        self.grid = {}
        for kind, points in (pois or {}).items():
            for pt in points:
                self.grid.setdefault(kind, {}).setdefault(self._key(pt), []).append(pt)

    def _key(self, pt):
        return int(pt[0] // self.CELL), int(pt[1] // self.CELL)

    def near(self, kinds, sample, within):
        reach = int(within / 1000) + 1  # grid cells to look at around each sample point
        for kind in kinds:
            cells = self.grid.get(kind)
            if not cells:
                continue
            for p in sample:
                cx, cy = self._key(p)
                for dx in range(-reach, reach + 1):
                    for dy in range(-reach, reach + 1):
                        for q in cells.get((cx + dx, cy + dy), ()):
                            if geo.haversine_m(p, q) <= within:
                                return True
        return False


def near_features(path, pois):
    """Which kinds of point of interest sit close to the trail. Stored at import time.

    `pois` is a PoiIndex, or a {kind: [(lon, lat), ...]} dict for one-off calls.
    """
    if not path:
        return {}
    index = pois if isinstance(pois, PoiIndex) else PoiIndex(pois)
    sample = path[:: max(1, len(path) // 60)] + [path[-1]]
    return {
        "waterfall": index.near(["waterfall"], sample, NEAR_M),
        "viewpoint": index.near(["viewpoint", "peak"], sample, NEAR_M),
        "beach": index.near(["beach"], sample, 500),
    }


def suggest(name, park_name, length_m, gain_m, difficulty, near=None):
    near = near or {}
    text = f"{name} {park_name or ''}".lower()
    m = set()
    if "fall" in text or near.get("waterfall"):
        m.add("waterfall")
    if any(w in text for w in ("redwood", "muir woods", "big basin", "armstrong", "sequoia")):
        m.add("redwoods")
    if any(w in text for w in ("beach", "coast", "bluff", "ocean", "point ", "cove")) or near.get("beach"):
        m.add("ocean")
    has_views = near.get("viewpoint") or gain_m >= 300 or any(w in text for w in ("peak", "summit", "ridge", "mount", "mt."))
    if has_views:
        m.add("views")
    if has_views and ("ocean" in m or gain_m >= 200):
        m.add("sunset")
    if gain_m >= 450 or difficulty == "hard":
        m.add("workout")
    if any(w in text for w in ("preserve", "refuge", "marsh", "wildlife", "lagoon", "slough")):
        m.add("wildlife")
    if length_m <= 5000 and gain_m <= 150:
        m.add("family")
    if (has_views or "ocean" in m) and length_m <= 8000 and difficulty != "hard":
        m.add("date")
    if length_m >= 6000 and "family" not in m and any(w in text for w in ("preserve", "wilderness", "canyon", "creek")):
        m.add("quiet")
    return sorted(m)
