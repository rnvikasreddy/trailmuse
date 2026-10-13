"""Elevation lookups from NASA SRTM data.

Two providers, tried in order:
  1. Local SRTM .hgt tiles in settings.ELEVATION_DIR (fast, offline, free). Each tile covers
     1x1 degree and is named after its south-west corner, e.g. N37W123.hgt.
  2. The OpenTopoData public API (srtm30m dataset), limited to 100 points per request and
     about 1 request per second, which is fine for a nightly batch.
"""
import math
import os
import struct
import time
from functools import lru_cache

import requests


class HgtProvider:
    name = "srtm-hgt"

    def __init__(self, folder):
        self.folder = folder

    def available(self):
        return os.path.isdir(self.folder) and any(f.lower().endswith(".hgt") for f in os.listdir(self.folder))

    @lru_cache(maxsize=16)
    def _tile(self, lat0, lon0):
        ns = "N" if lat0 >= 0 else "S"
        ew = "E" if lon0 >= 0 else "W"
        fname = f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}.hgt"
        path = os.path.join(self.folder, fname)
        if not os.path.exists(path):
            return None
        raw = open(path, "rb").read()
        size = int(math.isqrt(len(raw) // 2))  # 3601 for 1 arc-second, 1201 for 3 arc-second
        return size, raw

    def lookup(self, lon, lat):
        lat0, lon0 = math.floor(lat), math.floor(lon)
        tile = self._tile(lat0, lon0)
        if tile is None:
            return None
        size, raw = tile
        # Rows run north to south. Bilinear interpolation between the 4 surrounding samples.
        r = (lat0 + 1 - lat) * (size - 1)
        c = (lon - lon0) * (size - 1)
        r0, c0 = int(r), int(c)
        r1, c1 = min(r0 + 1, size - 1), min(c0 + 1, size - 1)

        def h(rr, cc):
            v = struct.unpack_from(">h", raw, (rr * size + cc) * 2)[0]
            return None if v == -32768 else v

        vals = [h(r0, c0), h(r0, c1), h(r1, c0), h(r1, c1)]
        if any(v is None for v in vals):
            good = [v for v in vals if v is not None]
            return sum(good) / len(good) if good else None
        fr, fc = r - r0, c - c0
        top = vals[0] * (1 - fc) + vals[1] * fc
        bottom = vals[2] * (1 - fc) + vals[3] * fc
        return top * (1 - fr) + bottom * fr

    def lookup_many(self, points):
        return [self.lookup(lon, lat) for lon, lat in points]


class OpenTopoDataProvider:
    name = "opentopodata-srtm30m"
    BATCH = 100

    def __init__(self, url, pause_s=1.1, session=None):
        self.url = url
        self.pause_s = pause_s
        self.session = session or requests.Session()

    def available(self):
        return bool(self.url)

    def lookup_many(self, points):
        out = []
        for i in range(0, len(points), self.BATCH):
            chunk = points[i: i + self.BATCH]
            locs = "|".join(f"{lat:.6f},{lon:.6f}" for lon, lat in chunk)
            resp = self.session.get(self.url, params={"locations": locs}, timeout=60)
            resp.raise_for_status()
            out += [r.get("elevation") for r in resp.json().get("results", [])]
            if i + self.BATCH < len(points):
                time.sleep(self.pause_s)
        return out


def build_profile(path, provider, step_m=30.0, max_points=400):
    """Sample elevations along a path. Returns [[distance_m, elevation_m], ...] (smoothed)."""
    from . import geo

    if len(path) < 2:
        return []
    total = geo.line_length_m(path)
    step = max(step_m, total / max_points)
    samples = geo.sample_line(path, step)
    elevs = provider.lookup_many([(lon, lat) for _, lon, lat in samples])
    pairs = [(d, e) for (d, _, _), e in zip(samples, elevs) if e is not None]
    if len(pairs) < 2:
        return []
    smoothed = geo.smooth([e for _, e in pairs], window=5)
    return [[round(d, 1), round(e, 1)] for (d, _), e in zip(pairs, smoothed)]
