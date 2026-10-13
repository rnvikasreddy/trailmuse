FROM python:3.12-slim

# GeoDjango needs the GDAL, GEOS and PROJ libraries.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gdal-bin binutils libproj-dev \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Build-time only key: collectstatic needs settings to load; the real key comes from the environment.
RUN DEBUG=0 SECRET_KEY=build-only-collectstatic python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["bin/start"]
