from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from trails.models import Trail

# Once this many real trails are in, the illustrative sample trails are hidden.
MIN_REAL_TRAILS = 50


class Command(BaseCommand):
    help = "Import the region's trails from OpenStreetMap, add NASA elevation, and hide the samples. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--parts", type=int, default=2, help="split the region into parts x parts imports to keep memory low")

    def handle(self, *args, **opts):
        west, south, east, north = settings.REGION_BBOX
        n = opts["parts"]
        dx, dy = (east - west) / n, (north - south) / n
        for i in range(n):
            for j in range(n):
                bbox = f"{west + i * dx:.4f},{south + j * dy:.4f},{west + (i + 1) * dx:.4f},{south + (j + 1) * dy:.4f}"
                self.stdout.write(f"Importing part {i * n + j + 1}/{n * n}: {bbox}")
                try:
                    call_command("import_osm", bbox=bbox, stdout=self.stdout, stderr=self.stderr)
                except Exception as exc:  # one failed part shouldn't stop the rest
                    self.stderr.write(self.style.WARNING(f"  part failed: {exc}"))
        call_command("fetch_srtm", stdout=self.stdout, stderr=self.stderr)
        call_command("compute_elevation", stdout=self.stdout, stderr=self.stderr)
        real = Trail.objects.filter(is_published=True).exclude(source="sample").count()
        if real >= MIN_REAL_TRAILS:
            hidden = Trail.objects.filter(source="sample", is_published=True).update(is_published=False)
            self.stdout.write(f"{real} real trails published; hid {hidden} sample trails.")
        self.stdout.write(self.style.SUCCESS("Trail refresh finished."))
