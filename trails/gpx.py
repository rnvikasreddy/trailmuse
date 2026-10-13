"""Read GPX files (exported from a watch, Strava, AllTrails, Gaia...) into an Activity."""
import gpxpy

from . import geo


class GpxError(ValueError):
    pass


def parse_gpx(fileobj):
    """Return name, lines [[(lon, lat), ...]], length_m, gain_m, moving_seconds and started_at."""
    try:
        text = fileobj.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        g = gpxpy.parse(text)
    except Exception as exc:
        raise GpxError(f"This doesn't look like a GPX file ({exc.__class__.__name__}).") from exc

    lines, elev_profile, started_at = [], [], None
    dist_so_far = 0.0
    for track in g.tracks:
        for seg in track.segments:
            pts = [p for p in seg.points if p.latitude is not None]
            if len(pts) < 2:
                continue
            coords = [(p.longitude, p.latitude) for p in pts]
            lines.append(coords)
            if started_at is None and pts[0].time:
                started_at = pts[0].time
            prev = None
            for p, c in zip(pts, coords):
                if prev is not None:
                    dist_so_far += geo.haversine_m(prev, c)
                prev = c
                elev_profile.append((dist_so_far, p.elevation))
    if not lines:
        for route in g.routes:
            coords = [(p.longitude, p.latitude) for p in route.points]
            if len(coords) >= 2:
                lines.append(coords)
    if not lines:
        raise GpxError("The GPX file has no track points.")

    name = (g.tracks[0].name if g.tracks and g.tracks[0].name else None) or g.name or "Uploaded hike"
    gain = geo.elevation_stats([(d, e) for d, e in elev_profile if e is not None])["gain_m"] if elev_profile else 0.0
    moving = None
    try:
        md = g.get_moving_data()
        moving = int(md.moving_time) if md and md.moving_time else None
    except Exception:
        pass
    return {
        "name": name[:200],
        "lines": lines,
        "length_m": geo.multiline_length_m(lines),
        "gain_m": gain,
        "moving_seconds": moving,
        "started_at": started_at,
    }
