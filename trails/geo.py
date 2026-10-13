"""Geometry helpers: lengths in meters, line sampling, and trail stats.

Coordinates are WGS84 (lon, lat). Distances use the haversine formula, which is accurate
to well under 1% at trail scale and needs no projection setup.
"""
import math

EARTH_RADIUS_M = 6371008.8
M_PER_MILE = 1609.344
FT_PER_M = 3.28084


def haversine_m(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def line_length_m(coords):
    return sum(haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def multiline_length_m(lines):
    return sum(line_length_m(line) for line in lines)


def sample_line(coords, step_m=30.0):
    """Points every `step_m` meters along a polyline, as (distance_m, lon, lat), including both ends."""
    if not coords:
        return []
    out = [(0.0, coords[0][0], coords[0][1])]
    travelled = 0.0
    next_at = step_m
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        seg = haversine_m(a, b)
        if seg == 0:
            continue
        while travelled + seg >= next_at:
            t = (next_at - travelled) / seg
            out.append((next_at, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            next_at += step_m
        travelled += seg
    last = coords[-1]
    if travelled - out[-1][0] > 1e-6:
        out.append((travelled, last[0], last[1]))
    return out


def chain_lines(lines, snap_m=25.0):
    """Join line pieces end to end into one path where they touch (OSM splits trails into many ways).

    Greedy: start from the longest piece and keep attaching the nearest unused piece whose end
    is within `snap_m` of the current path's tail or head. Pieces that never connect are dropped
    from the chain (they stay in the trail geometry for display).
    """
    pieces = [list(map(tuple, line)) for line in lines if len(line) >= 2]
    if not pieces:
        return []
    pieces.sort(key=line_length_m, reverse=True)
    path = pieces.pop(0)
    changed = True
    while pieces and changed:
        changed = False
        for i, p in enumerate(pieces):
            if haversine_m(path[-1], p[0]) <= snap_m:
                path += p[1:]
            elif haversine_m(path[-1], p[-1]) <= snap_m:
                path += list(reversed(p))[1:]
            elif haversine_m(path[0], p[-1]) <= snap_m:
                path = p[:-1] + path
            elif haversine_m(path[0], p[0]) <= snap_m:
                path = list(reversed(p))[:-1] + path
            else:
                continue
            pieces.pop(i)
            changed = True
            break
    return path


def route_type(path, total_length_m):
    """'loop' when the path ends near where it starts, otherwise 'out_and_back' (hikers return the same way)."""
    if len(path) < 2:
        return "out_and_back"
    gap = haversine_m(path[0], path[-1])
    return "loop" if gap <= max(150.0, 0.03 * total_length_m) else "out_and_back"


def elevation_stats(profile, threshold_m=3.0):
    """Gain/loss from a [(distance_m, elevation_m), ...] profile.

    Small wiggles below `threshold_m` are ignored so DEM noise doesn't inflate the gain.
    """
    elevs = [e for _, e in profile if e is not None]
    if len(elevs) < 2:
        return {"gain_m": 0.0, "loss_m": 0.0, "min_m": elevs[0] if elevs else None, "max_m": elevs[0] if elevs else None}
    gain = loss = 0.0
    ref = elevs[0]
    for e in elevs[1:]:
        diff = e - ref
        if diff >= threshold_m:
            gain += diff
            ref = e
        elif diff <= -threshold_m:
            loss += -diff
            ref = e
    return {"gain_m": gain, "loss_m": loss, "min_m": min(elevs), "max_m": max(elevs)}


def smooth(values, window=5):
    if window < 2 or len(values) < window:
        return list(values)
    half = window // 2
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - half): i + half + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def difficulty(length_m, gain_m):
    """Effort-based rating: kilometers plus 1 km for every 100 m of climbing (a common hiking rule of thumb)."""
    effort = length_m / 1000 + gain_m / 100
    if effort < 8:
        return "easy"
    if effort < 16:
        return "moderate"
    return "hard"


def estimated_minutes(length_m, gain_m):
    """Naismith's rule: 5 km/h, plus 1 hour per 600 m of ascent."""
    return round((length_m / 5000 + gain_m / 600) * 60)
