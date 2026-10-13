/* Stigrr explore page: map, filters, trail list and trail pages. Plain JS, no build step. */
(function () {
  "use strict";
  var CFG = JSON.parse(document.getElementById("app-config").textContent);
  var INITIAL = JSON.parse(document.getElementById("initial-trail").textContent);
  var CSRF = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";
  var ML = {}; CFG.muses.forEach(function (m) { ML[m[0]] = m[1]; });
  var $ = function (id) { return document.getElementById(id); };
  var phone = function () { return window.matchMedia("(max-width: 760px)").matches; };

  var state = {
    q: "", muse: "", difficulty: "", maxMiles: "", dogs: false, sort: "popular",
    saved: location.pathname.indexOf("/saved") === 0,
    trail: INITIAL, list: [], count: 0
  };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }
  function eta(min) { if (min < 60) return min + " min"; var h = Math.floor(min / 60), m = min % 60; return h + "h" + (m ? " " + m + "m" : ""); }
  var ROUTE = { loop: "Loop", out_and_back: "Out & back", point_to_point: "Point to point" };
  function toast(msg) { var el = $("toast"); el.textContent = msg; el.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(function () { el.hidden = true; }, 2800); }
  function loginUrl() { return "/accounts/login/?next=" + encodeURIComponent(location.pathname); }

  function api(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ "X-CSRFToken": CSRF }, opts.headers || {});
    opts.credentials = "same-origin";
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401) { location.href = loginUrl(); throw new Error("login"); }
        if (!r.ok) throw new Error(j.error || "Something went wrong. Try again.");
        return j;
      });
    });
  }

  // ---------------- Map ----------------
  var KEY = CFG.maptilerKey;
  var OSM_STYLE = {
    version: 8,
    sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors' } },
    layers: [{ id: "osm", type: "raster", source: "osm" }]
  };
  function mt(name) { return "https://api.maptiler.com/maps/" + name + "/style.json?key=" + encodeURIComponent(KEY); }
  var STYLES = KEY
    ? [{ id: "outdoor", label: "Outdoor", url: mt("outdoor-v2") }, { id: "satellite", label: "Satellite", url: mt("hybrid") },
       { id: "topo", label: "Topo", url: mt("topo-v2") }, { id: "winter", label: "Winter", url: mt("winter-v2") }]
    : [{ id: "osm", label: "Map", url: OSM_STYLE }];
  function pref(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  var styleId = STYLES.some(function (s) { return s.id === pref("stigrr-style"); }) ? pref("stigrr-style") : STYLES[0].id;
  function styleUrl(id) { return STYLES.filter(function (s) { return s.id === id; })[0].url; }

  var b = CFG.regionBbox;
  var map = new maplibregl.Map({
    container: "map", style: styleUrl(styleId), bounds: [[b[0], b[1]], [b[2], b[3]]],
    fitBoundsOptions: { padding: padding() }, attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.ScaleControl({ unit: "imperial", maxWidth: 90 }), "bottom-right");
  function padding() { return phone() ? { top: 70, bottom: window.innerHeight * 0.5, left: 20, right: 20 } : { top: 70, bottom: 30, left: 460, right: 80 }; }

  var BRAND = "#3fbf5a", INK = "#10261a", SEL_GREEN = "#74d84c", SEL_EDGE = "#1f5f24";

  // Map icons drawn on a canvas, so they need no image files and stay sharp on any screen.
  function icon(size, draw) {
    var px = 2, c = document.createElement("canvas"); c.width = c.height = size * px;
    var g = c.getContext("2d"); g.scale(px, px); draw(g, size);
    return { image: g.getImageData(0, 0, size * px, size * px), opts: { pixelRatio: px } };
  }
  function arrowIcon(dir) {
    return icon(22, function (g, s) {
      g.beginPath(); g.arc(s / 2, s / 2, s / 2 - 1.5, 0, Math.PI * 2); g.fillStyle = "#fff"; g.fill();
      g.lineWidth = 2; g.strokeStyle = SEL_EDGE; g.stroke();
      g.save(); g.translate(s / 2, s / 2); g.scale(dir, 1);
      g.beginPath(); g.moveTo(-5, 0); g.lineTo(4.5, 0); g.moveTo(0.5, -4); g.lineTo(4.5, 0); g.lineTo(0.5, 4);
      g.lineWidth = 2.2; g.lineCap = "round"; g.lineJoin = "round"; g.strokeStyle = "#16301b"; g.stroke(); g.restore();
    });
  }
  function addIcons() {
    var icons = {
      "arrow-fwd": arrowIcon(1), "arrow-back": arrowIcon(-1),
      trailhead: icon(26, function (g, s) {
        var r = s / 2 - 2;
        g.beginPath(); g.arc(s / 2, s / 2, r + 1.5, 0, Math.PI * 2); g.fillStyle = "#fff"; g.fill();
        g.beginPath(); g.moveTo(s / 2, s / 2); g.arc(s / 2, s / 2, r, Math.PI / 2, Math.PI * 1.5); g.fillStyle = "#16301b"; g.fill();
        g.beginPath(); g.moveTo(s / 2, s / 2); g.arc(s / 2, s / 2, r, -Math.PI / 2, Math.PI / 2); g.fillStyle = SEL_GREEN; g.fill();
      })
    };
    Object.keys(icons).forEach(function (k) { if (!map.hasImage(k)) map.addImage(k, icons[k].image, icons[k].opts); });
  }
  var DIFF_COLOR = ["match", ["get", "difficulty"], "easy", "#2f9e5b", "moderate", "#e09a12", "hard", "#d64533", BRAND];
  var EMPTY = { type: "FeatureCollection", features: [] };
  var lastLines = EMPTY, terrainOn = false, hoverId = null;
  var hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, className: "map-tip" });

  // Our trail layers sit on top of whichever base map is chosen; they are re-added after every style switch.
  function addTrailLayers() {
    var glyphs = !!map.getStyle().glyphs;
    var font = null;
    map.getStyle().layers.some(function (l) { if (l.layout && Array.isArray(l.layout["text-font"])) { font = l.layout["text-font"]; return true; } return false; });
    var round = { "line-cap": "round", "line-join": "round" };
    var hover = ["boolean", ["feature-state", "hover"], false];

    map.addSource("lines", { type: "geojson", data: lastLines, promoteId: "slug" });
    map.addSource("starts", { type: "geojson", data: EMPTY, cluster: true, clusterMaxZoom: 11, clusterRadius: 44 });
    map.addSource("selected", { type: "geojson", data: EMPTY });
    map.addSource("selected-start", { type: "geojson", data: EMPTY });
    map.addSource("selected-path", { type: "geojson", data: EMPTY });
    if (KEY) map.addSource("terrain", { type: "raster-dem", url: "https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=" + encodeURIComponent(KEY), tileSize: 256 });

    map.addLayer({ id: "lines-case", type: "line", source: "lines", layout: round, paint: {
      "line-color": "#ffffff", "line-opacity": 0.9,
      "line-width": ["interpolate", ["linear"], ["zoom"], 9, ["case", hover, 6, 3], 13, ["case", hover, 10, 6], 16, ["case", hover, 13, 9]] } });
    map.addLayer({ id: "lines", type: "line", source: "lines", layout: round, paint: {
      "line-color": DIFF_COLOR,
      "line-width": ["interpolate", ["linear"], ["zoom"], 9, ["case", hover, 3.5, 1.6], 13, ["case", hover, 6, 3.2], 16, ["case", hover, 8, 5]] } });
    // The open trail, drawn like AllTrails: a bright green line with a dark edge, direction arrows and a trailhead marker.
    addIcons();
    map.addLayer({ id: "selected-case", type: "line", source: "selected", layout: round, paint: { "line-color": SEL_EDGE, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 8, 16, 14] } });
    map.addLayer({ id: "selected-line", type: "line", source: "selected", layout: round, paint: { "line-color": SEL_GREEN, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 4.5, 16, 8] } });
    if (glyphs && font) {
      map.addLayer({ id: "line-labels", type: "symbol", source: "lines", minzoom: 12.5, layout: {
        "symbol-placement": "line", "text-field": ["get", "name"], "text-font": font, "text-size": 12, "text-letter-spacing": 0.02, "symbol-spacing": 320
      }, paint: { "text-color": INK, "text-halo-color": "#ffffff", "text-halo-width": 1.8 } });
    }
    map.addLayer({ id: "clusters", type: "circle", source: "starts", filter: ["has", "point_count"], paint: {
      "circle-color": BRAND, "circle-opacity": 0.92, "circle-stroke-color": "#ffffff", "circle-stroke-width": 3,
      "circle-radius": ["step", ["get", "point_count"], 15, 10, 19, 50, 24] } });
    if (glyphs && font) {
      map.addLayer({ id: "cluster-count", type: "symbol", source: "starts", filter: ["has", "point_count"], layout: {
        "text-field": ["get", "point_count_abbreviated"], "text-font": font, "text-size": 13, "text-allow-overlap": true
      }, paint: { "text-color": "#0d3319" } });
    }
    map.addLayer({ id: "starts", type: "circle", source: "starts", filter: ["!", ["has", "point_count"]], paint: {
      "circle-color": BRAND, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.5,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 8.5] } });
    var arrows = { "symbol-placement": "line", "symbol-spacing": 150, "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-rotation-alignment": "map" };
    map.addLayer({ id: "sel-arrows", type: "symbol", source: "selected-path", minzoom: 10, layout: Object.assign({ "icon-image": "arrow-fwd", "icon-offset": [0, 0] }, arrows) });
    map.addLayer({ id: "sel-arrows-back", type: "symbol", source: "selected-path", minzoom: 10, filter: ["==", ["get", "route"], "out_and_back"],
      layout: Object.assign({ "icon-image": "arrow-back" }, arrows, { "icon-offset": [26, 0] }) });
    map.addLayer({ id: "selected-start", type: "symbol", source: "selected-start", layout: { "icon-image": "trailhead", "icon-allow-overlap": true, "icon-ignore-placement": true } });
    setStarts();
    setSelected(state.trail);
    if (terrainOn) map.setTerrain({ source: "terrain", exaggeration: 1.4 });
  }

  var first = true;
  map.on("style.load", function () {
    addTrailLayers();
    if (first) { first = false; loadArea(); if (state.trail) showTrail(state.trail, true); }
  });

  ["starts", "lines"].forEach(function (layer) {
    map.on("mousemove", layer, function (e) {
      map.getCanvas().style.cursor = "pointer";
      var f = e.features[0], t = byslug[f.properties.slug];
      if (layer === "lines") {
        if (hoverId && hoverId !== f.id) map.setFeatureState({ source: "lines", id: hoverId }, { hover: false });
        hoverId = f.id; map.setFeatureState({ source: "lines", id: hoverId }, { hover: true });
      }
      var name = t ? t.name : f.properties.name || "";
      if (name) hoverPopup.setLngLat(e.lngLat).setHTML("<b>" + esc(name) + "</b>" + (t ? "<span>" + cap(t.difficulty) + " · " + t.miles + " mi</span>" : "")).addTo(map);
    });
    map.on("mouseleave", layer, function () {
      map.getCanvas().style.cursor = ""; hoverPopup.remove();
      if (hoverId) { map.setFeatureState({ source: "lines", id: hoverId }, { hover: false }); hoverId = null; }
    });
    map.on("click", layer, function (e) { hoverPopup.remove(); openTrail(e.features[0].properties.slug, true); });
  });
  map.on("click", "clusters", function (e) {
    var f = e.features[0];
    map.getSource("starts").getClusterExpansionZoom(f.properties.cluster_id).then(function (z) {
      map.easeTo({ center: f.geometry.coordinates, zoom: z + 0.5, padding: padding() });
    });
  });
  map.on("mouseenter", "clusters", function () { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "clusters", function () { map.getCanvas().style.cursor = ""; });

  function setSelected(t) {
    if (!map.getSource("selected")) return;
    map.getSource("selected").setData(t && t.geometry ? { type: "Feature", properties: {}, geometry: t.geometry } : EMPTY);
    map.getSource("selected-start").setData(t ? { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [t.lon, t.lat] } } : EMPTY);
    var path = t && t.path && t.path.length > 1 ? { type: "Feature", properties: { route: t.route_type }, geometry: { type: "LineString", coordinates: t.path } } : EMPTY;
    map.getSource("selected-path").setData(path);
  }

  // Base map picker and 3D terrain
  function renderLayersMenu() {
    $("layersMenu").innerHTML = STYLES.map(function (s) {
      return '<button type="button" role="menuitemradio" aria-checked="' + (s.id === styleId) + '" data-style="' + s.id + '">' + esc(s.label) + "</button>";
    }).join("");
  }
  if (STYLES.length > 1) {
    $("layersBtn").hidden = false;
    renderLayersMenu();
    $("layersBtn").onclick = function (e) { e.stopPropagation(); var m = $("layersMenu"); m.hidden = !m.hidden; this.setAttribute("aria-expanded", String(!m.hidden)); };
    $("layersMenu").onclick = function (e) {
      var btn = e.target.closest("[data-style]"); if (!btn) return;
      styleId = btn.dataset.style; pref("stigrr-style", styleId); renderLayersMenu();
      $("layersMenu").hidden = true; $("layersBtn").setAttribute("aria-expanded", "false");
      map.setStyle(styleUrl(styleId), { diff: false });
    };
    document.addEventListener("click", function (e) { if (!e.target.closest("#layersMenu")) { $("layersMenu").hidden = true; $("layersBtn").setAttribute("aria-expanded", "false"); } });
  }
  if (KEY) {
    $("terrainBtn").hidden = false;
    $("terrainBtn").onclick = function () {
      terrainOn = !terrainOn;
      this.classList.toggle("on", terrainOn); this.setAttribute("aria-pressed", String(terrainOn));
      if (terrainOn) { map.setTerrain({ source: "terrain", exaggeration: 1.4 }); map.dragRotate.enable(); map.easeTo({ pitch: 60, duration: 800 }); }
      else { map.setTerrain(null); map.dragRotate.disable(); map.easeTo({ pitch: 0, bearing: 0, duration: 600 }); }
    };
  }

  var moved = false;
  map.on("moveend", function (e) { if (e.originalEvent) { moved = true; $("searchArea").hidden = !!state.trail; debounceLoad(); } });
  var loadTimer;
  function debounceLoad() { clearTimeout(loadTimer); loadTimer = setTimeout(loadArea, 350); }
  $("searchArea").onclick = function () { $("searchArea").hidden = true; loadArea(); };
  $("zin").onclick = function () { map.zoomIn(); };
  $("zout").onclick = function () { map.zoomOut(); };
  $("locate").onclick = function () {
    if (!navigator.geolocation) return toast("Your browser can't share location.");
    navigator.geolocation.getCurrentPosition(function (p) {
      map.flyTo({ center: [p.coords.longitude, p.coords.latitude], zoom: 11, padding: padding() });
    }, function () { toast("Location is off. Allow it in your browser to find trails near you."); }, { timeout: 8000 });
  };

  // ---------------- Data ----------------
  var byslug = {};
  function params(extra) {
    var p = new URLSearchParams();
    var bb = map.getBounds();
    p.set("bbox", [bb.getWest(), bb.getSouth(), bb.getEast(), bb.getNorth()].map(function (v) { return v.toFixed(5); }).join(","));
    if (state.q) p.set("q", state.q);
    if (state.muse) p.set("muse", state.muse);
    if (state.difficulty) p.set("difficulty", state.difficulty);
    if (state.maxMiles) p.set("max_miles", state.maxMiles);
    if (state.dogs) p.set("dogs", "1");
    if (state.saved) p.set("saved", "1");
    if (state.sort === "length") p.set("sort", "length");
    Object.keys(extra || {}).forEach(function (k) { p.set(k, extra[k]); });
    return p.toString();
  }
  var reqId = 0;
  function loadArea() {
    var id = ++reqId;
    // Searching by name looks across the whole region, not just the visible map.
    var extra = state.q || state.saved ? { bbox: CFG.regionBbox.join(",") } : {};
    api("/api/trails?" + params(extra)).then(function (j) {
      if (id !== reqId) return;
      state.list = j.results; state.count = j.count;
      j.results.forEach(function (t) { byslug[t.slug] = t; });
      setStarts();
      if (!state.trail) renderList();
    }).catch(function (e) { if (e.message !== "login") toast(e.message); });
    api("/api/trails/lines?" + params(Object.assign({ z: map.getZoom().toFixed(1) }, extra))).then(function (fc) {
      if (id !== reqId) return;
      lastLines = fc;
      if (map.getSource("lines")) map.getSource("lines").setData(fc);
    }).catch(function () {});
  }
  function setStarts() {
    if (!map.getSource("starts")) return;
    var feats = state.list.map(function (t) { return { type: "Feature", properties: { slug: t.slug }, geometry: { type: "Point", coordinates: [t.lon, t.lat] } }; });
    map.getSource("starts").setData({ type: "FeatureCollection", features: feats });
  }

  // ---------------- Filters ----------------
  function renderFilters() {
    var h = '<label class="fchip' + (state.difficulty ? " on" : "") + '" for="fDiff"><select id="fDiff" aria-label="Difficulty"><option value="">Difficulty</option><option value="easy">Easy</option><option value="moderate">Moderate</option><option value="hard">Hard</option></select></label>';
    h += '<label class="fchip' + (state.maxMiles ? " on" : "") + '" for="fLen"><select id="fLen" aria-label="Length"><option value="">Length</option><option value="3">Under 3 mi</option><option value="5">Under 5 mi</option><option value="8">Under 8 mi</option><option value="12">Under 12 mi</option></select></label>';
    h += '<button type="button" class="fchip' + (state.dogs ? " on" : "") + '" data-f="dogs">Dog friendly' + (state.dogs ? ' <span class="x" aria-hidden="true">×</span>' : "") + "</button>";
    CFG.muses.forEach(function (m) {
      var on = state.muse === m[0];
      h += '<button type="button" class="fchip' + (on ? " on" : "") + '" data-muse="' + m[0] + '" aria-pressed="' + on + '">' + esc(m[1]) + (on ? ' <span class="x" aria-hidden="true">×</span>' : "") + "</button>";
    });
    $("filters").innerHTML = h;
    $("fDiff").value = state.difficulty; $("fLen").value = state.maxMiles;
    $("fDiff").onchange = function () { state.difficulty = this.value; filtersChanged(); };
    $("fLen").onchange = function () { state.maxMiles = this.value; filtersChanged(); };
  }
  $("filters").addEventListener("click", function (e) {
    var btn = e.target.closest("button.fchip"); if (!btn) return;
    if (btn.dataset.f === "dogs") state.dogs = !state.dogs;
    if (btn.dataset.muse) state.muse = state.muse === btn.dataset.muse ? "" : btn.dataset.muse;
    filtersChanged();
  });
  function filtersChanged() { renderFilters(); if (state.trail) closeTrail(); loadArea(); }
  var qTimer;
  $("q").addEventListener("input", function () { var v = this.value.trim(); clearTimeout(qTimer); qTimer = setTimeout(function () { state.q = v; if (state.trail) closeTrail(); loadArea(); }, 250); });
  $("grab").onclick = function () { $("panel").classList.toggle("tall"); };

  // ---------------- List ----------------
  var MOUNTAIN = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M2 20 L9 8 L13 14 L16 10 L22 20Z"/></svg>';
  function thumb(t) { return t.photo ? '<img class="thumb" src="' + esc(t.photo) + '" alt="" loading="lazy">' : '<div class="thumb ' + t.difficulty + '">' + MOUNTAIN + "</div>"; }
  function rating(t) { return t.avg_rating ? '<span><span class="star">★</span> ' + t.avg_rating + " (" + t.review_count + ")</span>" : ""; }
  function renderList() {
    $("cta").hidden = true;
    var title = state.saved ? "Saved trails" : state.q ? "Results for “" + esc(state.q) + "”" : state.muse ? esc(ML[state.muse]) + " in this area" : "Trails in this area";
    var h = '<div class="list-head"><h2>' + title + "</h2><span>" + fmt(state.count) + (state.count === 1 ? " trail" : " trails") + "</span></div>";
    h += '<div class="list-sub" style="display:flex;justify-content:space-between;gap:8px;align-items:center"><span>' +
      (state.saved ? "Trails you saved." : "Move the map or pick a reason to go.") +
      '</span><select class="sort" id="sort" aria-label="Sort"><option value="popular">Most popular</option><option value="length">Shortest first</option></select></div>';
    if (state.saved && !CFG.loggedIn) {
      h += '<p class="empty"><a href="' + loginUrl() + '">Log in</a> to see the trails you saved.</p>';
    } else if (!state.list.length) {
      h += '<p class="empty">' + (state.saved ? "You haven't saved any trails yet. Open a trail and tap Save." : "No trails match here. Zoom out, move the map or remove a filter.") + "</p>";
    } else {
      h += state.list.map(function (t) {
        return '<button type="button" class="card" data-slug="' + esc(t.slug) + '">' + thumb(t) + "<div>" +
          '<div class="card-name">' + (t.saved ? '<span class="saved-mark" aria-label="Saved">♥ </span>' : "") + esc(t.name) + "</div>" +
          '<div class="card-park">' + esc(t.park || t.town) + "</div>" +
          '<div class="meta"><span class="dot ' + t.difficulty + '">' + cap(t.difficulty) + "</span>" + rating(t) + "<span>· " + t.miles + " mi</span><span>· Est. " + eta(t.est_minutes) + "</span></div>" +
          (t.why ? '<div class="why">' + esc(t.why) + "</div>" : "") + "</div></button>";
      }).join("");
      if (state.count > state.list.length) h += '<p class="list-sub" style="margin-top:12px">Showing the top ' + state.list.length + ". Zoom in to see more.</p>";
    }
    $("panelScroll").innerHTML = h;
    var sortEl = $("sort"); if (sortEl) { sortEl.value = state.sort; sortEl.onchange = function () { state.sort = this.value; loadArea(); }; }
  }
  $("panelScroll").addEventListener("click", function (e) { var c = e.target.closest(".card"); if (c) openTrail(c.dataset.slug, true); });

  // ---------------- Trail page ----------------
  var ICON = {
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>',
    share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
    heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
    heartOn: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
    camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
    car: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 16h14v-4l-2-5H7l-2 5v4zM5 16v2M19 16v2"/></svg>',
    loop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 7h9a4 4 0 0 1 0 8H8a4 4 0 0 1 0-8"/></svg>',
    out_and_back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 9h15l-3-3M20 15H5l3 3"/></svg>',
    point_to_point: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><path d="M7 12h10"/></svg>'
  };

  function openTrail(slug, fly) {
    api("/api/trails/" + encodeURIComponent(slug)).then(function (t) {
      history.pushState({ slug: slug }, "", "/trail/" + slug + "/");
      showTrail(t, fly);
    }).catch(function (e) { if (e.message !== "login") toast(e.message); });
  }

  function showTrail(t, fly) {
    state.trail = t; byslug[t.slug] = Object.assign(byslug[t.slug] || {}, t);
    document.title = t.name + " · Stigrr";
    $("searchArea").hidden = true;
    renderTrail(t);
    setStarts();
    setSelected(t);
    if (fly) {
      if (!state.listView) state.listView = { center: map.getCenter(), zoom: map.getZoom() };
      if (t.bbox) map.fitBounds([[t.bbox[0], t.bbox[1]], [t.bbox[2], t.bbox[3]]], { padding: padding(), maxZoom: 15, duration: 700 });
      else map.flyTo({ center: [t.lon, t.lat], zoom: Math.max(map.getZoom(), 12.5), padding: padding(), duration: 700 });
    }
    if (phone()) $("panel").classList.remove("tall");
  }

  function closeTrail(push) {
    state.trail = null;
    setSelected(null);
    document.title = "Stigrr";
    if (push !== false) history.pushState({}, "", state.saved ? "/saved/" : "/");
    setStarts(); renderList();
    // Return the map to where the list was, so the list matches what it showed before.
    if (!state.listView) return false;
    map.once("moveend", loadArea);
    map.easeTo({ center: state.listView.center, zoom: state.listView.zoom, duration: 500 });
    state.listView = null;
    return true;
  }
  window.addEventListener("popstate", function () {
    var m = location.pathname.match(/^\/trail\/([^/]+)\/?$/);
    if (m) api("/api/trails/" + m[1]).then(function (t) { showTrail(t, true); });
    else { state.saved = location.pathname.indexOf("/saved") === 0; if (!closeTrail(false)) loadArea(); }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && state.trail) closeTrail(); });

  function gallery(t) {
    if (!t.photos.length) return '<div class="no-photos"><span>No photos yet. ' + (CFG.loggedIn ? "Be the first to add one." : '<a href="' + loginUrl() + '">Log in</a> to add the first one.') + "</span></div>";
    var ps = t.photos.slice(0, 3);
    return '<div class="gallery' + (ps.length === 1 ? " one" : "") + '">' + ps.map(function (p) { return '<img src="' + esc(p.url) + '" alt="' + esc(p.caption || "Trail photo by " + p.by) + '" loading="lazy">'; }).join("") + "</div>";
  }

  function renderTrail(t) {
    var tags = (t.muses || []).map(function (m) { return '<span class="tag muse">' + esc(ML[m] || m) + "</span>"; }).join("");
    tags += t.dogs_allowed === true ? '<span class="tag">Dogs on leash</span>' : t.dogs_allowed === false ? '<span class="tag">No dogs</span>' : "";
    tags += '<span class="tag">Hiking</span>';
    var park = t.park ? (t.park_website ? '<a href="' + esc(t.park_website) + '" target="_blank" rel="noopener">' + esc(t.park) + "</a>" : esc(t.park)) : esc(t.town);
    var h =
      '<div class="d-top"><button class="round" type="button" id="back" aria-label="Back to trails">' + ICON.back + '</button><button class="round" type="button" id="share" aria-label="Share trail">' + ICON.share + "</button></div>" +
      '<h1 class="d-name">' + esc(t.name) + "</h1>" +
      '<div class="d-park">' + park + "</div>" +
      '<div class="meta"><span class="dot ' + t.difficulty + '">' + cap(t.difficulty) + "</span>" + rating(t) + (t.town ? "<span>· " + esc(t.town) + "</span>" : "") + "</div>" +
      '<div class="d-actions"><button class="obtn' + (t.saved ? " on" : "") + '" type="button" id="save" aria-pressed="' + !!t.saved + '">' + (t.saved ? ICON.heartOn + " Saved" : ICON.heart + " Save") + "</button>" +
      '<button class="obtn" type="button" id="share2">' + ICON.share + " Share</button>" +
      (CFG.loggedIn ? '<label class="obtn" for="photoFile">' + ICON.camera + ' Add photo</label><input id="photoFile" type="file" accept="image/*" hidden>' : "") + "</div>" +
      gallery(t) +
      '<div class="statrow">' +
        '<div class="stat"><b>' + t.miles + ' mi</b><span>Length</span></div>' +
        '<div class="stat"><b>' + fmt(t.gain_ft) + ' ft</b><span>Elevation gain</span></div>' +
        '<div class="stat"><b>' + eta(t.est_minutes) + '</b><span>Estimated time</span></div>' +
        '<div class="stat">' + (ICON[t.route_type] || "") + "<span>" + (ROUTE[t.route_type] || "") + "</span></div>" +
      "</div>" +
      '<div class="tags">' + tags + "</div>" +
      (t.description ? '<p class="d-desc">' + esc(t.description) + "</p>" : "") +
      elevationSection(t) +
      reviewsSection(t) +
      '<p class="note">' + (t.source === "sample" ? "Sample trail with approximate figures. " : "") +
      (t.osm_url ? 'Trail data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (<a href="' + esc(t.osm_url) + '" target="_blank" rel="noopener">view or fix it</a>). ' : "") +
      "Check the park's official page for closures before you go.</p>";
    $("panelScroll").innerHTML = h;
    $("panelScroll").scrollTop = 0;
    $("cta").innerHTML = '<a href="https://www.google.com/maps/dir/?api=1&destination=' + t.lat + "," + t.lon + '" target="_blank" rel="noopener">' + ICON.car + " Get directions</a>";
    $("cta").hidden = false;
    $("back").onclick = function () { closeTrail(); };
    $("save").onclick = function () {
      if (!CFG.loggedIn) { location.href = loginUrl(); return; }
      api("/api/trails/" + t.slug + "/save", { method: "POST" }).then(function (j) {
        t.saved = j.saved; if (byslug[t.slug]) byslug[t.slug].saved = j.saved;
        renderTrail(t); toast(j.saved ? "Saved to your trails" : "Removed from saved");
      }).catch(function (e) { if (e.message !== "login") toast(e.message); });
    };
    $("share").onclick = $("share2").onclick = function () {
      var url = location.origin + "/trail/" + t.slug + "/";
      if (navigator.share) { navigator.share({ title: t.name, url: url }).catch(function () {}); return; }
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { toast("Link copied"); }, function () { toast(url); });
      else toast(url);
    };
    var pf = $("photoFile");
    if (pf) pf.onchange = function () {
      if (!pf.files.length) return;
      var fd = new FormData(); fd.append("image", pf.files[0]);
      toast("Uploading photo…");
      api("/api/trails/" + t.slug + "/photos", { method: "POST", body: fd }).then(function (p) {
        t.photos.unshift(p); renderTrail(t); toast("Photo added");
      }).catch(function (e) { if (e.message !== "login") toast(e.message); });
    };
    var rf = $("reviewForm");
    if (rf) rf.onsubmit = function (e) {
      e.preventDefault();
      var fd = new FormData(rf);
      var body = { rating: Number(fd.get("rating") || 0), body: fd.get("body"), hiked_on: fd.get("hiked_on") || null };
      $("reviewMsg").textContent = "";
      api("/api/trails/" + t.slug + "/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) {
        toast("Review posted");
        // Reload the trail so the average rating and count include this review.
        return api("/api/trails/" + t.slug).then(function (fresh) { if (state.trail && state.trail.slug === fresh.slug) showTrail(fresh, false); });
      }).catch(function (err) { if (err.message !== "login") $("reviewMsg").textContent = err.message; });
    };
  }

  function elevationSection(t) {
    var pts = t.profile || [];
    if (pts.length < 2) return "";
    var w = 380, h = 140, l = 4, r = 50, top = 10, bot = 22;
    var elevs = pts.map(function (p) { return p[1] * 3.28084; });
    var lo = Math.floor(Math.min.apply(null, elevs) / 100) * 100, hi = Math.ceil(Math.max.apply(null, elevs) / 100) * 100;
    if (hi - lo < 200) hi = lo + 200;
    var maxD = pts[pts.length - 1][0];
    var X = function (d) { return l + d / maxD * (w - l - r); };
    var Y = function (v) { return top + (1 - (v - lo) / (hi - lo)) * (h - top - bot); };
    var d = pts.map(function (p, i) { return (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(elevs[i]).toFixed(1); }).join("");
    var s = '<svg class="profile" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="Elevation from ' + fmt(lo) + " to " + fmt(hi) + ' feet">';
    [lo, hi].forEach(function (v) { s += '<line class="grid" x1="' + l + '" x2="' + (w - r) + '" y1="' + Y(v) + '" y2="' + Y(v) + '"/><text x="' + (w - r + 6) + '" y="' + (Y(v) + 4) + '">' + fmt(v) + " ft</text>"; });
    s += '<path class="fill" d="' + d + "L" + X(maxD) + "," + (h - bot) + "L" + l + "," + (h - bot) + 'Z"/><path class="line" d="' + d + '"/>';
    s += '<text x="' + l + '" y="' + (h - 6) + '">0 mi</text><text x="' + (w - r) + '" y="' + (h - 6) + '" text-anchor="end">' + (maxD / 1609.344).toFixed(1) + " mi</text></svg>";
    var src = /^sample/.test(t.elevation_source) ? "Illustrative profile" : "NASA SRTM elevation data";
    return '<div class="sec">Elevation <small>' + (t.profile_one_way ? "One way · " : "") + src + "</small></div>" + s;
  }

  function stars(n) { var s = ""; for (var i = 1; i <= 5; i++) s += i <= n ? "★" : "☆"; return '<span class="star" aria-label="' + n + ' out of 5 stars">' + s + "</span>"; }
  function reviewsSection(t) {
    var h = '<div class="sec">Reviews <small>' + (t.review_count ? (t.avg_rating + " ★ · " + t.review_count + (t.review_count === 1 ? " review" : " reviews")) : "None yet") + "</small></div>";
    if (CFG.loggedIn) {
      var mine = t.my_review || {};
      h += '<form class="rform" id="reviewForm"><div class="row"><div class="stars" role="radiogroup" aria-label="Your rating">';
      for (var i = 5; i >= 1; i--) h += '<input type="radio" name="rating" id="r' + i + '" value="' + i + '"' + (mine.rating === i ? " checked" : "") + '><label for="r' + i + '" title="' + i + ' stars">★</label>';
      h += '</div><input type="date" name="hiked_on" aria-label="Date hiked" value="' + esc(mine.hiked_on || "") + '"></div>' +
        '<textarea name="body" placeholder="How was it? Trail conditions, parking, what you saw…" aria-label="Your review">' + esc(mine.body || "") + "</textarea>" +
        '<div class="row"><span class="error" id="reviewMsg" role="alert"></span><button class="pill" type="submit">' + (t.my_review ? "Update review" : "Post review") + "</button></div></form>";
    } else {
      h += '<p class="muted"><a href="' + loginUrl() + '">Log in</a> to write a review.</p>';
    }
    h += (t.reviews || []).map(function (r) {
      return '<div class="review"><div class="review-head"><b>' + esc(r.user) + "</b>" + stars(r.rating) + "</div>" +
        '<div class="muted" style="font-size:0.8rem">' + (r.hiked_on ? "Hiked " + new Date(r.hiked_on + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "") + "</div><p>" + esc(r.body) + "</p></div>";
    }).join("");
    return h;
  }

  renderFilters();
  if (!state.trail) renderList();
})();
