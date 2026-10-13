from django.conf import settings


def site(request):
    return {"MAPTILER_KEY": settings.MAPTILER_KEY, "REGION_NAME": settings.REGION_NAME}
