"""Load 16 well-known Bay Area trails so the app has something to show before the OpenStreetMap import.

Figures are approximate and the elevation profiles are illustrative. Each trail is marked
source="sample" and the trail page says so. Run `import_osm` and `compute_elevation` for real data.
"""
import math
import random

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from trails import geo
from trails.models import Park, Trail

# name, park, town, lon, lat, miles, gain_ft, low_ft, high_ft, shape, route, difficulty, dogs, muses, why, description
SAMPLES = [
    ("Dipsea Trail", "Mount Tamalpais State Park", "Mill Valley", -122.548, 37.906, 7.4, 2200, 0, 1360, "dipsea", "point_to_point", "hard", False, ["ocean", "redwoods", "workout"], "Stairs, redwoods and a run down to the beach.", "The route of the country's oldest trail race. Climb hundreds of steps out of Mill Valley, cross Muir Woods, crest Cardiac Hill and drop through forest to Stinson Beach. Plan a ride or bus back."),
    ("Mt. Tam East Peak Loop", "Mount Tamalpais State Park", "Mill Valley", -122.577, 37.928, 0.7, 150, 2360, 2571, "loop", "loop", "easy", False, ["views", "sunset", "family"], "The whole Bay below you for very little effort.", "A short loop around the summit of East Peak with a side trip to the fire lookout. On a clear day you can see the Golden Gate, the Farallones and the Sierra."),
    ("Cataract Falls Trail", "Mt. Tamalpais Watershed", "Fairfax", -122.632, 37.935, 2.8, 900, 650, 1550, "summit", "out_and_back", "moderate", True, ["waterfall", "quiet", "redwoods"], "A staircase of cascades in a mossy canyon.", "From Alpine Lake the trail climbs beside a chain of falls and pools under bay laurel and redwood. Best in winter and spring after rain."),
    ("Tennessee Valley Trail", "Golden Gate National Recreation Area", "Mill Valley", -122.536, 37.860, 3.4, 200, 0, 200, "descent", "out_and_back", "easy", False, ["ocean", "family", "wildlife"], "A gentle valley walk that ends at a hidden cove.", "A wide, nearly flat path down a quiet valley to a small beach between cliffs. Good with kids, and you often see hawks, bobcats and deer."),
    ("Muir Woods Main Trail", "Muir Woods National Monument", "Mill Valley", -122.581, 37.892, 2.0, 150, 150, 300, "flat", "loop", "easy", False, ["redwoods", "family"], "Old-growth redwoods on a flat boardwalk.", "A boardwalk loop through old-growth coast redwoods along Redwood Creek. Parking and shuttle reservations are required."),
    ("Alamere Falls via Coast Trail", "Point Reyes National Seashore", "Bolinas", -122.745, 37.934, 13.0, 1600, 0, 750, "rolling", "out_and_back", "hard", False, ["waterfall", "ocean", "workout"], "A waterfall that pours straight onto the beach.", "From Palomarin the trail passes ponds and bluffs to Wildcat Beach, where Alamere Creek drops onto the sand. Take the official route via Wildcat Beach, not the eroding cliff shortcut."),
    ("Tomales Point Trail", "Point Reyes National Seashore", "Inverness", -122.955, 38.190, 9.4, 1000, 50, 550, "descent", "out_and_back", "moderate", False, ["wildlife", "ocean", "quiet"], "Tule elk, wildflowers and ocean on both sides.", "A long, open walk to the tip of the peninsula with Tomales Bay on one side and the Pacific on the other. Tule elk graze beside the trail."),
    ("Lands End Trail", "Golden Gate National Recreation Area", "San Francisco", -122.505, 37.785, 3.4, 550, 50, 300, "rolling", "out_and_back", "easy", True, ["ocean", "sunset", "date", "views"], "Golden Gate views, shipwrecks and a labyrinth in the city.", "A cypress-lined cliff path from the Sutro Baths ruins toward the Legion of Honor, with the Golden Gate in view most of the way."),
    ("Mission Peak Trail", "Mission Peak Regional Preserve", "Fremont", -121.880, 37.512, 6.0, 2100, 400, 2517, "summit", "out_and_back", "hard", True, ["workout", "sunset", "views"], "A steady, sunny grind to the famous summit post.", "A relentless climb up open grassland to the pole at the top. Very little shade, so go early or near sunset and carry water."),
    ("Mt. Diablo Grand Loop", "Mount Diablo State Park", "Walnut Creek", -121.914, 37.882, 6.5, 1800, 2900, 3849, "loop", "loop", "hard", False, ["views", "wildflowers", "workout"], "One of the widest views in California.", "Circle the main peak on rocky single-track, then finish at the summit building. In spring the slopes fill with wildflowers."),
    ("Purisima Creek Redwoods Loop", "Purisima Creek Redwoods Preserve", "Half Moon Bay", -122.360, 37.430, 6.5, 1600, 500, 2000, "descent", "loop", "moderate", False, ["redwoods", "quiet"], "A deep, quiet redwood canyon above Half Moon Bay.", "Drop from Skyline Boulevard into a canyon of redwoods and ferns along Purisima Creek, then climb back out."),
    ("Uvas Canyon Waterfall Loop", "Uvas Canyon County Park", "Morgan Hill", -121.791, 37.085, 1.5, 350, 1000, 1350, "loop", "loop", "easy", True, ["waterfall", "family"], "Several small waterfalls on one short loop.", "A shaded loop past Black Rock Falls, Basin Falls and more along Swanson Creek. Best a few days after winter rain."),
    ("Wildcat Loop Trail", "Rancho San Antonio Preserve", "Los Altos Hills", -122.089, 37.333, 3.0, 500, 300, 800, "loop", "loop", "easy", False, ["family", "wildlife"], "A canyon loop with a working farm at the start.", "A shady creekside climb and an open-ridge return, starting near Deer Hollow Farm. Deer are almost guaranteed."),
    ("Mori Point Loop", "Golden Gate National Recreation Area", "Pacifica", -122.502, 37.616, 2.3, 400, 0, 400, "loop", "loop", "easy", True, ["ocean", "sunset", "wildflowers"], "A short headland loop with big Pacific views.", "Climb the Bootlegger's Steps to a bluff above the surf, then loop back past a lagoon."),
    ("Stream and French Trail Loop", "Redwood Regional Park", "Oakland", -122.166, 37.812, 4.5, 900, 550, 1100, "descent", "loop", "moderate", True, ["redwoods", "quiet"], "A redwood forest ten minutes from downtown Oakland.", "Wind down the Stream Trail beside a creek, then climb the narrow French Trail through tall redwoods."),
    ("Twin Peaks Summit Trail", "Twin Peaks Natural Area", "San Francisco", -122.447, 37.752, 0.8, 250, 650, 922, "summit", "out_and_back", "easy", True, ["views", "sunset", "date"], "The best 360° view of San Francisco.", "Short, steep paths to the two summits in the middle of the city. Come for sunset, and bring a jacket."),
]


