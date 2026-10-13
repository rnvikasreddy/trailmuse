"""Find free photos for trails: Wikimedia Commons (geotagged, freely licensed) and the National Park Service.

Commons is searched once per ~10 km map square, and each trail takes the nearest good photos
within NEAR_M of its path. NPS "places" (trailheads, viewpoints, falls) are matched the same
way, and trails in a national park with no closer photo get one of the park's own photos.
Every photo keeps its author, license and a link back, which the site shows as the credit.
"""
import html
import re
import time

import requests

from . import geo

USER_AGENT = "Stigrr/1.0 (https://stigrr.com; trail photo matching)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
NPS_API = "https://developer.nps.gov/api/v1"
NEAR_M = 250
PER_TRAIL = 3
SEARCH_RADIUS_M = 10000  # Commons' maximum

# Whole license names only: "CC BY-NC" and "CC BY-ND" must not slip through as "CC BY".
FREE_LICENSE = re.compile(r"(cc0( 1\.0)?|cc[ -]by(-sa)?( \d\.\d)?( [a-z]{2,3})?|public domain|pd[- ].*|attribution)", re.I)
NOT_SCENERY = re.compile(r"\b(map|maps|sign|signs|signage|logo|diagram|plan|chart|plaque|brochure|marker|kiosk|scan|document)\b", re.I)
# Close-ups of a species ("Mariana Swiftlet (Aerodramus bartschi)", iNaturalist's "Ficus microcarpa 451514630")
# and photos of things (planes, cars, people, exhibits) are not views of the trail.
SPECIES_TITLE = re.compile(r"\([A-Z][a-z]+ [a-z]+\)|^File:[A-Z][a-z]+ [a-z]+( [a-z]+)? \d{5,}")
NOT_SCENERY_CATEGORY = re.compile(
    r"inaturalist|taxon|species|\bbirds?\b|insects?|butterfl|moths?\b|spiders?|reptiles|amphibians|mammals|fungi|mushrooms|lichens|"
    r"flowers?\b|plants? (by|of|in)|leaves|aircraft|airplanes|aviation|vehicles|\bcars\b|automobiles|ships|boats|buses|trains|locomotives|"
    r"people|portraits|men\b|women\b|children|food|interiors|museum|exhibits|statues|sculptures|specimens|animals|dogs|cats|horses", re.I)
SCENIC = re.compile(
    r"trail|hik(e|ing)|view|vista|overlook|lookout|peak|summit|mount|mountain|falls|waterfall|lake|river|creek|canyon|ridge|valley|"
    r"forest|woods|beach|coast|park|landscape|meadow|preserve|path|sunset|sunrise|cliff|bluff|gorge|hill|point|reserve|wilderness", re.I)


def strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class Commons:
    def __init__(self, session=None, pause_s=0.2):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.pause_s = pause_s

    def _get(self, params):
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        for attempt in range(5):
            resp = self.session.get(COMMONS_API, params=params, timeout=60)
            if resp.status_code in (429, 503) or (resp.ok and resp.json().get("error", {}).get("code") == "maxlag"):
                time.sleep(5 * (attempt + 1))  # the wiki is busy; back off as the API asks
                continue
            resp.raise_for_status()
            time.sleep(self.pause_s)
            return resp.json()
        resp.raise_for_status()
        return {}

    def nearby(self, lon, lat, radius_m=SEARCH_RADIUS_M):
        """Geotagged files near a point: [((lon, lat), title), ...]."""
        data = self._get({"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": radius_m,
                          "gsnamespace": 6, "gslimit": 500})
        return [((g["lon"], g["lat"]), g["title"]) for g in data.get("query", {}).get("geosearch", [])]

    def details(self, titles):
        """Photo details for file titles that pass the checks: {title: photo dict}."""
        out = {}
        titles = list(titles)
        for n in range(0, len(titles), 50):
            data = self._get({"action": "query", "titles": "|".join(titles[n: n + 50]), "prop": "imageinfo",
                              "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1024,
                              "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName|Restrictions|Categories"})
            for page in data.get("query", {}).get("pages", []):
                info = (page.get("imageinfo") or [None])[0]
                photo = commons_photo(page.get("title", ""), info)
                if photo:
                    out[page["title"]] = photo
        return out


