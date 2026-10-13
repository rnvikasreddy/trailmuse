from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.db.models import Avg, Count
from django.urls import reverse
from django.utils.text import slugify

from . import geo

DIFFICULTY_CHOICES = [("easy", "Easy"), ("moderate", "Moderate"), ("hard", "Hard")]
ROUTE_CHOICES = [("loop", "Loop"), ("out_and_back", "Out & back"), ("point_to_point", "Point to point")]

# Reasons to hike. These drive the "What's your muse?" filters.
MUSES = [
    ("waterfall", "Waterfalls"),
    ("redwoods", "Redwoods"),
    ("ocean", "Ocean"),
    ("views", "Big views"),
    ("sunset", "Sunset"),
    ("workout", "Workout"),
    ("quiet", "Quiet escape"),
    ("wildlife", "Wildlife"),
    ("wildflowers", "Wildflowers"),
    ("family", "Kid-friendly"),
    ("date", "Date hike"),
]
MUSE_LABELS = dict(MUSES)


def unique_slug(model, text, instance_pk=None):
    base = slugify(text)[:70] or "trail"
    slug, n = base, 2
    while model.objects.filter(slug=slug).exclude(pk=instance_pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class Park(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=90, unique=True)
    agency = models.CharField(max_length=200, blank=True)
    website = models.URLField(blank=True)
    geom = models.MultiPolygonField(srid=4326, null=True, blank=True)
    osm_type = models.CharField(max_length=10, blank=True)
    osm_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["osm_type", "osm_id"], name="park_osm_unique", condition=models.Q(osm_id__isnull=False))]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Park, self.name, self.pk)
        super().save(*args, **kwargs)


class Trail(models.Model):
    SOURCES = [("osm", "OpenStreetMap"), ("sample", "Sample data"), ("staff", "Added by staff")]

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=90, unique=True)
    park = models.ForeignKey(Park, null=True, blank=True, on_delete=models.SET_NULL, related_name="trails")
    town = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    why = models.CharField("one-line reason to go", max_length=160, blank=True)

    geom = models.MultiLineStringField(srid=4326, null=True, blank=True)
    start = models.PointField(srid=4326)

    length_m = models.FloatField(default=0)
    gain_m = models.FloatField(default=0)
    min_elev_m = models.FloatField(null=True, blank=True)
    max_elev_m = models.FloatField(null=True, blank=True)
    # [[distance_m, elevation_m], ...] sampled along the main path
    profile = models.JSONField(default=list, blank=True)
    elevation_source = models.CharField(max_length=40, blank=True)

    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default="moderate")
    route_type = models.CharField(max_length=20, choices=ROUTE_CHOICES, default="out_and_back")
    dogs_allowed = models.BooleanField(null=True, blank=True, help_text="Leave empty when unknown")
    muses = ArrayField(models.CharField(max_length=20, choices=MUSES), default=list, blank=True)

    source = models.CharField(max_length=10, choices=SOURCES, default="osm")
    osm_type = models.CharField(max_length=10, blank=True)
    osm_id = models.BigIntegerField(null=True, blank=True)
    osm_tags = models.JSONField(default=dict, blank=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["osm_type", "osm_id"], name="trail_osm_unique", condition=models.Q(osm_id__isnull=False))]
        indexes = [models.Index(fields=["difficulty"]), models.Index(fields=["is_published", "length_m"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Trail, self.name, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("trail", args=[self.slug])

    @property
    def miles(self):
        return round(self.length_m / geo.M_PER_MILE, 1)

    @property
    def gain_ft(self):
        return round(self.gain_m * geo.FT_PER_M)

    @property
    def estimated_minutes(self):
        return geo.estimated_minutes(self.length_m, self.gain_m)

    def main_path(self):
        """The trail's pieces joined into one walkable line, as [(lon, lat), ...]."""
        if not self.geom:
            return []
        return geo.chain_lines([list(line.coords) for line in self.geom])

    def recompute_stats(self, rate_difficulty=True):
        """Recompute length, route type, gain and difficulty from geometry and profile."""
        if self.geom:
            lines = [list(line.coords) for line in self.geom]
            total = geo.multiline_length_m(lines)
            path = self.main_path()
            path_len = geo.line_length_m(path) if path else 0
            # Use the connected main path when it is most of the trail; otherwise the pieces' total.
            one_way = path_len if path_len >= 0.6 * total else total
            self.route_type = geo.route_type(path, path_len) if path else "out_and_back"
            self.length_m = one_way * 2 if self.route_type == "out_and_back" else one_way
        if self.profile:
            stats = geo.elevation_stats(self.profile)
            gain = stats["gain_m"] + (stats["loss_m"] if self.route_type == "out_and_back" else 0)
            self.gain_m = gain
            self.min_elev_m, self.max_elev_m = stats["min_m"], stats["max_m"]
        if rate_difficulty and self.length_m:
            self.difficulty = geo.difficulty(self.length_m, self.gain_m)


class Review(models.Model):
    trail = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    body = models.TextField(max_length=3000)
    hiked_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["trail", "user"], name="one_review_per_user")]

    def __str__(self):
        return f"{self.user} on {self.trail}: {self.rating}"


def photo_path(instance, filename):
    return f"trail_photos/{instance.trail_id}/{filename}"


class Photo(models.Model):
    trail = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name="photos")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=photo_path)
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SavedTrail(models.Model):
    trail = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name="saves")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_trails")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["trail", "user"], name="save_once")]


class Activity(models.Model):
    """A hike the user recorded elsewhere (GPX from a watch, Strava or AllTrails export)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activities")
    name = models.CharField(max_length=200)
    geom = models.MultiLineStringField(srid=4326)
    length_m = models.FloatField(default=0)
    gain_m = models.FloatField(default=0)
    moving_seconds = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    trail = models.ForeignKey(Trail, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-created_at"]
        verbose_name_plural = "activities"

    def __str__(self):
        return self.name


def rating_summary(trail_qs):
    return trail_qs.annotate(avg_rating=Avg("reviews__rating"), review_count=Count("reviews", distinct=True))
