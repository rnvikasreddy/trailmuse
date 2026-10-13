import gzip
import math
import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

# NASA SRTM tiles mirrored in the public AWS Terrain Tiles dataset (no account needed).
SKADI_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{ns}{lat:02d}/{name}.hgt.gz"


def tile_name(lat, lon):
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    return ns, f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def download_tiles(cells, folder, log=print):
    """Download SRTM tiles for (lat, lon) cells (south-west corners) that aren't in folder yet."""
    os.makedirs(folder, exist_ok=True)
    for lat, lon in sorted(cells):
        ns, name = tile_name(lat, lon)
        path = os.path.join(folder, name + ".hgt")
        if os.path.exists(path):
            continue
        r = requests.get(SKADI_URL.format(ns=ns, lat=abs(lat), name=name), timeout=120)
        if r.status_code in (403, 404):  # no tile: open ocean, or beyond SRTM's 60°N coverage
            log(f"{name}: no data")
            continue
        r.raise_for_status()
        with open(path + ".part", "wb") as f:
            f.write(gzip.decompress(r.content))
        os.replace(path + ".part", path)
        log(f"{name}: saved")


class Command(BaseCommand):
    help = "Download NASA SRTM elevation tiles covering the launch region into ELEVATION_DIR."

    def add_arguments(self, parser):
        parser.add_argument("--bbox", help="west,south,east,north (default: REGION_BBOX setting)")

    def handle(self, *args, **opts):
        west, south, east, north = (tuple(float(x) for x in opts["bbox"].split(",")) if opts["bbox"] else settings.REGION_BBOX)
        folder = settings.ELEVATION_DIR
        cells = [(lat, lon) for lat in range(math.floor(south), math.floor(north) + 1) for lon in range(math.floor(west), math.floor(east) + 1)]
        download_tiles(cells, folder, self.stdout.write)
        self.stdout.write(self.style.SUCCESS(f"Elevation tiles are in {folder}. Next: python manage.py compute_elevation"))
