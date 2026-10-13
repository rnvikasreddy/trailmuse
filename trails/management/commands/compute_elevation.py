from django.conf import settings
from django.contrib.gis.geos import Polygon
from django.core.management.base import BaseCommand, CommandError

from trails import elevation, muses
from trails.models import Trail


class Command(BaseCommand):
    help = "Build elevation profiles and gain for trails from NASA SRTM data, then refresh difficulty and muses."

    def add_arguments(self, parser):
        parser.add_argument("--provider", choices=["auto", "hgt", "opentopodata"], default="auto")
        parser.add_argument("--all", action="store_true", help="redo trails that already have a profile")
        parser.add_argument("--slug", action="append", help="only these trails")
        parser.add_argument("--bbox", help="only trails starting inside west,south,east,north")

    def handle(self, *args, **opts):
        hgt = elevation.HgtProvider(settings.ELEVATION_DIR)
        if opts["provider"] == "hgt" or (opts["provider"] == "auto" and hgt.available()):
            if not hgt.available():
                raise CommandError(f"No .hgt files in {settings.ELEVATION_DIR}")
            provider = hgt
        else:
            provider = elevation.OpenTopoDataProvider(settings.OPENTOPODATA_URL)
        self.stdout.write(f"Using {provider.name}")

        qs = Trail.objects.exclude(geom__isnull=True)
        if opts["bbox"]:
            box = Polygon.from_bbox(tuple(float(x) for x in opts["bbox"].split(",")))
            box.srid = 4326
            qs = qs.filter(start__within=box)
        if opts["slug"]:
            qs = qs.filter(slug__in=opts["slug"])
        elif not opts["all"]:
            qs = qs.filter(profile=[])
        done = failed = 0
        for trail in qs.iterator():
            try:
                profile = elevation.build_profile(trail.main_path(), provider)
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.WARNING(f"{trail.slug}: {exc}"))
                continue
            if not profile:
                failed += 1
                continue
            trail.profile = profile
            trail.elevation_source = provider.name
            trail.recompute_stats()
            if trail.source == "osm":
                suggested = muses.suggest(trail.name, trail.park.name if trail.park else "", trail.length_m, trail.gain_m, trail.difficulty, trail.osm_tags.get("_near"))
                trail.muses = sorted(set(trail.muses) | set(suggested))
            trail.save()
            done += 1
        self.stdout.write(self.style.SUCCESS(f"Profiles built for {done} trails ({failed} skipped)"))
