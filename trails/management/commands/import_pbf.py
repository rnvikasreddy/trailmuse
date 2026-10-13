import math
import os
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from trails import elevation, importer, osm, pbf
from trails.management.commands.fetch_srtm import download_tiles


class Command(BaseCommand):
    help = "Import trails and parks from an OpenStreetMap .osm.pbf extract (e.g. a Geofabrik state file)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="path to a .osm.pbf file")
        parser.add_argument("--no-filter", action="store_true", help="the file is already filtered (skip osmium tags-filter)")
        parser.add_argument("--elevation", action="store_true", help="also download SRTM tiles and build elevation profiles")

    def handle(self, *args, **opts):
        path = opts["file"]
        with tempfile.TemporaryDirectory() as tmp:
            if not opts["no_filter"]:
                if not shutil.which("osmium"):
                    raise CommandError("osmium-tool is needed to filter the extract (apt install osmium-tool), or pass --no-filter.")
                filtered = os.path.join(tmp, "filtered.osm.pbf")
                self.stdout.write("Filtering the extract down to trails, parks and points of interest...")
                subprocess.run(["osmium", "tags-filter", path, *pbf.FILTER_EXPRESSIONS, "-o", filtered, "--overwrite"], check=True)
                path = filtered
            data = pbf.read_elements(path)
        parsed = osm.parse(data)
        del data
        self.stdout.write(f"Parsed {len(parsed['trails'])} trails and {len(parsed['parks'])} parks")

        provider = None
        if opts["elevation"] and parsed["trails"]:
            cells = set()
            for t in parsed["trails"]:
                for line in t["lines"]:
                    for lon, lat in line[:: max(1, len(line) // 20)] + [line[-1]]:
                        cells.add((math.floor(lat), math.floor(lon)))
            self.stdout.write(f"Downloading NASA elevation for {len(cells)} map squares...")
            download_tiles(cells, settings.ELEVATION_DIR, self.stdout.write)
            provider = elevation.HgtProvider(settings.ELEVATION_DIR)

        self.stdout.write("Saving...")
        result = importer.import_parsed(parsed, provider=provider, log=self.stdout.write)
        real, hidden = importer.hide_samples_if_ready()
        if hidden:
            self.stdout.write(f"{real} real trails published; hid {hidden} sample trails.")
        self.stdout.write(self.style.SUCCESS(f"Saved {result['parks']} parks; {result['created']} new trails, {result['updated']} updated."))