def commons_photo(title, info):
    """A usable photo from a Commons imageinfo record, or None (not a free, landscape scenery JPEG)."""
    if not info or info.get("mime") != "image/jpeg":
        return None
    w, h = info.get("width", 0), info.get("height", 0)
    if w < 800 or h < 500 or w < h * 0.9:
        return None
    meta = info.get("extmetadata", {})
    lic = strip_html(meta.get("LicenseShortName", {}).get("value"))
    if not FREE_LICENSE.fullmatch(lic) or strip_html(meta.get("Restrictions", {}).get("value")):
        return None
    name = strip_html(meta.get("ObjectName", {}).get("value")) or title.removeprefix("File:").rsplit(".", 1)[0]
    categories = strip_html(meta.get("Categories", {}).get("value"))
    if NOT_SCENERY.search(name) or NOT_SCENERY.search(title) or SPECIES_TITLE.search(title) or NOT_SCENERY_CATEGORY.search(categories):
        return None
    artist = strip_html(meta.get("Artist", {}).get("value")) or "Unknown photographer"
    return {
        "source": "commons",
        "remote_url": info.get("thumburl") or info["url"],
        "source_url": info.get("descriptionurl", ""),
        "credit": artist[:300],
        "license": lic[:80],
        "caption": name[:200],
        # Photos named or filed as a landscape (a peak, falls, a view) are preferred over other nearby shots.
        "scenic": bool(SCENIC.search(title) or SCENIC.search(categories)),
    }


class NPS:
    """National Park Service photos (needs a free key from developer.nps.gov)."""

    def __init__(self, api_key, session=None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _all(self, endpoint):
        items, start = [], 0
        while True:
            resp = self.session.get(f"{NPS_API}/{endpoint}", params={"limit": 500, "start": start, "api_key": self.api_key}, timeout=120)
            resp.raise_for_status()
            j = resp.json()
            items += j.get("data", [])
            start += 500
            if not j.get("data") or start >= int(j.get("total", 0)):
                return items

    def places(self):
        """Geotagged NPS places with a usable photo: [((lon, lat), photo), ...]."""
        out = []
        for p in self._all("places"):
            try:
                pt = (float(p["longitude"]), float(p["latitude"]))
            except (KeyError, TypeError, ValueError):
                continue
            photo = nps_photo(p.get("images") or [], p.get("url") or "", p.get("title") or "")
            if photo:
                out.append((pt, photo))
        return out

    def parks(self):
        """{park full name (lowercase): [photo, ...]} for national park units."""
        out = {}
        for p in self._all("parks"):
            photos = [ph for ph in (nps_photo([img], p.get("url") or "", p.get("fullName") or "") for img in p.get("images") or []) if ph]
            if photos and p.get("fullName"):
                out[p["fullName"].strip().lower()] = photos[:PER_TRAIL]
        return out


def nps_photo(images, page_url, name):
    """The first NPS image that is public domain (photos credited with © are someone else's)."""
    for img in images:
        credit = (img.get("credit") or "").strip()
        if not img.get("url") or "©" in credit or "copyright" in credit.lower():
            continue
        return {
            "source": "nps",
            "remote_url": img["url"],
            "source_url": page_url,
            "credit": (credit or "National Park Service")[:300],
            "license": "Public domain",
            "caption": (img.get("altText") or img.get("title") or name)[:200],
            "scenic": True,
        }
    return None


class PointGrid:
    """Points bucketed into ~1 km cells for 'what is within NEAR_M of this path' lookups."""

    CELL = 0.01

    def __init__(self, items):
        self.grid = {}
        for pt, value in items:
            self.grid.setdefault((int(pt[0] // self.CELL), int(pt[1] // self.CELL)), []).append((pt, value))

    def nearest(self, path, within=NEAR_M):
        """Values near the path, closest first, each once."""
        best = {}
        sample = path[:: max(1, len(path) // 40)] + [path[-1]]
        for p in sample:
            cx, cy = int(p[0] // self.CELL), int(p[1] // self.CELL)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for pt, value in self.grid.get((cx + dx, cy + dy), ()):
                        d = geo.haversine_m(p, pt)
                        key = id(value) if isinstance(value, dict) else value
                        if d <= within and d < best.get(key, (within + 1, None))[0]:
                            best[key] = (d, value)
        return [v for _, v in sorted(best.values(), key=lambda dv: dv[0])]
