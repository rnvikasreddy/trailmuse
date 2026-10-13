"""Guess each trail's "muses" (reasons to hike) from its numbers, name, park and nearby features.

These are starting suggestions; staff can edit them in the admin.
"""
from . import geo

NEAR_M = 350


def near_features(path, pois):
    """Which kinds of point of interest sit close to the trail. Stored at import time."""
    if not path:
        return {}
    sample = path[:: max(1, len(path) // 60)] + [path[-1]]

    def near(points, within):
        return any(geo.haversine_m(p, q) <= within for p in sample for q in points)

    return {
        "waterfall": near(pois.get("waterfall", []), NEAR_M),
        "viewpoint": near(pois.get("viewpoint", []) + pois.get("peak", []), NEAR_M),
        "beach": near(pois.get("beach", []), 500),
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