def illustrative_profile(slug, miles, low_ft, high_ft, shape, n=80):
    rnd = random.Random(slug)
    noise = [rnd.random() - 0.5 for _ in range(n)]
    noise = [noise[0]] + [(noise[i - 1] + 2 * noise[i] + noise[i + 1]) / 4 for i in range(1, n - 1)] + [noise[-1]]
    ys = []
    for i in range(n):
        x = i / (n - 1)
        if shape == "summit":
            y = math.sin(math.pi * x)
        elif shape == "descent":
            y = 1 - math.sin(math.pi * x)
        elif shape == "loop":
            y = math.sin(math.pi * min(1, x * 1.15)) ** 1.2
        elif shape == "dipsea":
            y = 0.15 + x / 0.3 * 0.85 if x < 0.3 else (0.85 if x < 0.6 else max(0.0, 1 - (x - 0.6) / 0.4))
        elif shape == "rolling":
            y = 0.55 + 0.35 * math.sin(x * math.pi * 3) * (1 - abs(x - 0.5))
        else:
            y = 0.4 + 0.1 * math.sin(x * math.pi * 4)
        ys.append(y + noise[i] * 0.2)
    lo, hi = min(ys), max(ys)
    one_way_m = miles * geo.M_PER_MILE
    return [[round(i / (n - 1) * one_way_m, 1), round(((low_ft + (y - lo) / (hi - lo) * (high_ft - low_ft)) / geo.FT_PER_M), 1)] for i, y in enumerate(ys)]


class Command(BaseCommand):
    help = "Load 16 sample Bay Area trails (approximate figures) so the app works before the OSM import."

    def handle(self, *args, **opts):
        created = 0
        for (name, park, town, lon, lat, miles, gain_ft, low, high, shape, route, diff, dogs, muse_list, why, desc) in SAMPLES:
            park_obj, _ = Park.objects.get_or_create(name=park, osm_id=None, defaults={})
            trail, is_new = Trail.objects.update_or_create(
                name=name, source="sample",
                defaults=dict(
                    park=park_obj, town=town, start=Point(lon, lat, srid=4326),
                    length_m=miles * geo.M_PER_MILE, gain_m=gain_ft / geo.FT_PER_M,
                    min_elev_m=low / geo.FT_PER_M, max_elev_m=high / geo.FT_PER_M,
                    route_type=route, difficulty=diff, dogs_allowed=dogs, muses=muse_list,
                    why=why, description=desc, elevation_source="sample (illustrative)",
                ),
            )
            if not trail.profile:
                trail.profile = illustrative_profile(trail.slug, miles / (2 if route == "out_and_back" else 1), low, high, shape)
                trail.save(update_fields=["profile"])
            created += is_new
        self.stdout.write(self.style.SUCCESS(f"Sample trails ready ({created} new, {len(SAMPLES) - created} already there)."))
