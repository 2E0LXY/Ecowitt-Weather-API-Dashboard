import asyncio
import base64
import json
import math
import os
import re
import sqlite3
import time
from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
from urllib.parse import quote, unquote, urljoin

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Weather Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

APPLICATION_KEY = os.getenv("APPLICATION_KEY", "")
API_KEY = os.getenv("API_KEY", "")
MAC_ADDRESS = os.getenv("MAC_ADDRESS", "")
ECOWITT_URL = os.getenv("ECOWITT_URL", "https://api.ecowitt.net/api/v3/device/real_time")
DB_PATH = os.getenv("WEATHER_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "weather_data.db"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
BACKUP_LLM_PROVIDER = os.getenv("BACKUP_LLM_PROVIDER", "openrouter").strip().lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_MODELS = os.getenv("OPENROUTER_MODELS", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SATELLITE_BASE_URL = os.getenv("SATELLITE_BASE_URL", "http://zx3de49.glddns.com:8080")
SATELLITE_AI_IMAGES_ENABLED = os.getenv("SATELLITE_AI_IMAGES_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
SATELLITE_AI_IMAGE_ENHANCEMENT = os.getenv("SATELLITE_AI_IMAGE_ENHANCEMENT", "equidistant_221_composite")
SATELLITE_AI_IMAGE_COUNT = max(0, min(4, int(os.getenv("SATELLITE_AI_IMAGE_COUNT", "2"))))
SATELLITE_AI_MAX_IMAGE_BYTES = int(os.getenv("SATELLITE_AI_MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))

WU_API_KEY = os.getenv("WU_API_KEY", "")
WU_API_BASE = "https://api.weather.com"
WU_CENTER_LAT = float(os.getenv("WU_CENTER_LAT", "53.75"))
WU_CENTER_LON = float(os.getenv("WU_CENTER_LON", "-1.52"))
WU_RADIUS_MILES = float(os.getenv("WU_RADIUS_MILES", "100"))
WU_MIN_STATION_SPACING_MILES = float(os.getenv("WU_MIN_STATION_SPACING_MILES", "10"))
WU_STATION_LIMIT = max(1, min(40, int(os.getenv("WU_STATION_LIMIT", "24"))))
WU_LOCAL_RADIUS_MILES = float(os.getenv("WU_LOCAL_RADIUS_MILES", "20"))
WU_CACHE_TTL_SECONDS = int(os.getenv("WU_CACHE_TTL_SECONDS", "3600"))

CEFAS_API_BASE = "https://wavenet-api.cefas.co.uk/api"
CEFAS_RADIUS_MILES = float(os.getenv("CEFAS_RADIUS_MILES", "100"))
CEFAS_BUOY_LIMIT = max(1, min(20, int(os.getenv("CEFAS_BUOY_LIMIT", "12"))))
CEFAS_CACHE_TTL_SECONDS = int(os.getenv("CEFAS_CACHE_TTL_SECONDS", "1800"))

CAPE_API_BASE = "https://api.open-meteo.com/v1/forecast"
CAPE_CACHE_TTL_SECONDS = int(os.getenv("CAPE_CACHE_TTL_SECONDS", "1800"))

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))

AI_CACHE_TTL_SECONDS = 900
_ai_cache = {"ts": 0.0, "payload": None}
AI_RETRY_COOLDOWN_SECONDS = 600
_ai_last_failure_ts = 0.0
SATELLITE_CACHE_TTL_SECONDS = 300
_satellite_cache = {"ts": 0.0, "payload": None}
_wu_cache = {"ts": 0.0, "payload": None}
_cefas_cache = {"ts": 0.0, "payload": None}
_cape_cache = {"ts": 0.0, "payload": None}


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def f_to_c(v):
    return (float(v) - 32.0) * 5.0 / 9.0 if v is not None else None


def mph_to_kmh(v):
    return float(v) * 1.60934 if v is not None else None


def in_to_mm(v):
    return float(v) * 25.4 if v is not None else None


def fmt_temp_dual(f_val, digits_c=1, digits_f=1):
    if f_val is None:
        return "--"
    c_val = f_to_c(f_val)
    return f"{c_val:.{digits_c}f}°C ({float(f_val):.{digits_f}f}°F)"


def fmt_wind_dual(mph_val, digits_kmh=1, digits_mph=1):
    if mph_val is None:
        return "--"
    kmh_val = mph_to_kmh(mph_val)
    return f"{kmh_val:.{digits_kmh}f} km/h ({float(mph_val):.{digits_mph}f} mph)"


def fmt_rain_rate_dual(inhr_val, digits_mm=1, digits_in=2):
    if inhr_val is None:
        return "--"
    mm_val = in_to_mm(inhr_val)
    return f"{mm_val:.{digits_mm}f} mm/hr ({float(inhr_val):.{digits_in}f} in/hr)"


def weather_comfort_score(temp_f, humidity, wind_mph, rain_rate_inhr, uv_index):
    if temp_f is None:
        return None
    ideal_temp = 68.0
    temp_penalty = abs(temp_f - ideal_temp) * 1.1
    humidity_penalty = 0.0 if humidity is None else abs(humidity - 50.0) * 0.4
    wind_penalty = 0.0 if wind_mph is None else max(0.0, wind_mph - 8.0) * 1.2
    rain_penalty = 0.0 if rain_rate_inhr is None else rain_rate_inhr * 10.0
    uv_penalty = 0.0 if uv_index is None else max(0.0, uv_index - 3.0) * 2.0
    score = 100.0 - (temp_penalty + humidity_penalty + wind_penalty + rain_penalty + uv_penalty)
    return round(max(0.0, min(100.0, score)), 2)


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _destination_point(lat, lon, bearing_deg, distance_km):
    R = 6371.0
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    theta = math.radians(bearing_deg)
    delta = distance_km / R
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lam2)


def _bearing_deg(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    theta = math.atan2(y, x)
    return (math.degrees(theta) + 360) % 360


_COMPASS_POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _compass_point(bearing_deg):
    idx = int((bearing_deg / 22.5) + 0.5) % 16
    return _COMPASS_POINTS[idx]


_OCTANTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _compass_octant(bearing_deg):
    idx = int((bearing_deg / 45.0) + 0.5) % 8
    return _OCTANTS[idx]


async def _wu_near_search(client, lat, lon):
    """Single nearest-10 lookup; returns [(stationId, name, lat, lon), ...]."""
    try:
        resp = await client.get(
            f"{WU_API_BASE}/v3/location/near",
            params={"geocode": f"{lat},{lon}", "product": "pws", "format": "json", "apiKey": WU_API_KEY},
        )
        resp.raise_for_status()
        loc = resp.json().get("location", {})
        ids = loc.get("stationId", [])
        names = loc.get("stationName", [])
        lats = loc.get("latitude", [])
        lons = loc.get("longitude", [])
        return list(zip(ids, names, lats, lons))
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        return []


async def fetch_wu_nearby_stations(force=False):
    """Fetch PWS stations within WU_RADIUS_MILES of the configured centre point.

    The WU v3/location/near API hard-caps each lookup at the 10 nearest stations
    to the queried geocode, so to cover a wider radius we issue several lookups
    from points arranged in a ring around the centre, merge + dedupe the results,
    then keep only stations whose true (haversine) distance from the centre is
    within the configured radius.
    """
    now = time.time()
    if not force and _wu_cache["payload"] and (now - _wu_cache["ts"] < WU_CACHE_TTL_SECONDS):
        cached = deepcopy(_wu_cache["payload"])
        cached["cached"] = True
        cached["cache_age_seconds"] = int(now - _wu_cache["ts"])
        return cached

    if not WU_API_KEY:
        raise HTTPException(status_code=500, detail="Missing WU_API_KEY")

    radius_km = WU_RADIUS_MILES * 1.60934
    min_spacing_km = WU_MIN_STATION_SPACING_MILES * 1.60934

    # Multi-ring radial sweep: each near() lookup only returns the 10 closest
    # stations to that point, so a single ring can't cover a 100mi disc -
    # use several concentric rings with more points per ring as radius grows.
    rings = [
        (0.20, 6),
        (0.45, 8),
        (0.70, 10),
        (0.95, 14),
    ]
    probe_points = [(WU_CENTER_LAT, WU_CENTER_LON)]
    for radius_frac, point_count in rings:
        ring_radius_km = radius_km * radius_frac
        bearing_step = 360.0 / point_count
        for i in range(point_count):
            bearing = i * bearing_step
            probe_points.append(_destination_point(WU_CENTER_LAT, WU_CENTER_LON, bearing, ring_radius_km))

    async with httpx.AsyncClient(timeout=20.0) as client:
        probe_results = await asyncio.gather(
            *[_wu_near_search(client, plat, plon) for plat, plon in probe_points]
        )

        candidates = {}
        for result in probe_results:
            for sid, name, slat, slon in result:
                if sid not in candidates:
                    candidates[sid] = {"station_id": sid, "name": name, "lat": slat, "lon": slon}

        scored = []
        for sid, info in candidates.items():
            try:
                dist_km = _haversine_km(WU_CENTER_LAT, WU_CENTER_LON, float(info["lat"]), float(info["lon"]))
            except (TypeError, ValueError):
                continue
            if dist_km <= radius_km:
                scored.append((dist_km, info))
        scored.sort(key=lambda x: x[0])
        stations_in_radius = len(scored)

        # Enforce minimum spacing between selected stations so the result set
        # is geographically spread across the full radius rather than
        # clustering around the densest spot (closest candidates win ties).
        spaced = []
        for dist_km, info in scored:
            try:
                lat, lon = float(info["lat"]), float(info["lon"])
            except (TypeError, ValueError):
                continue
            too_close = any(
                _haversine_km(lat, lon, float(sel["lat"]), float(sel["lon"])) < min_spacing_km
                for _, sel in spaced
            )
            if not too_close:
                spaced.append((dist_km, info))
        scored = spaced[:WU_STATION_LIMIT]

        sem = asyncio.Semaphore(5)

        async def fetch_obs(dist_km, info):
            sid = info["station_id"]
            async with sem:
                try:
                    obs_resp = await client.get(
                        f"{WU_API_BASE}/v2/pws/observations/current",
                        params={"stationId": sid, "format": "json", "units": "m", "apiKey": WU_API_KEY},
                    )
                    if obs_resp.status_code != 200:
                        return None
                    observations = obs_resp.json().get("observations", [])
                    if not observations:
                        return None
                    obs = observations[0]
                    metric = obs.get("metric", {})
                    obs_lat = obs.get("lat", info["lat"])
                    obs_lon = obs.get("lon", info["lon"])
                    try:
                        bearing = _bearing_deg(WU_CENTER_LAT, WU_CENTER_LON, float(obs_lat), float(obs_lon))
                        direction = _compass_point(bearing)
                        octant = _compass_octant(bearing)
                    except (TypeError, ValueError):
                        direction = None
                        octant = None
                    return {
                        "station_id": sid,
                        "name": info["name"],
                        "distance_km": round(dist_km, 2),
                        "distance_mi": round(dist_km / 1.60934, 2),
                        "direction_from_centre": direction,
                        "octant": octant,
                        "lat": obs_lat,
                        "lon": obs_lon,
                        "obs_time_local": obs.get("obsTimeLocal"),
                        "neighborhood": obs.get("neighborhood"),
                        "temp_c": metric.get("temp"),
                        "heat_index_c": metric.get("heatIndex"),
                        "dewpt_c": metric.get("dewpt"),
                        "wind_chill_c": metric.get("windChill"),
                        "humidity_pct": obs.get("humidity"),
                        "wind_dir_deg": obs.get("winddir"),
                        "wind_speed_kmh": metric.get("windSpeed"),
                        "wind_gust_kmh": metric.get("windGust"),
                        "pressure_hpa": metric.get("pressure"),
                        "precip_rate_mmhr": metric.get("precipRate"),
                        "precip_total_mm": metric.get("precipTotal"),
                        "uv": obs.get("uv"),
                        "solar_radiation": obs.get("solarRadiation"),
                    }
                except (httpx.HTTPStatusError, httpx.RequestError, ValueError, KeyError):
                    return None

        station_results = await asyncio.gather(*[fetch_obs(d, info) for d, info in scored])
        stations = [s for s in station_results if s]
        stations.sort(key=lambda s: s["distance_km"])

    def avg(items, field):
        vals = [s[field] for s in items if isinstance(s.get(field), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else None

    def summarize(items):
        return {
            "station_count": len(items),
            "temp_c_avg": avg(items, "temp_c"),
            "humidity_pct_avg": avg(items, "humidity_pct"),
            "wind_speed_kmh_avg": avg(items, "wind_speed_kmh"),
            "wind_gust_kmh_avg": avg(items, "wind_gust_kmh"),
            "wind_gust_kmh_max": max([s["wind_gust_kmh"] for s in items if isinstance(s.get("wind_gust_kmh"), (int, float))], default=None),
            "pressure_hpa_avg": avg(items, "pressure_hpa"),
            "precip_total_mm_avg": avg(items, "precip_total_mm"),
            "precip_total_mm_max": max([s["precip_total_mm"] for s in items if isinstance(s.get("precip_total_mm"), (int, float))], default=None),
            "stations_reporting_rain": sum(1 for s in items if isinstance(s.get("precip_rate_mmhr"), (int, float)) and s["precip_rate_mmhr"] > 0),
        }

    # Local Average: true near-field conditions, not blended with distant stations
    local_stations = [s for s in stations if s["distance_mi"] <= WU_LOCAL_RADIUS_MILES]
    local_summary = summarize(local_stations)
    local_summary["radius_miles"] = WU_LOCAL_RADIUS_MILES

    # By-direction breakdown of the far-field stations (>local radius), for
    # spotting weather approaching from a specific compass sector.
    directional_stations = [s for s in stations if s["distance_mi"] > WU_LOCAL_RADIUS_MILES]
    directional_summary = {}
    for octant in _OCTANTS:
        octant_stations = [s for s in directional_stations if s.get("octant") == octant]
        entry = summarize(octant_stations)
        entry["nearest_distance_mi"] = min((s["distance_mi"] for s in octant_stations), default=None)
        entry["farthest_distance_mi"] = max((s["distance_mi"] for s in octant_stations), default=None)
        directional_summary[octant] = entry

    # Overall blended summary kept for backward compatibility / fallback use
    overall_summary = summarize(stations)

    payload = {
        "status": "ok",
        "source": "Weather Underground PWS Network",
        "center": {"lat": WU_CENTER_LAT, "lon": WU_CENTER_LON},
        "radius_miles": WU_RADIUS_MILES,
        "local_radius_miles": WU_LOCAL_RADIUS_MILES,
        "min_spacing_miles": WU_MIN_STATION_SPACING_MILES,
        "cached": False,
        "cache_age_seconds": 0,
        "candidates_found": len(candidates),
        "stations_in_radius": stations_in_radius,
        "station_count": len(stations),
        "stations": stations,
        "local_summary": local_summary,
        "directional_summary": directional_summary,
        "regional_summary": overall_summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _wu_cache["payload"] = deepcopy(payload)
    _wu_cache["ts"] = time.time()
    return payload


async def fetch_cape_data(force=False):
    """Fetch CAPE and CIN from Open-Meteo (UKMO Seamless model).
    Free, no key needed. Raw indices only - no forecast text consumed."""
    now = time.time()
    if not force and _cape_cache["payload"] and (now - _cape_cache["ts"] < CAPE_CACHE_TTL_SECONDS):
        cached = deepcopy(_cape_cache["payload"])
        cached["cached"] = True
        cached["cache_age_seconds"] = int(now - _cape_cache["ts"])
        return cached

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                CAPE_API_BASE,
                params={
                    "latitude": WU_CENTER_LAT,
                    "longitude": WU_CENTER_LON,
                    "hourly": "cape,convective_inhibition",
                    "forecast_days": 2,
                    "timezone": "Europe/London",
                    "models": "ukmo_seamless",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Open-Meteo CAPE HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Open-Meteo CAPE request error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Open-Meteo CAPE returned invalid JSON") from exc

    hourly = data.get("hourly", {})
    times  = hourly.get("time", [])
    capes  = hourly.get("cape", [])
    cins   = hourly.get("convective_inhibition", [])

    hours = []
    for t, cape, cin in zip(times, capes, cins):
        hours.append({
            "time": t,
            "cape_j_kg": round(_safe_float(cape) or 0.0, 1),
            "cin_j_kg": round(_safe_float(cin) or 0.0, 1),
        })

    from datetime import datetime as _dt
    now_str = _dt.now().strftime("%Y-%m-%dT%H:00")
    current_idx = next((i for i, h in enumerate(hours) if h["time"] == now_str), 0)
    current = hours[current_idx] if hours else {}

    next_24 = hours[current_idx:current_idx + 24]
    next_48 = hours[current_idx:current_idx + 48]

    def cape_risk_level(cape, cin):
        if cape is None: return "unknown"
        if cape < 300: return "low"
        if cape < 1000: return "moderate"
        if cape < 2000:
            return "elevated" if cin > -200 else "moderate-capped"
        return "high" if cin > -100 else "high-capped"

    peak_24 = max((h["cape_j_kg"] for h in next_24), default=0.0)
    peak_48 = max((h["cape_j_kg"] for h in next_48), default=0.0)
    peak_24_hour = next((h for h in next_24 if h["cape_j_kg"] == peak_24), {})

    payload = {
        "status": "ok",
        "source": "Open-Meteo / UKMO Seamless (raw atmospheric indices only)",
        "cached": False,
        "cache_age_seconds": 0,
        "current": current,
        "current_risk_level": cape_risk_level(current.get("cape_j_kg"), current.get("cin_j_kg", 0)),
        "peak_cape_24h_j_kg": peak_24,
        "peak_cape_24h_time": peak_24_hour.get("time"),
        "peak_cape_24h_cin": peak_24_hour.get("cin_j_kg"),
        "peak_cape_48h_j_kg": peak_48,
        "hours": next_48,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _cape_cache["payload"] = deepcopy(payload)
    _cape_cache["ts"] = time.time()
    return payload


async def compute_thunderstorm_risk():
    """Combine CAPE/CIN model data with WH57 sensor live strikes.
    WH57 = ground truth now; CAPE = forward-looking potential.
    Rule-based, no external forecast text consumed."""
    cape_data = await fetch_cape_data()
    current_cape = cape_data.get("current", {})
    cape = current_cape.get("cape_j_kg", 0.0)
    cin  = current_cape.get("cin_j_kg", 0.0)
    risk = cape_data.get("current_risk_level", "unknown")

    wh57_strikes = None
    wh57_distance_km = None
    try:
        station_data = await fetch_current_from_ecowitt()
        d = station_data.get("data", {})
        wh57_strikes = to_float(d.get("lightning", {}).get("count", {}).get("value"))
        dist_mi = to_float(d.get("lightning", {}).get("distance", {}).get("value"))
        wh57_distance_km = round(dist_mi * 1.60934, 1) if dist_mi is not None else None
    except Exception:
        pass

    active_strikes = bool(wh57_strikes and wh57_strikes > 0)
    nearby_lightning = bool(active_strikes and wh57_distance_km and wh57_distance_km <= 40)

    if nearby_lightning:
        composite_risk = "high"
        assessment = (
            f"Active lightning detected by WH57 ({int(wh57_strikes)} strikes today, "
            f"nearest {wh57_distance_km}km). CAPE {cape:.0f} J/kg — "
            f"{'elevated instability supports continued activity' if cape > 500 else 'moderate instability present'}."
        )
    elif active_strikes:
        composite_risk = "elevated" if risk in ("low", "moderate") else risk
        assessment = (
            f"Lightning detected by WH57 ({int(wh57_strikes)} strikes today, "
            f"nearest {wh57_distance_km}km). CAPE {cape:.0f} J/kg, CIN {cin:.0f} J/kg."
        )
    elif risk in ("high", "elevated"):
        composite_risk = risk
        assessment = (
            f"No strikes yet but CAPE {cape:.0f} J/kg with CIN {cin:.0f} J/kg — "
            f"{'uncapped, storms could initiate' if cin > -50 else 'cap weakening, monitor closely'}."
        )
    elif risk in ("high-capped", "moderate-capped"):
        composite_risk = "moderate"
        assessment = (
            f"High CAPE ({cape:.0f} J/kg) but strongly inhibited (CIN {cin:.0f} J/kg). "
            f"Storms suppressed — could fire explosively if cap breaks."
        )
    else:
        composite_risk = risk
        assessment = (
            f"CAPE {cape:.0f} J/kg, CIN {cin:.0f} J/kg. "
            f"{'Low convective potential.' if cape < 300 else 'Moderate instability.'}"
        )

    return {
        "status": "ok",
        "composite_risk_level": composite_risk,
        "assessment": assessment,
        "cape_current_j_kg": cape,
        "cin_current_j_kg": cin,
        "model_risk_level": risk,
        "peak_cape_24h_j_kg": cape_data.get("peak_cape_24h_j_kg"),
        "peak_cape_24h_time": cape_data.get("peak_cape_24h_time"),
        "peak_cape_24h_cin": cape_data.get("peak_cape_24h_cin"),
        "wh57_strikes_today": wh57_strikes,
        "wh57_nearest_km": wh57_distance_km,
        "active_strikes_detected": active_strikes,
        "nearby_lightning": nearby_lightning,
        "cape_hours_48h": cape_data.get("hours", []),
        "method": "WH57 sensor (ground truth) + UKMO CAPE/CIN (forward-looking). No external forecast text.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_cefas_buoys(force=False):
    """Fetch live Cefas WaveNet marine buoy data within CEFAS_RADIUS_MILES of
    the configured centre point.

    Public, unauthenticated GeoJSON endpoint maintained by Cefas (Centre for
    Environment, Fisheries and Aquaculture Science). Data is licensed under
    the Open Government Licence - acknowledgement required, no API key needed.
    """
    now = time.time()
    if not force and _cefas_cache["payload"] and (now - _cefas_cache["ts"] < CEFAS_CACHE_TTL_SECONDS):
        cached = deepcopy(_cefas_cache["payload"])
        cached["cached"] = True
        cached["cache_age_seconds"] = int(now - _cefas_cache["ts"])
        return cached

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{CEFAS_API_BASE}/Map/Current")
            resp.raise_for_status()
            geojson = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Cefas WaveNet HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Cefas WaveNet request error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Cefas WaveNet returned invalid JSON") from exc

    scored = []
    for feature in geojson.get("features", []):
        try:
            lon, lat = feature["geometry"]["coordinates"]
        except (KeyError, ValueError, TypeError):
            continue
        dist_km = _haversine_km(WU_CENTER_LAT, WU_CENTER_LON, lat, lon)
        dist_mi = dist_km / 1.60934
        if dist_mi > CEFAS_RADIUS_MILES:
            continue
        scored.append((dist_mi, lat, lon, feature))
    scored.sort(key=lambda x: x[0])
    scored = scored[:CEFAS_BUOY_LIMIT]

    buoys = []
    for dist_mi, lat, lon, feature in scored:
        props = feature.get("properties", {})
        results = props.get("results", {})

        def result_value(key):
            entry = results.get(key, {})
            values = entry.get("values", [])
            return _safe_float(values[0]) if values else None

        try:
            bearing = _bearing_deg(WU_CENTER_LAT, WU_CENTER_LON, lat, lon)
            direction = _compass_point(bearing)
        except (TypeError, ValueError):
            direction = None

        buoys.append({
            "id": props.get("id"),
            "name": props.get("title"),
            "provider": props.get("provider"),
            "distance_mi": round(dist_mi, 1),
            "direction_from_centre": direction,
            "lat": lat,
            "lon": lon,
            "timestamp": props.get("timestamp"),
            "overdue": bool(props.get("overdue")),
            "wave_height_m": result_value("Hm0"),
            "sea_temp_c": result_value("TEMP"),
            "wave_period_zero_s": result_value("Tz"),
            "wave_period_peak_s": result_value("Tpeak"),
            "wave_spread_deg": result_value("W_SPR"),
            "wave_direction_deg": result_value("W_PDIR"),
        })

    def avg(field):
        vals = [b[field] for b in buoys if isinstance(b.get(field), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else None

    payload = {
        "status": "ok",
        "source": "Cefas WaveNet (Channel Coastal Observatory / Cefas)",
        "license": "Open Government Licence - https://wavenet-api.cefas.co.uk/api/Licence/1/Download",
        "centre": {"lat": WU_CENTER_LAT, "lon": WU_CENTER_LON},
        "radius_miles": CEFAS_RADIUS_MILES,
        "cached": False,
        "cache_age_seconds": 0,
        "buoy_count": len(buoys),
        "buoys": buoys,
        "regional_summary": {
            "wave_height_m_avg": avg("wave_height_m"),
            "wave_height_m_max": max([b["wave_height_m"] for b in buoys if isinstance(b.get("wave_height_m"), (int, float))], default=None),
            "sea_temp_c_avg": avg("sea_temp_c"),
            "sea_temp_c_min": min([b["sea_temp_c"] for b in buoys if isinstance(b.get("sea_temp_c"), (int, float))], default=None),
            "sea_temp_c_max": max([b["sea_temp_c"] for b in buoys if isinstance(b.get("sea_temp_c"), (int, float))], default=None),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _cefas_cache["payload"] = deepcopy(payload)
    _cefas_cache["ts"] = time.time()
    return payload


async def compute_pressure_tendency():
    """Barometric pressure trend over 3h/6h from our own stored snapshots.
    Classic manual-forecasting technique - no external data involved."""
    with db_conn() as conn:
        latest = conn.execute(
            "SELECT captured_at, pressure_inhg FROM weather_snapshots "
            "WHERE pressure_inhg IS NOT NULL ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return None

        def pressure_at(hours_ago):
            row = conn.execute(
                """SELECT pressure_inhg FROM weather_snapshots
                   WHERE captured_at <= datetime('now', ?) AND pressure_inhg IS NOT NULL
                   ORDER BY captured_at DESC LIMIT 1""",
                (f"-{hours_ago} hours",),
            ).fetchone()
            return row["pressure_inhg"] if row else None

        p_now = latest["pressure_inhg"]
        p_3h = pressure_at(3)
        p_6h = pressure_at(6)

    def to_hpa(inhg):
        return inhg * 33.8639 if inhg is not None else None

    hpa_now = to_hpa(p_now)

    def delta_hpa(p_then):
        if p_then is None:
            return None
        return round(hpa_now - to_hpa(p_then), 2)

    delta_3h = delta_hpa(p_3h)
    delta_6h = delta_hpa(p_6h)

    def classify(delta, hours):
        if delta is None:
            return "unknown"
        rate = delta / hours
        if rate <= -2.0:
            return "falling rapidly"
        if rate <= -0.5:
            return "falling"
        if rate >= 2.0:
            return "rising rapidly"
        if rate >= 0.5:
            return "rising"
        return "steady"

    return {
        "pressure_hpa_now": round(hpa_now, 1) if hpa_now is not None else None,
        "delta_3h_hpa": delta_3h,
        "delta_6h_hpa": delta_6h,
        "tendency_3h": classify(delta_3h, 3),
        "tendency_6h": classify(delta_6h, 6),
    }


NOWCAST_ASSUMED_SPEED_MPH = float(os.getenv("NOWCAST_ASSUMED_SPEED_MPH", "25"))


async def compute_nowcast():
    """Rule-based short-term (1-3h) nowcast built entirely in-house from data
    already being collected: own station's current wind direction (to find
    the upwind compass sector), our own barometric pressure tendency, and
    the WU regional network's directional_summary (already computed for the
    dashboard's direction breakdown). No external forecast model is used -
    this is a deliberately self-contained, deterministic prediction layer.
    """
    try:
        current_payload = await fetch_current_from_ecowitt()
        current_data = current_payload.get("data", {})
        wind_dir_raw = current_data.get("wind", {}).get("wind_direction", {}).get("value")
        own_wind_dir = to_float(wind_dir_raw)
    except Exception:
        own_wind_dir = None

    tendency = await compute_pressure_tendency()

    # Wind direction is reported as the direction the wind is blowing FROM,
    # so that compass octant is exactly the upwind sector to watch.
    upwind_octant = _compass_octant(own_wind_dir) if own_wind_dir is not None else None

    upwind_info = None
    try:
        wu_data = await fetch_wu_nearby_stations()
        directional = wu_data.get("directional_summary", {})
        if upwind_octant and upwind_octant in directional:
            sector = directional[upwind_octant]
            upwind_info = {
                "sector": upwind_octant,
                "station_count": sector.get("station_count"),
                "stations_reporting_rain": sector.get("stations_reporting_rain"),
                "nearest_distance_mi": sector.get("nearest_distance_mi"),
                "temp_c_avg": sector.get("temp_c_avg"),
                "wind_speed_kmh_avg": sector.get("wind_speed_kmh_avg"),
            }
    except Exception:
        upwind_info = None

    rain_upwind = bool(upwind_info and (upwind_info.get("stations_reporting_rain") or 0) > 0)
    tendency_3h = tendency.get("tendency_3h") if tendency else "unknown"
    falling = tendency_3h in ("falling", "falling rapidly")
    rapidly_falling = tendency_3h == "falling rapidly"

    eta_minutes = None
    if rain_upwind and upwind_info.get("nearest_distance_mi"):
        eta_minutes = round((upwind_info["nearest_distance_mi"] / NOWCAST_ASSUMED_SPEED_MPH) * 60)

    message_parts = []
    if rain_upwind and rapidly_falling:
        risk_level = "high"
        message_parts.append(f"Rain detected upwind ({upwind_octant}) with rapidly falling pressure")
    elif rain_upwind and falling:
        risk_level = "moderate-high"
        message_parts.append(f"Rain detected upwind ({upwind_octant}) with falling pressure")
    elif rain_upwind:
        risk_level = "moderate"
        message_parts.append(f"Rain detected upwind ({upwind_octant}); pressure currently steady or rising")
    elif rapidly_falling:
        risk_level = "moderate"
        message_parts.append("Pressure falling rapidly - conditions may deteriorate even though no rain detected upwind yet")
    elif falling:
        risk_level = "low-moderate"
        message_parts.append("Pressure gently falling - worth keeping an eye on conditions")
    else:
        risk_level = "low"
        message_parts.append("No rain detected upwind and pressure is steady or rising")

    if eta_minutes is not None:
        if eta_minutes < 60:
            message_parts.append(f"possible arrival in roughly {eta_minutes} minutes (assumes ~{int(NOWCAST_ASSUMED_SPEED_MPH)}mph system speed - a rough estimate, not a precise forecast)")
        else:
            message_parts.append(f"possible arrival in roughly {round(eta_minutes / 60, 1)} hours (assumes ~{int(NOWCAST_ASSUMED_SPEED_MPH)}mph system speed - a rough estimate, not a precise forecast)")

    return {
        "status": "ok",
        "method": "Self-computed, rule-based: own pressure tendency + upwind regional station network. No external forecast API used.",
        "own_wind_direction_deg": own_wind_dir,
        "upwind_sector": upwind_octant,
        "pressure_tendency": tendency,
        "upwind_conditions": upwind_info,
        "risk_level": risk_level,
        "eta_minutes": eta_minutes,
        "message": ". ".join(message_parts) + ".",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                outdoor_temp_f REAL,
                humidity_pct REAL,
                pressure_inhg REAL,
                wind_mph REAL,
                rain_rate_inhr REAL,
                uv_index REAL,
                comfort_score REAL,
                soil_moisture_pct REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_weather_snapshots_captured_at ON weather_snapshots(captured_at)")
        try:
            conn.execute("ALTER TABLE weather_snapshots ADD COLUMN soil_moisture_pct REAL")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def normalized_mac(mac):
    m = (mac or "").strip().lower()
    if ":" in m:
        return m
    if len(m) == 12:
        return ":".join(m[i:i + 2] for i in range(0, 12, 2))
    return m


def trend_label(delta, positive_is_better):
    if delta is None:
        return "unknown"
    if abs(delta) < 0.01:
        return "steady"
    better = delta > 0 if positive_is_better else delta < 0
    return "better" if better else "worse"


def local_fallback_forecast(stats_24, trend_24):
    latest = (stats_24 or {}).get("latest", {}) if isinstance(stats_24, dict) else {}
    summary = (stats_24 or {}).get("summary", {}) if isinstance(stats_24, dict) else {}
    overall = (trend_24 or {}).get("overall", "steady") if isinstance(trend_24, dict) else "steady"
    temp_f = latest.get("outdoor_temp_f")
    hum = latest.get("humidity_pct")
    wind_mph = latest.get("wind_mph")
    rain_rate = latest.get("rain_rate_inhr")
    uv = latest.get("uv_index")
    temp_avg = (summary.get("temperature_f") or {}).get("avg")
    hum_avg = (summary.get("humidity_pct") or {}).get("avg")
    wind_avg = (summary.get("wind_mph") or {}).get("avg")
    wind_max = (summary.get("wind_mph") or {}).get("max")
    return {
        "summary_24h": (
            f"Last 24h (local DB): average temperature {fmt_temp_dual(temp_avg)}, average humidity {hum_avg}%, "
            f"average wind {fmt_wind_dual(wind_avg)} (max {fmt_wind_dual(wind_max)})."
        ),
        "forecast_24h": (
            f"Local trend outlook: {overall}. Current: {fmt_temp_dual(temp_f)}, humidity {hum}%, "
            f"wind {fmt_wind_dual(wind_mph)}, rain rate {fmt_rain_rate_dual(rain_rate)}, UV {uv}. "
            f"Conditions likely to remain near recent trend."
        ),
        "comfort_outlook": "Local fallback forecast while AI provider is temporarily unavailable or rate-limited.",
        "risks": ["AI provider temporarily unavailable (Gemini rate-limit or network issue)."],
        "confidence": "low",
    }


async def fetch_current_from_ecowitt():
    if not all([APPLICATION_KEY, API_KEY, MAC_ADDRESS]):
        raise HTTPException(status_code=500, detail="Missing APPLICATION_KEY, API_KEY or MAC_ADDRESS")
    params = {
        "application_key": APPLICATION_KEY,
        "api_key": API_KEY,
        "mac": normalized_mac(MAC_ADDRESS),
        "call_back": "all",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(ECOWITT_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Ecowitt HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Ecowitt request error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Ecowitt returned invalid JSON") from exc
    if payload.get("code") != 0:
        raise HTTPException(status_code=502, detail=f"Ecowitt API error: {payload.get('msg', 'Unknown')}")
    return payload


async def call_gemini_forecast(context_payload, satellite_ai_images=None):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY")
    satellite_ai_images = satellite_ai_images or []
    prompt = (
        "You are a weather assistant. Use ONLY the provided weather data.\n"
        "Task:\n"
        "1) Summarize what weather has done over the last 24 hours.\n"
        "2) Give a practical next-24-hours forecast based on trend extrapolation and any attached METEOR satellite images.\n"
        "3) Mention confidence level (low/medium/high) and why.\n"
        "4) Return strict JSON with keys: summary_24h, forecast_24h, comfort_outlook, risks, confidence.\n"
        "5) Use metric-first units with imperial in brackets.\n"
        "If satellite images are attached, compare them chronologically. Use visible cloud cover, clearing, frontal bands, "
        "and cloud movement to improve the forecast description, but do not invent precise model data.\n"
        "If regional_stations data is present, cross-reference it with the satellite imagery: use nearby station "
        "temperature, humidity, wind, pressure and rain readings to corroborate or refine what the satellite shows "
        "(e.g. confirm actual rainfall under cloud cover, detect wind shifts ahead of a front, or pressure drops "
        "indicating an approaching system). Each station includes direction_from_centre (a compass bearing such as "
        "NW, SE) and distance_mi from Tingley, spread across up to a 100-mile radius. Use this spatial layout for "
        "synoptic-scale reasoning: compare conditions between compass sectors to infer which direction a front, "
        "shower band, or temperature change is approaching from, and roughly how far away it is. Mention notable "
        "regional variation or an approaching change in conditions if relevant.\n"
        "regional_stations.local_summary is the true near-field average (within local_radius_miles, ~20mi) - use "
        "this for describing current local conditions around Tingley, not the wider mix. "
        "regional_stations.directional_summary breaks the remaining stations (beyond local_radius_miles, out to "
        "the full radius) into 8 compass sectors (N/NE/E/SE/S/SW/W/NW), each with its own averages and station "
        "count. Compare local_summary against each sector to identify which direction shows the most different "
        "conditions (cooler, wetter, windier, lower pressure) - that sector is the most likely source of "
        "incoming change in the next several hours. Mention the sector by compass direction when relevant.\n"
        "If coastal_marine data is present, use it for additional coastal context: sea temperature relative to "
        "land temperature can indicate sea-breeze effects on the East Yorkshire coast, and wave height/period can "
        "hint at offshore wind strength feeding into the region. Only mention this if genuinely relevant.\n"
        "If local_nowcast data is present, treat it as a second independent short-term (1-3h) signal computed from "
        "our own pressure tendency and upwind regional stations. State briefly whether it agrees or disagrees with "
        "your own reading of the satellite and regional data, but do not just repeat its message verbatim.\n"
        "If thunderstorm_risk data is present, incorporate it: CAPE (J/kg) measures atmospheric instability "
        "(>1000 = significant, >2000 = severe), CIN measures convective inhibition (near 0 = storms can fire "
        "freely, strongly negative = capped). Cross-reference CAPE with the WH57 sensor actual strike count. "
        "If nearby_lightning is true, storms are already active. High CAPE with CIN near zero but no strikes yet "
        "= imminent risk. High CAPE with strong negative CIN = potential but suppressed for now.\n"
        "Keep text concise and plain English for a dashboard.\n\n"
        f"DATA:\n{json.dumps(context_payload, ensure_ascii=True)}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    parts = [{"text": prompt}]
    for item in satellite_ai_images:
        parts.append({"inline_data": {"mime_type": item["mime_type"], "data": item["base64"]}})
    body = {"contents": [{"parts": parts}]}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Gemini returned invalid JSON") from exc
    text = (payload.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip())
    if not text:
        raise HTTPException(status_code=502, detail="Gemini returned empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").replace("json", "", 1).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        return {"summary_24h": text, "forecast_24h": "Forecast parsing fallback.", "comfort_outlook": "unknown", "risks": [], "confidence": "low"}


async def call_openai_compatible_forecast(context_payload, base_url, api_key, model_name, provider_name):
    if not api_key:
        raise HTTPException(status_code=500, detail=f"Missing {provider_name} API key")
    prompt = (
        "You are a weather assistant. Use ONLY the provided weather data.\n"
        "Task:\n1) Summarize last 24h weather.\n2) Forecast next 24h.\n"
        "3) Confidence level (low/medium/high) and why.\n"
        "4) Return strict JSON: summary_24h, forecast_24h, comfort_outlook, risks, confidence.\n"
        "5) Metric-first units with imperial in brackets.\n\n"
        f"DATA:\n{json.dumps(context_payload, ensure_ascii=True)}"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider_name == "openrouter":
        headers["HTTP-Referer"] = "https://2e0lxy.uk/weather-dashboard"
        headers["X-Title"] = "Ecowitt Weather Dashboard"
    body = {"model": model_name, "messages": [{"role": "system", "content": "You generate concise structured weather forecast JSON."}, {"role": "user", "content": prompt}], "temperature": 0.4}
    if provider_name != "openrouter":
        body["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"{provider_name} HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"{provider_name} request error: {exc}") from exc
    content = payload["choices"][0]["message"]["content"].strip()
    if not content:
        raise HTTPException(status_code=502, detail=f"{provider_name} returned empty response")
    try:
        return json.loads(content)
    except ValueError:
        return {"summary_24h": content, "forecast_24h": "Fallback.", "comfort_outlook": "unknown", "risks": [], "confidence": "low"}


async def call_backup_llm_forecast(context_payload):
    if BACKUP_LLM_PROVIDER == "openai":
        return await call_openai_compatible_forecast(context_payload, "https://api.openai.com/v1", OPENAI_API_KEY, OPENAI_MODEL, "openai"), OPENAI_MODEL
    return await call_openai_compatible_forecast(context_payload, "https://openrouter.ai/api/v1", OPENROUTER_API_KEY, OPENROUTER_MODEL, "openrouter"), OPENROUTER_MODEL


async def call_openrouter_chain_forecast(context_payload):
    models = [m.strip() for m in OPENROUTER_MODELS.split(",") if m.strip()] or [OPENROUTER_MODEL]
    last_error = None
    for model_name in models:
        try:
            ai = await call_openai_compatible_forecast(context_payload, "https://openrouter.ai/api/v1", OPENROUTER_API_KEY, model_name, "openrouter")
            return ai, model_name
        except HTTPException as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise HTTPException(status_code=502, detail="openrouter chain failed")


def extract_snapshot(payload):
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    def get(*path):
        cur = data
        for key in path:
            if not isinstance(cur, dict): return None
            cur = cur.get(key)
        return cur
    temp_f = to_float(get("outdoor", "temperature", "value"))
    humidity = to_float(get("outdoor", "humidity", "value"))
    pressure = to_float(get("pressure", "relative", "value"))
    wind = to_float(get("wind", "wind_speed", "value"))
    rain_rate = to_float(get("rainfall", "rain_rate", "value"))
    uv = to_float(get("solar_and_uvi", "uvi", "value"))
    soil_moisture = to_float(get("soil_ch1", "soilmoisture", "value"))
    return {
        "outdoor_temp_f": temp_f, "humidity_pct": humidity, "pressure_inhg": pressure,
        "wind_mph": wind, "rain_rate_inhr": rain_rate, "uv_index": uv,
        "comfort_score": weather_comfort_score(temp_f, humidity, wind, rain_rate, uv),
        "soil_moisture_pct": soil_moisture,
    }


def save_snapshot(snapshot):
    captured_at = datetime.now(timezone.utc).isoformat()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO weather_snapshots (
                captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                wind_mph, rain_rate_inhr, uv_index, comfort_score, soil_moisture_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (captured_at, snapshot.get("outdoor_temp_f"), snapshot.get("humidity_pct"),
             snapshot.get("pressure_inhg"), snapshot.get("wind_mph"), snapshot.get("rain_rate_inhr"),
             snapshot.get("uv_index"), snapshot.get("comfort_score"), snapshot.get("soil_moisture_pct")),
        )
        conn.commit()
    return captured_at


def satellite_absolute_url(path_or_url):
    return urljoin(f"{SATELLITE_BASE_URL.rstrip('/')}/", unescape(path_or_url).lstrip("/"))

def satellite_proxy_url(image_url):
    return f"/api/satellite/image?url={quote(image_url, safe='')}"

def parse_capture_cards(html):
    cards = []
    for match in re.finditer(r'<div class="card bg-light.*?</div>\s*</div>', html, flags=re.DOTALL):
        block = match.group(0)
        pass_match = re.search(r'href="(/captures/listImages\?pass_id=(\d+))"', block)
        if not pass_match: continue
        title_match = re.search(r'<h5 class="card-title">\s*(.*?)\s*</h5>', block, flags=re.DOTALL)
        pass_start_match = re.search(r'<strong>Pass Start:\s*</strong>\s*([^<]+)<', block, flags=re.DOTALL)
        direction_match = re.search(r'<strong>Direction:\s*</strong>\s*([^<]+)<', block, flags=re.DOTALL)
        elevation_match = re.search(r'<strong>Elevation:\s*</strong>\s*([^<]+)<', block, flags=re.DOTALL)
        cards.append({
            "pass_id": pass_match.group(2), "detail_path": pass_match.group(1),
            "satellite": unescape(title_match.group(1)).strip() if title_match else "Unknown",
            "pass_start": " ".join(unescape(pass_start_match.group(1)).split()) if pass_start_match else "--",
            "direction": " ".join(unescape(direction_match.group(1)).split()) if direction_match else "--",
            "elevation": " ".join(unescape(elevation_match.group(1)).split()) if elevation_match else "--",
        })
    return cards

def parse_capture_images(html):
    images = []
    for href in re.findall(r'href="(/images/[^"]+\.(?:jpg|jpeg|png))"', html, flags=re.IGNORECASE):
        url = satellite_absolute_url(href)
        filename = url.rsplit("/", 1)[-1]
        name = filename.rsplit(".", 1)[0]
        parts = name.split("-")
        enhancement = "-".join(parts[5:]) if len(parts) >= 6 else name
        is_polar = "polar" in enhancement.lower()
        images.append({
            "url": url,
            "proxy_url": satellite_proxy_url(url),
            "filename": filename,
            "enhancement": enhancement,
            "is_polar": is_polar,
        })
    return images

def choose_satellite_image(images):
    if not images: return None
    weather = [img for img in images if not img.get("is_polar")]
    if not weather: return None
    for pref in ["equidistant_221_composite","equidistant_321_composite","composite","equidistant_221","equidistant_321"]:
        for img in weather:
            if pref in img["filename"]: return img
    return weather[0]

def choose_satellite_image_by_enhancement(images, enhancement):
    if not images: return None
    weather = [img for img in images if not img.get("is_polar")]
    wanted = (enhancement or "").strip()
    if wanted:
        for img in weather:
            if img.get("enhancement") == wanted or wanted in img.get("filename", ""): return img
    return choose_satellite_image(weather)


async def fetch_latest_satellite_payload(force=False):
    now = time.time()
    if not force and _satellite_cache["payload"] and (now - _satellite_cache["ts"] < SATELLITE_CACHE_TTL_SECONDS):
        cached = deepcopy(_satellite_cache["payload"])
        cached["cached"] = True
        cached["cache_age_seconds"] = int(now - _satellite_cache["ts"])
        return cached
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            captures_resp = await client.get(satellite_absolute_url("/captures?page_no=1"))
            captures_resp.raise_for_status()
            capture_cards = parse_capture_cards(captures_resp.text)
            if not capture_cards: raise HTTPException(status_code=502, detail="No satellite captures found")
            latest = capture_cards[0]
            detail_resp = await client.get(satellite_absolute_url(latest["detail_path"]))
            detail_resp.raise_for_status()
            images = parse_capture_images(detail_resp.text)
    except HTTPException: raise
    except httpx.HTTPStatusError as exc: raise HTTPException(status_code=502, detail=f"Satellite HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc: raise HTTPException(status_code=502, detail=f"Satellite request error: {exc}") from exc
    weather_imgs = [img for img in images if not img.get("is_polar")]
    polar_imgs   = [img for img in images if img.get("is_polar")]
    active_capture = latest

    # If latest capture has no weather imagery (e.g. low-elevation pass that
    # only produced polar charts), scan up to 5 earlier captures for imagery.
    if not weather_imgs:
        for fallback_capture in capture_cards[1:6]:
            try:
                async with httpx.AsyncClient(timeout=10.0) as fc:
                    fb_resp = await fc.get(satellite_absolute_url(fallback_capture["detail_path"]))
                    fb_resp.raise_for_status()
                    fb_imgs = parse_capture_images(fb_resp.text)
                fb_weather = [i for i in fb_imgs if not i.get("is_polar")]
                if fb_weather:
                    weather_imgs     = fb_weather
                    polar_imgs       = [i for i in fb_imgs if i.get("is_polar")]
                    active_capture   = fallback_capture
                    break
            except Exception:
                continue

    chosen = choose_satellite_image(weather_imgs)
    if not chosen: raise HTTPException(status_code=502, detail="No satellite images found")
    payload = {"status": "ok", "source": SATELLITE_BASE_URL, "cached": False, "cache_age_seconds": 0,
               "capture": active_capture, "image": chosen, "images": weather_imgs,
               "polar_images": polar_imgs,
               "updated_at": datetime.now(timezone.utc).isoformat()}
    _satellite_cache["payload"] = deepcopy(payload)
    _satellite_cache["ts"] = time.time()
    return payload


async def fetch_satellite_ai_images():
    if not SATELLITE_AI_IMAGES_ENABLED or SATELLITE_AI_IMAGE_COUNT <= 0: return []
    ai_images = []
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        captures_resp = await client.get(satellite_absolute_url("/captures?page_no=1"))
        captures_resp.raise_for_status()
        capture_cards = parse_capture_cards(captures_resp.text)
        for capture in capture_cards:
            if len(ai_images) >= SATELLITE_AI_IMAGE_COUNT: break
            detail_resp = await client.get(satellite_absolute_url(capture["detail_path"]))
            detail_resp.raise_for_status()
            images = parse_capture_images(detail_resp.text)
            chosen = choose_satellite_image_by_enhancement(images, SATELLITE_AI_IMAGE_ENHANCEMENT)
            if not chosen: continue
            image_resp = await client.get(chosen["url"])
            image_resp.raise_for_status()
            content = image_resp.content
            if len(content) > SATELLITE_AI_MAX_IMAGE_BYTES: continue
            mime_type = image_resp.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip()
            ai_images.append({"capture": capture, "image": chosen, "mime_type": mime_type, "bytes": content,
                               "size_bytes": len(content), "base64": base64.b64encode(content).decode("ascii")})
    return list(reversed(ai_images))


@app.on_event("startup")
async def on_startup():
    init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/satellite/latest")
async def api_satellite_latest(force: bool = False):
    return await fetch_latest_satellite_payload(force=force)


@app.get("/api/satellite/image")
async def api_satellite_image(url: str = Query(...)):
    image_url = unquote(url)
    if not image_url.startswith(f"{SATELLITE_BASE_URL.rstrip('/')}/images/"):
        raise HTTPException(status_code=400, detail="Invalid satellite image URL")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc: raise HTTPException(status_code=502, detail=f"Satellite image HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc: raise HTTPException(status_code=502, detail=f"Satellite image request error: {exc}") from exc
    return Response(content=resp.content, media_type=resp.headers.get("content-type","image/jpeg"), headers={"Cache-Control":"public,max-age=300"})


@app.get("/api/wu/nearby")
async def api_wu_nearby(force: bool = False):
    return await fetch_wu_nearby_stations(force=force)


@app.get("/api/cefas/buoys")
async def api_cefas_buoys(force: bool = False):
    return await fetch_cefas_buoys(force=force)


@app.get("/api/thunderstorm")
async def api_thunderstorm():
    return await compute_thunderstorm_risk()


@app.get("/api/nowcast")
async def api_nowcast():
    return await compute_nowcast()


@app.get("/api/current")
async def api_current(save: bool = False):
    payload = await fetch_current_from_ecowitt()
    if save:
        snapshot = extract_snapshot(payload)
        captured_at = save_snapshot(snapshot)
        payload["_snapshot"] = {"captured_at": captured_at}
    return payload


@app.post("/api/snapshot")
async def api_snapshot():
    payload = await fetch_current_from_ecowitt()
    snapshot = extract_snapshot(payload)
    captured_at = save_snapshot(snapshot)
    return {"status": "ok", "captured_at": captured_at, "snapshot": snapshot}


@app.get("/api/trend")
async def api_trend(hours: int = 6):
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="hours must be between 1 and 168")
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                      wind_mph, rain_rate_inhr, uv_index, comfort_score, soil_moisture_pct
               FROM weather_snapshots WHERE captured_at >= datetime('now', ?) ORDER BY captured_at ASC""",
            (f"-{hours} hours",),
        ).fetchall()
    if len(rows) < 2:
        return {"status": "insufficient_data", "message": "Need at least 2 snapshots"}
    first, last = rows[0], rows[-1]
    def delta(field):
        if first[field] is None or last[field] is None: return None
        return round(last[field] - first[field], 3)
    comfort_delta = delta("comfort_score")
    overall = "steady"
    if comfort_delta is not None:
        if comfort_delta > 0.5: overall = "better"
        elif comfort_delta < -0.5: overall = "worse"
    return {
        "status": "ok", "window_hours": hours, "points": len(rows), "overall": overall,
        "comparison": {
            "comfort_score": {"delta": comfort_delta, "trend": trend_label(comfort_delta, True)},
            "temperature_f": {"delta": delta("outdoor_temp_f"), "trend": "info"},
            "humidity_pct": {"delta": delta("humidity_pct"), "trend": "info"},
            "pressure_inhg": {"delta": delta("pressure_inhg"), "trend": "info"},
            "wind_mph": {"delta": delta("wind_mph"), "trend": trend_label(delta("wind_mph"), False)},
            "rain_rate_inhr": {"delta": delta("rain_rate_inhr"), "trend": trend_label(delta("rain_rate_inhr"), False)},
            "uv_index": {"delta": delta("uv_index"), "trend": "info"},
            "soil_moisture_pct": {"delta": delta("soil_moisture_pct"), "trend": "info"},
        },
        "latest": dict(last),
    }


@app.get("/api/snapshots")
async def api_snapshots(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be 1..1000")
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT id, captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                      wind_mph, rain_rate_inhr, uv_index, comfort_score
               FROM weather_snapshots ORDER BY captured_at DESC LIMIT ?""", (limit,)
        ).fetchall()
    return {"status": "ok", "items": [dict(r) for r in rows]}


@app.get("/api/stats")
async def api_stats(hours: int = 24):
    if hours < 1 or hours > 720:
        raise HTTPException(status_code=400, detail="hours must be between 1 and 720")
    with db_conn() as conn:
        agg = conn.execute(
            """SELECT COUNT(*) AS points, MIN(outdoor_temp_f) AS temp_min_f, MAX(outdoor_temp_f) AS temp_max_f,
                      AVG(outdoor_temp_f) AS temp_avg_f, MIN(humidity_pct) AS humidity_min,
                      MAX(humidity_pct) AS humidity_max, AVG(humidity_pct) AS humidity_avg,
                      AVG(pressure_inhg) AS pressure_avg_inhg, MAX(wind_mph) AS wind_max_mph,
                      AVG(wind_mph) AS wind_avg_mph, SUM(COALESCE(rain_rate_inhr,0)) AS rain_rate_sum,
                      AVG(comfort_score) AS comfort_avg, MIN(soil_moisture_pct) AS soil_min,
                      MAX(soil_moisture_pct) AS soil_max, AVG(soil_moisture_pct) AS soil_avg
               FROM weather_snapshots WHERE captured_at >= datetime('now', ?)""", (f"-{hours} hours",)
        ).fetchone()
        latest = conn.execute(
            """SELECT captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                      wind_mph, rain_rate_inhr, uv_index, comfort_score, soil_moisture_pct
               FROM weather_snapshots ORDER BY captured_at DESC LIMIT 1"""
        ).fetchone()
    if not latest:
        return {"status": "insufficient_data", "message": "No snapshots yet"}
    latest_dt = datetime.fromisoformat(latest["captured_at"])
    age_seconds = int((datetime.now(timezone.utc) - latest_dt).total_seconds())
    def ron(value, digits=2):
        if value is None: return None
        return round(float(value), digits)
    return {
        "status": "ok", "window_hours": hours, "points": int(agg["points"] or 0),
        "latest": dict(latest), "latest_age_seconds": max(0, age_seconds),
        "summary": {
            "temperature_f": {"min": ron(agg["temp_min_f"],2), "max": ron(agg["temp_max_f"],2), "avg": ron(agg["temp_avg_f"],2)},
            "humidity_pct": {"min": ron(agg["humidity_min"],1), "max": ron(agg["humidity_max"],1), "avg": ron(agg["humidity_avg"],1)},
            "pressure_inhg": {"avg": ron(agg["pressure_avg_inhg"],3)},
            "wind_mph": {"max": ron(agg["wind_max_mph"],2), "avg": ron(agg["wind_avg_mph"],2)},
            "rain_rate_sum_inhr": ron(agg["rain_rate_sum"],3),
            "comfort_score_avg": ron(agg["comfort_avg"],2),
            "soil_moisture_pct": {"min": ron(agg["soil_min"],1), "max": ron(agg["soil_max"],1), "avg": ron(agg["soil_avg"],1)},
        },
    }


@app.get("/api/ai-forecast")
async def api_ai_forecast():
    global _ai_last_failure_ts
    now = time.time()
    if _ai_cache["payload"] and (now - _ai_cache["ts"] < AI_CACHE_TTL_SECONDS):
        cached = deepcopy(_ai_cache["payload"])
        cached["cached"] = True
        cached["cache_age_seconds"] = int(now - _ai_cache["ts"])
        return cached

    current = await fetch_current_from_ecowitt()
    stats_24 = await api_stats(hours=24)
    trend_24 = await api_trend(hours=24)

    with db_conn() as conn:
        points = conn.execute(
            """SELECT captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                      wind_mph, rain_rate_inhr, uv_index, comfort_score, soil_moisture_pct
               FROM weather_snapshots WHERE captured_at >= datetime('now', '-24 hours')
               ORDER BY captured_at ASC LIMIT 288"""
        ).fetchall()

    compact_points = [{
        "t": r["captured_at"], "temp_f": r["outdoor_temp_f"], "hum_pct": r["humidity_pct"],
        "pressure_inhg": r["pressure_inhg"], "wind_mph": r["wind_mph"],
        "rain_rate_inhr": r["rain_rate_inhr"], "uv": r["uv_index"],
        "comfort": r["comfort_score"], "soil_pct": r["soil_moisture_pct"],
    } for r in points]

    context_payload = {
        "current": current.get("data", {}), "stats_24h": stats_24, "trend_24h": trend_24,
        "samples_24h": compact_points, "timezone_hint": "Europe/London",
    }

    try:
        wu_data = await fetch_wu_nearby_stations()
        context_payload["regional_stations"] = {
            "source": wu_data.get("source"),
            "centre": "Tingley, Leeds, UK",
            "radius_miles": wu_data.get("radius_miles"),
            "local_radius_miles": wu_data.get("local_radius_miles"),
            "min_spacing_miles": wu_data.get("min_spacing_miles"),
            "station_count": wu_data.get("station_count"),
            "local_summary": wu_data.get("local_summary"),
            "directional_summary": wu_data.get("directional_summary"),
            "stations": [
                {
                    "name": s.get("name"),
                    "distance_mi": s.get("distance_mi"),
                    "direction_from_centre": s.get("direction_from_centre"),
                    "temp_c": s.get("temp_c"),
                    "humidity_pct": s.get("humidity_pct"),
                    "wind_speed_kmh": s.get("wind_speed_kmh"),
                    "wind_gust_kmh": s.get("wind_gust_kmh"),
                    "wind_dir_deg": s.get("wind_dir_deg"),
                    "precip_rate_mmhr": s.get("precip_rate_mmhr"),
                    "precip_total_mm": s.get("precip_total_mm"),
                    "pressure_hpa": s.get("pressure_hpa"),
                }
                for s in wu_data.get("stations", [])
            ],
        }
    except Exception as exc:
        context_payload["regional_stations"] = {"error": str(exc)}

    try:
        cefas_data = await fetch_cefas_buoys()
        context_payload["coastal_marine"] = {
            "source": cefas_data.get("source"),
            "radius_miles": cefas_data.get("radius_miles"),
            "buoy_count": cefas_data.get("buoy_count"),
            "regional_summary": cefas_data.get("regional_summary"),
            "buoys": [
                {
                    "name": b.get("name"),
                    "distance_mi": b.get("distance_mi"),
                    "direction_from_centre": b.get("direction_from_centre"),
                    "sea_temp_c": b.get("sea_temp_c"),
                    "wave_height_m": b.get("wave_height_m"),
                    "wave_period_peak_s": b.get("wave_period_peak_s"),
                    "wave_direction_deg": b.get("wave_direction_deg"),
                    "overdue": b.get("overdue"),
                }
                for b in cefas_data.get("buoys", [])
            ],
        }
    except Exception as exc:
        context_payload["coastal_marine"] = {"error": str(exc)}

    try:
        context_payload["local_nowcast"] = await compute_nowcast()
    except Exception as exc:
        context_payload["local_nowcast"] = {"error": str(exc)}

    try:
        ts_risk = await compute_thunderstorm_risk()
        context_payload["thunderstorm_risk"] = {
            "composite_risk_level": ts_risk.get("composite_risk_level"),
            "assessment": ts_risk.get("assessment"),
            "cape_current_j_kg": ts_risk.get("cape_current_j_kg"),
            "cin_current_j_kg": ts_risk.get("cin_current_j_kg"),
            "peak_cape_24h_j_kg": ts_risk.get("peak_cape_24h_j_kg"),
            "peak_cape_24h_time": ts_risk.get("peak_cape_24h_time"),
            "peak_cape_24h_cin": ts_risk.get("peak_cape_24h_cin"),
            "wh57_strikes_today": ts_risk.get("wh57_strikes_today"),
            "wh57_nearest_km": ts_risk.get("wh57_nearest_km"),
            "active_strikes_detected": ts_risk.get("active_strikes_detected"),
            "nearby_lightning": ts_risk.get("nearby_lightning"),
            "method": ts_risk.get("method"),
        }
    except Exception as exc:
        context_payload["thunderstorm_risk"] = {"error": str(exc)}

    in_retry_cooldown = _ai_last_failure_ts > 0 and (now - _ai_last_failure_ts) < AI_RETRY_COOLDOWN_SECONDS
    if in_retry_cooldown:
        payload = {"status":"ok","model":"local-fallback","generated_at":datetime.now(timezone.utc).isoformat(),
                   "ai_forecast":local_fallback_forecast(stats_24,trend_24),"cached":False,"cache_age_seconds":0,
                   "warning":f"AI retry cooldown active ({int(AI_RETRY_COOLDOWN_SECONDS-(now-_ai_last_failure_ts))}s remaining)."}
        _ai_cache["payload"] = deepcopy(payload); _ai_cache["ts"] = time.time()
        return payload

    satellite_ai_images = []
    try:
        satellite_ai_images = await fetch_satellite_ai_images()
        if satellite_ai_images:
            context_payload["satellite_images"] = [
                {"satellite": i["capture"].get("satellite"), "pass_start": i["capture"].get("pass_start"),
                 "direction": i["capture"].get("direction"), "elevation": i["capture"].get("elevation"),
                 "enhancement": i["image"].get("enhancement"), "filename": i["image"].get("filename"),
                 "size_bytes": i["size_bytes"], "attached_to_gemini": True}
                for i in satellite_ai_images
            ]
    except Exception as exc:
        context_payload["satellite_images"] = {"attached_to_gemini": False, "error": str(exc)}

    try:
        ai = await call_gemini_forecast(context_payload, satellite_ai_images=satellite_ai_images)
        _ai_last_failure_ts = 0.0
        payload = {"status":"ok","model":GEMINI_MODEL,"generated_at":datetime.now(timezone.utc).isoformat(),
                   "ai_forecast":ai,"cached":False,"cache_age_seconds":0,"satellite_images_used":len(satellite_ai_images)}
        _ai_cache["payload"] = deepcopy(payload); _ai_cache["ts"] = time.time()
        return payload
    except HTTPException as exc:
        _ai_last_failure_ts = time.time()
        try:
            if BACKUP_LLM_PROVIDER == "openrouter":
                backup_ai, backup_model = await call_openrouter_chain_forecast(context_payload)
            else:
                backup_ai, backup_model = await call_backup_llm_forecast(context_payload)
            payload = {"status":"ok","model":backup_model,"generated_at":datetime.now(timezone.utc).isoformat(),
                       "ai_forecast":backup_ai,"cached":False,"cache_age_seconds":0,
                       "warning":f"Primary unavailable: {exc.detail}. Served by backup."}
            _ai_cache["payload"] = deepcopy(payload); _ai_cache["ts"] = time.time()
            return payload
        except HTTPException as backup_exc:
            if _ai_cache["payload"]:
                stale = deepcopy(_ai_cache["payload"]); stale.update({"cached":True,"stale":True,"cache_age_seconds":int(now-_ai_cache["ts"]),"warning":f"Primary ({exc.detail}); backup ({backup_exc.detail}) both failed"})
                return stale
        payload = {"status":"ok","model":"local-fallback","generated_at":datetime.now(timezone.utc).isoformat(),
                   "ai_forecast":local_fallback_forecast(stats_24,trend_24),"cached":False,"cache_age_seconds":0,
                   "warning":f"Primary and backup both failed."}
        _ai_cache["payload"] = deepcopy(payload); _ai_cache["ts"] = time.time()
        return payload
    except Exception as exc:
        _ai_last_failure_ts = time.time()
        if _ai_cache["payload"]:
            stale = deepcopy(_ai_cache["payload"]); stale.update({"cached":True,"stale":True,"cache_age_seconds":int(now-_ai_cache["ts"]),"warning":f"Unexpected AI error: {exc}"})
            return stale
        payload = {"status":"ok","model":"local-fallback","generated_at":datetime.now(timezone.utc).isoformat(),
                   "ai_forecast":local_fallback_forecast(stats_24,trend_24),"cached":False,"cache_age_seconds":0,"warning":f"Unexpected AI error: {exc}"}
        _ai_cache["payload"] = deepcopy(payload); _ai_cache["ts"] = time.time()
        return payload


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "weather.html"))

@app.get("/weather-dashboard")
async def dashboard_alias():
    return FileResponse(os.path.join(STATIC_DIR, "weather.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
