import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import MultiLineString, LineString, Point, Polygon
from django.contrib.gis.measure import D
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from . import serializers
from .gpx import GpxError, parse_gpx
from .models import MUSES, Activity, Photo, Review, SavedTrail, Trail, rating_summary

MAX_RESULTS = 200


# ---------- Pages ----------

def explore(request, slug=None):
    initial = None
    if slug:
        trail = get_object_or_404(Trail, slug=slug, is_published=True)
        saved = request.user.is_authenticated and trail.saves.filter(user=request.user).exists()
        initial = serializers.trail_detail(trail, request.user, saved)
    return render(request, "trails/explore.html", {
        "initial_trail": initial,
        "muses": MUSES,
        "region_bbox": list(settings.REGION_BBOX),
        "page_title": initial["name"] if initial else None,
        "page_description": (initial["why"] or initial["description"][:150]) if initial else None,
    })


@login_required
def my_hikes(request):
    acts = request.user.activities.select_related("trail")
    return render(request, "trails/my_hikes.html", {"activities": [serializers.activity(a) for a in acts]})


# ---------- API helpers ----------

def _bad(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


def _parse_bbox(value):
    try:
        w, s, e, n = (float(x) for x in value.split(","))
    except (AttributeError, ValueError):
        return None
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        return None
    return Polygon.from_bbox((w, s, e, n))


def filtered_trails(request):
    qs = Trail.objects.filter(is_published=True).select_related("park")
    p = request.GET
    bbox = _parse_bbox(p.get("bbox"))
    if bbox is not None:
        bbox.srid = 4326
        qs = qs.filter(Q(start__within=bbox) | Q(geom__intersects=bbox))
    if p.get("q"):
        q = p["q"].strip()
        qs = qs.filter(Q(name__icontains=q) | Q(park__name__icontains=q) | Q(town__icontains=q))
    if p.get("difficulty") in ("easy", "moderate", "hard"):
        qs = qs.filter(difficulty=p["difficulty"])
    if p.get("max_miles"):
        try:
            qs = qs.filter(length_m__lte=float(p["max_miles"]) * 1609.344)
        except ValueError:
            pass
    if p.get("dogs") == "1":
        qs = qs.filter(dogs_allowed=True)
    if p.get("muse"):
        qs = qs.filter(muses__contains=[p["muse"]])
    if p.get("saved") == "1":
        if not request.user.is_authenticated:
            return qs.none()
        qs = qs.filter(saves__user=request.user)
    return qs


@require_GET
def api_trails(request):
    # The list never needs geometry or profiles; loading them (and big park outlines) made wide areas slow.
    qs = filtered_trails(request).defer("geom", "profile", "osm_tags", "description", "park__geom")
    qs = rating_summary(qs).annotate(save_count=Count("saves", distinct=True))
    near = request.GET.get("near")
    if near:
        try:
            lon, lat = (float(x) for x in near.split(","))
            qs = qs.annotate(dist=Distance("start", Point(lon, lat, srid=4326))).order_by("dist")
        except ValueError:
            return _bad("near must be lon,lat")
    elif request.GET.get("sort") == "length":
        qs = qs.order_by("length_m")
    else:
        qs = qs.order_by("-save_count", "-review_count", "name")
    total = qs.count()
    trails = list(qs.prefetch_related("photos")[:MAX_RESULTS])
    saved_ids = set()
    if request.user.is_authenticated:
        saved_ids = set(SavedTrail.objects.filter(user=request.user, trail__in=trails).values_list("trail_id", flat=True))
    return JsonResponse({"count": total, "results": [serializers.trail_summary(t, saved_ids) for t in trails]})


@require_GET
def api_trail_lines(request):
    """Trail lines for the map as GeoJSON, simplified to suit the zoom level."""
    try:
        zoom = float(request.GET.get("z", 11))
    except ValueError:
        zoom = 11
    tolerance = 0.0 if zoom >= 14 else 0.00002 * 2 ** (14 - zoom)
    qs = filtered_trails(request).select_related(None).exclude(geom__isnull=True).only("slug", "name", "difficulty", "geom")[:1500]
    feats = []
    for t in qs:
        g = t.geom.simplify(tolerance, preserve_topology=False) if tolerance else t.geom
        if g.empty:
            continue
        feats.append({"type": "Feature", "properties": {"slug": t.slug, "name": t.name, "difficulty": t.difficulty}, "geometry": json.loads(g.geojson)})
    return JsonResponse({"type": "FeatureCollection", "features": feats})


@require_GET
def api_trail(request, slug):
    trail = get_object_or_404(Trail.objects.select_related("park"), slug=slug, is_published=True)
    trail = rating_summary(Trail.objects.filter(pk=trail.pk)).select_related("park").get()
    saved = request.user.is_authenticated and trail.saves.filter(user=request.user).exists()
    return JsonResponse(serializers.trail_detail(trail, request.user, saved))


def _login_json(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _bad("Log in to do that.", 401)
        return view(request, *args, **kwargs)
    return wrapped


@require_POST
@_login_json
def api_toggle_save(request, slug):
    trail = get_object_or_404(Trail, slug=slug, is_published=True)
    obj = SavedTrail.objects.filter(user=request.user, trail=trail).first()
    if obj:
        obj.delete()
        return JsonResponse({"saved": False})
    SavedTrail.objects.create(user=request.user, trail=trail)
    return JsonResponse({"saved": True})


@require_POST
@_login_json
def api_review(request, slug):
    trail = get_object_or_404(Trail, slug=slug, is_published=True)
    try:
        data = json.loads(request.body or "{}")
        rating = int(data.get("rating", 0))
    except (ValueError, TypeError):
        return _bad("Send JSON with a rating from 1 to 5.")
    body = (data.get("body") or "").strip()
    if not 1 <= rating <= 5:
        return _bad("Pick a rating from 1 to 5 stars.")
    if len(body) < 10:
        return _bad("Write at least a sentence about the hike.")
    if len(body) > 3000:
        return _bad("Keep reviews under 3,000 characters.")
    hiked_on = data.get("hiked_on") or None
    review, _ = Review.objects.update_or_create(trail=trail, user=request.user, defaults={"rating": rating, "body": body, "hiked_on": hiked_on})
    return JsonResponse(serializers.review(review), status=201)


@require_POST
@_login_json
def api_photo(request, slug):
    trail = get_object_or_404(Trail, slug=slug, is_published=True)
    img = request.FILES.get("image")
    if not img:
        return _bad("Choose a photo to upload.")
    if img.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        return _bad(f"Photos must be under {settings.MAX_UPLOAD_MB} MB.")
    from PIL import Image, UnidentifiedImageError
    try:
        Image.open(img).verify()
    except (UnidentifiedImageError, OSError):
        return _bad("That file isn't a photo we can read. Use JPG, PNG or WebP.")
    img.seek(0)
    photo = Photo.objects.create(trail=trail, user=request.user, image=img, caption=(request.POST.get("caption") or "")[:200])
    return JsonResponse(serializers.photo(photo), status=201)


@require_POST
@_login_json
def api_upload_gpx(request):
    f = request.FILES.get("gpx")
    if not f:
        return _bad("Choose a .gpx file.")
    try:
        data = parse_gpx(f)
    except GpxError as exc:
        return _bad(str(exc))
    geom = MultiLineString([LineString(l, srid=4326) for l in data["lines"]], srid=4326)
    start = Point(*data["lines"][0][0], srid=4326)
    # Match the hike to the nearest trail start within 500 m.
    trail = (Trail.objects.filter(is_published=True, start__distance_lte=(start, D(m=500)))
             .annotate(d=Distance("start", start)).order_by("d").first())
    act = Activity.objects.create(
        user=request.user, name=data["name"], geom=geom, length_m=data["length_m"], gain_m=data["gain_m"],
        moving_seconds=data["moving_seconds"], started_at=data["started_at"], trail=trail,
    )
    return JsonResponse(serializers.activity(act), status=201)


@require_GET
@_login_json
def api_activities(request):
    return JsonResponse({"results": [serializers.activity(a) for a in request.user.activities.select_related("trail")[:100]]})
