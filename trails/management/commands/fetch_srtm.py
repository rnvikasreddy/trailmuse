import gzip
import math
import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

# NASA SRTM tiles mirrored in the public AWS Terrain Tiles dataset (no account needed).
SKADI_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{ns}{lat:02d}/{name}.hgt.gz"


class Command(BaseCommand):
    help = "Download NASA SRTM elevation tiles covering the launch region into ELEVATION_DIR."

    def add_arguments(self, parser):
        parser.add_argument("--bbox", help="west,south,east,north (default: REGION_BBOX setting)")

    def handle(self, *args, **opts):
        west, south, east, north = (tuple(float(x) for x in opts["bbox"].split(",")) if opts["bbox"] else settings.REGION_BBOX)
        folder = settings.ELEVATION_DIR
        os.makedirs(folder, exist_ok=True)
        for lat in range(math.floor(south), math.floor(north) + 1):
            for lon in range(math.floor(west), math.floor(east) + 1):
                ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
                name = f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"
                path = os.path.join(folder, name + ".hgt")
                if os.path.exists(path):
                    self.stdout.write(f"{name}: already downloaded")
                    continue
                r = requests.get(SKADI_URL.format(ns=ns, lat=abs(lat), name=name), timeout=120)
                if r.status_code == 404:
                    self.stdout.write(f"{name}: no data (ocean)")
                    continue
                r.raise_for_status()
                with open(path + ".part", "wb") as f:
                    f.write(gzip.decompress(r.content))
                os.replace(path + ".part", path)
                self.stdout.write(f"{name}: saved")
        self.stdout.write(self.style.SUCCESS(f"Elevation tiles are in {folder}. Next: python manage.py compute_elevation"))
