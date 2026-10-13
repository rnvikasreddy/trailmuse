from django.urls import path

from . import views

urlpatterns = [
    path("", views.explore, name="explore"),
    path("trail/<slug:slug>/", views.explore, name="trail"),
    path("saved/", views.explore, name="saved"),
    path("me/hikes/", views.my_hikes, name="my_hikes"),
    path("api/trails", views.api_trails, name="api_trails"),
    path("api/trails/lines", views.api_trail_lines, name="api_trail_lines"),
    path("api/trails/<slug:slug>", views.api_trail, name="api_trail"),
    path("api/trails/<slug:slug>/save", views.api_toggle_save, name="api_toggle_save"),
    path("api/trails/<slug:slug>/reviews", views.api_review, name="api_review"),
    path("api/trails/<slug:slug>/photos", views.api_photo, name="api_photo"),
    path("api/activities", views.api_activities, name="api_activities"),
    path("api/activities/upload", views.api_upload_gpx, name="api_upload_gpx"),
]
