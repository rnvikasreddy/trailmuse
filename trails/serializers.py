"""Plain-dict serializers for the JSON API (no extra framework needed at this size)."""
import json

from . import geo
from .models import MUSE_LABELS


def trail_summary(t, saved_ids=frozenset()):
    photos = t.photos.all()  # served from prefetch_related("photos") in list views
    photo = photos[0] if photos else None
    return {
        "slug": t.slug,
        "name": t.name,
        "park": t.park.name if t.park_id else "",
        "town": t.town,
        "lon": round(t.start.x, 6),
        "lat": round(t.start.y, 6),
        "miles": t.miles,
        "gain_ft": t.gain_ft,
        "difficulty": t.difficulty,
        "route_type": t.route_type,
        "est_minutes": t.estimated_minutes,
        "muses": t.muses,
        "why": t.why,
        "avg_rating": round(t.avg_rating, 1) if getattr(t, "avg_rating", None) else None,
        "review_count": getattr(t, "review_count", 0),
        "saved": t.pk in saved_ids,
        "photo": photo.image.url if photo else None,
        "source": t.source,
    }


def trail_detail(t, user=None, saved=False):
    d = trail_summary(t, {t.pk} if saved else frozenset())
    d.update({
        "description": t.description,
        "park_website": t.park.website if t.park_id else "",
        "dogs_allowed": t.dogs_allowed,
        "profile": t.profile,
        "profile_one_way": t.route_type == "out_and_back",
        "elevation_source": t.elevation_source,
        "min_elev_ft": round(t.min_elev_m * geo.FT_PER_M) if t.min_elev_m is not None else None,
        "max_elev_ft": round(t.max_elev_m * geo.FT_PER_M) if t.max_elev_m is not None else None,
        "geometry": json.loads(t.geom.geojson) if t.geom else None,
        "bbox": list(t.geom.extent) if t.geom else None,
        # The pieces chained into one walkable line from the trailhead, for direction arrows on the map.
        "path": [[round(x, 6), round(y, 6)] for x, y in t.main_path()] if t.geom else None,
        "muse_labels": [MUSE_LABELS.get(m, m) for m in t.muses],
        "osm_url": f"https://www.openstreetmap.org/{t.osm_type}/{t.osm_id}" if t.osm_id else "",
        "reviews": [review(r) for r in t.reviews.select_related("user")[:20]],
        "photos": [{"url": p.image.url, "caption": p.caption, "by": p.user.username} for p in t.photos.select_related("user")[:12]],
        "my_review": review(t.reviews.filter(user=user).first()) if user and user.is_authenticated else None,
    })
    return d


def review(r):
    if r is None:
        return None
    return {
        "id": r.pk,
        "user": r.user.username,
        "rating": r.rating,
        "body": r.body,
        "hiked_on": r.hiked_on.isoformat() if r.hiked_on else None,
        "created_at": r.created_at.isoformat(),
    }


def activity(a):
    return {
        "id": a.pk,
        "name": a.name,
        "miles": round(a.length_m / geo.M_PER_MILE, 2),
        "gain_ft": round(a.gain_m * geo.FT_PER_M),
        "moving_minutes": round(a.moving_seconds / 60) if a.moving_seconds else None,
        "started_at": a.started_at.isoformat() if a.started_at else None,
        "trail": {"slug": a.trail.slug, "name": a.trail.name} if a.trail_id else None,
        "geometry": json.loads(a.geom.geojson),
    }
