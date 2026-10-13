from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import Activity, Park, Photo, Review, SavedTrail, Trail


@admin.register(Trail)
class TrailAdmin(GISModelAdmin):
    list_display = ("name", "park", "difficulty", "miles", "gain_ft", "source", "is_published")
    list_filter = ("difficulty", "source", "is_published", "route_type")
    search_fields = ("name", "park__name", "town")
    readonly_fields = ("osm_type", "osm_id", "osm_tags", "created_at", "updated_at")
    autocomplete_fields = ("park",)
    actions = ["publish", "unpublish", "take_over"]

    @admin.action(description="Publish selected trails")
    def publish(self, request, qs):
        qs.update(is_published=True)

    @admin.action(description="Hide selected trails")
    def unpublish(self, request, qs):
        qs.update(is_published=False)

    @admin.action(description="Mark as staff-edited (future OSM imports won't overwrite)")
    def take_over(self, request, qs):
        qs.update(source="staff")


@admin.register(Park)
class ParkAdmin(GISModelAdmin):
    list_display = ("name", "agency", "website")
    search_fields = ("name",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("trail", "user", "rating", "created_at")
    search_fields = ("trail__name", "user__username", "body")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("trail", "source", "user", "credit", "license", "created_at")
    list_filter = ("source",)
    raw_id_fields = ("trail", "user")


admin.site.register(SavedTrail)
admin.site.register(Activity, GISModelAdmin)
admin.site.site_header = "Stigrr admin"
