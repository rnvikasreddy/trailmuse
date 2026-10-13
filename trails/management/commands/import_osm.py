import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from trails import importer, osm


class Command(BaseCommand):
    help = "Import trails and parks from OpenStreetMap (Overpass API) for the launch region."

    def add_arguments(self, parser):
        parser.add_argument("--bbox", help="west,south,east,north (default: REGION_BBOX setting)")
        parser.add_argument("--tile", type=float, default=0.25, help="tile size in degrees per Overpass request")
        parser.add_argument("--file", action="append", help="read Overpass JSON from a file instead of the network (repeatable)")
        parser.add_argument("--save-raw", help="also write the combined Overpass JSON to this file")
        parser.add_argument("--pause", type=float, default=2.0, help="seconds between Overpass requests")

    def handle(self, *args, **opts):
        if opts["file"]:
            responses = [json.load(open(f)) for f in opts["file"]]
        else:
            west, south, east, north = (tuple(float(x) for x in opts["bbox"].split(",")) if opts["bbox"] else settings.REGION_BBOX)
            tiles = osm.tile_bbox(west, south, east, north, opts["tile"])
            responses = []
            for i, (s, w, n, e) in enumerate(tiles, 1):
                self.stdout.write(f"Fetching tile {i}/{len(tiles)} ({s:.2f},{w:.2f} to {n:.2f},{e:.2f})")
                try:
                    responses.append(osm.fetch_overpass(settings.OVERPASS_URL, osm.overpass_query(s, w, n, e)))
                except Exception as exc:  # keep going; a re-run picks the tile up again
                    self.stderr.write(self.style.WARNING(f"  tile failed: {exc}"))
                time.sleep(opts["pause"])
            if not responses:
                raise CommandError("No data downloaded. Check that the server can reach the Overpass API.")
        data = importer.merge_overpass(responses)
        if opts["save_raw"]:
            json.dump(data, open(opts["save_raw"], "w"))
        parsed = osm.parse(data)
        self.stdout.write(f"Parsed {len(parsed['trails'])} trails and {len(parsed['parks'])} parks")
        result = importer.import_parsed(parsed)
        self.stdout.write(self.style.SUCCESS(
            f"Saved {result['parks']} parks; {result['created']} new trails, {result['updated']} updated. "
            "Next: python manage.py compute_elevation"
        ))
