# Stigrr

*Stigrr* comes from the Swedish *stig*, "trail" or "footpath".

Find Bay Area hikes by what you're in the mood for: waterfalls, redwoods, ocean, big views, a sunset or a date hike.
A free trail map in the style of AllTrails and Strava, built on open data.

- **Explore**: full-screen map with the trail list on the left (bottom sheet on phones), search, difficulty and length filters, dog-friendly, and "muse" chips.
- **Trail pages**: length, elevation gain, estimated time, route type, elevation profile, photos, reviews, directions, share link.
- **Accounts**: sign up, save trails, write reviews, upload photos, upload GPX hikes from Strava/AllTrails/a watch ("My hikes").
- **Data tools**: import trails and parks from OpenStreetMap, add elevation from NASA SRTM, edit anything in the admin.

Stack: Django 5.1 + GeoDjango, PostgreSQL + PostGIS, MapLibre GL, plain JS (no build step).

## Run it locally

### With Docker (easiest)

```sh
docker compose up --build
docker compose exec web python manage.py seed_sample        # 16 sample Bay Area trails
docker compose exec web python manage.py createsuperuser    # for /admin
```

Open http://localhost:8000.

### Without Docker

Needs Python 3.11+, PostgreSQL 14+ with PostGIS, and GDAL (`brew install postgis gdal` on a Mac, `apt install postgis gdal-bin` on Ubuntu).

```sh
createdb trailmuse && psql trailmuse -c "CREATE EXTENSION postgis"
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit DATABASE_URL if needed, then export the variables
python manage.py migrate
python manage.py seed_sample
python manage.py runserver
```

Run the tests with `python manage.py test trails accounts`.

## Map tiles

Without a key the map uses OpenStreetMap's public tiles, which are fine for development but not allowed for a public site.
For the real site, make a free account at https://cloud.maptiler.com, copy the API key and set `MAPTILER_KEY`.
The map then uses MapTiler's Outdoor style (contours, hillshade, trails). The free plan (5,000 map sessions a month) is for testing and non-commercial use; a public launch needs the Flex plan or Mapbox.

## Loading real trails

The 16 sample trails have approximate figures and illustrative elevation profiles. To load real trails:

```sh
# 1. Trails and parks from OpenStreetMap (whole Bay Area, in 0.25° tiles; takes a while)
python manage.py import_osm
#    or a smaller area:  python manage.py import_osm --bbox=-122.7,37.8,-122.4,38.0
#    or from a saved Overpass file:  python manage.py import_osm --file bay.json

# 2. Elevation profiles, gain and difficulty
python manage.py fetch_srtm
python manage.py compute_elevation
```

`fetch_srtm` downloads the NASA SRTM tiles for the region (about 150 MB, from the public AWS Terrain Tiles mirror) into `data/srtm/`, and `compute_elevation` then works offline. Without tiles it falls back to the free OpenTopoData API, which allows only about 1,000 requests a day.
Re-running the import updates trails in place. Trails you edit in the admin and mark "Take over" (source = staff) are never overwritten.

Once real trails are in, unpublish the samples in the admin (filter by source = sample, action "Unpublish").

Both commands need outbound access to `overpass-api.de` and `api.opentopodata.org`.

### The whole US

For whole states, use Geofabrik's OpenStreetMap extracts instead of the Overpass API:

```bash
# needs osmium-tool (apt install osmium-tool)
curl -LO https://download.geofabrik.de/north-america/us/oregon-latest.osm.pbf
python manage.py import_pbf oregon-latest.osm.pbf --elevation
```

`--elevation` downloads the NASA tiles the state's trails need and builds profiles as it saves. The GitHub workflow **Import trails** (Actions tab, Run workflow) does this for every state, one at a time, into the live database. It needs a repository secret `RENDER_DATABASE_URL` holding the External Database URL from Render. NASA's elevation data stops at 60°N, so most of Alaska gets trails without profiles.

## Trail photos

```bash
python manage.py fetch_photos            # Wikimedia Commons; add NPS_API_KEY for National Park Service photos
```

Attaches up to 3 free photos per trail: geotagged Wikimedia Commons photos within 250 m of the trail (free licenses only, no signs or maps), and public-domain NPS photos (free key at developer.nps.gov). Each photo keeps its photographer, license and a link back, shown under the trail's gallery. Hikers' own uploads always show first. On GitHub, run the **Find trail photos** workflow; it resumes where it stopped.

## Deploy

`render.yaml` is a Render Blueprint: a Docker web service with a 5 GB disk for photos, plus a Postgres database (PostGIS is enabled by the first migration).
In Render choose **New → Blueprint**, pick this repo, then set `MAPTILER_KEY`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` for your domain.
The first start loads the sample trails. The `trailmuse-refresh` cron job then imports real trails and elevation every Tuesday (`python manage.py refresh_trails`); use **Trigger Run** in Render to run it right away.

Any host that runs a Docker image and offers Postgres with PostGIS works the same way (Fly.io, Railway, a VPS). Settings are environment variables; see `.env.example`.
With `DEBUG=0` the app refuses to start without a `SECRET_KEY`.

## Data and credits

Trail and park data © OpenStreetMap contributors, available under the Open Database License. The app credits OSM on the map and on every imported trail page.
Elevation: NASA SRTM. Map style: MapTiler (when configured).

## Layout

```
config/            settings, urls
trails/            models, API views, OSM importer, elevation, GPX, admin
  management/      import_osm, compute_elevation, seed_sample
  static/trails/   app.js, app.css, logo
  templates/       explore page, my hikes
  tests/           test suite and fixtures
accounts/          sign up, log in, log out
```
