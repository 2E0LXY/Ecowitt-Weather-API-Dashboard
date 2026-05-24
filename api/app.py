import os
import sqlite3
import json
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))


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
                comfort_score REAL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_weather_snapshots_captured_at ON weather_snapshots(captured_at)"
        )
        conn.commit()


def normalized_mac(mac):
    m = (mac or "").strip().lower()
    if ":" in m:
        return m
    if len(m) == 12:
        return ":".join(m[i:i+2] for i in range(0, 12, 2))
    return m


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


async def call_gemini_forecast(context_payload):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY")

    prompt = (
        "You are a weather assistant. Use ONLY the provided weather data.\n"
        "Task:\n"
        "1) Summarize what weather has done over the last 24 hours.\n"
        "2) Give a practical next-24-hours forecast based on trend extrapolation.\n"
        "3) Mention confidence level (low/medium/high) and why.\n"
        "4) Return strict JSON with keys: summary_24h, forecast_24h, comfort_outlook, risks, confidence.\n"
        "5) Use metric-first units with imperial in brackets, e.g. 26.0°C (78.8°F), 12.3 km/h (7.6 mph), 1014 hPa (29.94 inHg), 3.2 mm (0.13 in).\n"
        "Keep text concise and plain English for a dashboard.\n\n"
        f"DATA:\n{json.dumps(context_payload, ensure_ascii=True)}"
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request error: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Gemini returned invalid JSON") from exc

    text = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    if not text:
        raise HTTPException(status_code=502, detail="Gemini returned empty response")

    # Accept either raw JSON or fenced JSON.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()

    try:
        return json.loads(cleaned)
    except ValueError:
        # Fallback: return plain text in expected shape.
        return {
            "summary_24h": text,
            "forecast_24h": "Forecast parsing fallback. Review model output format.",
            "comfort_outlook": "unknown",
            "risks": [],
            "confidence": "low",
        }


def extract_snapshot(payload):
    data = payload.get("data", {}) if isinstance(payload, dict) else {}

    def get(*path):
        cur = data
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    temp_f = to_float(get("outdoor", "temperature", "value"))
    humidity = to_float(get("outdoor", "humidity", "value"))
    pressure = to_float(get("pressure", "relative", "value"))
    wind = to_float(get("wind", "wind_speed", "value"))
    rain_rate = to_float(get("rainfall", "rain_rate", "value"))
    uv = to_float(get("solar_and_uvi", "uvi", "value"))

    return {
        "outdoor_temp_f": temp_f,
        "humidity_pct": humidity,
        "pressure_inhg": pressure,
        "wind_mph": wind,
        "rain_rate_inhr": rain_rate,
        "uv_index": uv,
        "comfort_score": weather_comfort_score(temp_f, humidity, wind, rain_rate, uv),
    }


def save_snapshot(snapshot):
    captured_at = datetime.now(timezone.utc).isoformat()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO weather_snapshots (
                captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                wind_mph, rain_rate_inhr, uv_index, comfort_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                captured_at,
                snapshot.get("outdoor_temp_f"),
                snapshot.get("humidity_pct"),
                snapshot.get("pressure_inhg"),
                snapshot.get("wind_mph"),
                snapshot.get("rain_rate_inhr"),
                snapshot.get("uv_index"),
                snapshot.get("comfort_score"),
            ),
        )
        conn.commit()
    return captured_at


def trend_label(delta, positive_is_better):
    if delta is None:
        return "unknown"
    if abs(delta) < 0.01:
        return "steady"
    better = delta > 0 if positive_is_better else delta < 0
    return "better" if better else "worse"


@app.on_event("startup")
async def on_startup():
    init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


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
    # Keep endpoint for compatibility, but this still performs one fresh fetch.
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
            """
            SELECT captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                   wind_mph, rain_rate_inhr, uv_index, comfort_score
            FROM weather_snapshots
            WHERE captured_at >= datetime('now', ?)
            ORDER BY captured_at ASC
            """,
            (f"-{hours} hours",),
        ).fetchall()

    if len(rows) < 2:
        return {"status": "insufficient_data", "message": "Need at least 2 snapshots"}

    first, last = rows[0], rows[-1]

    def delta(field):
        if first[field] is None or last[field] is None:
            return None
        return round(last[field] - first[field], 3)

    comfort_delta = delta("comfort_score")
    overall = "steady"
    if comfort_delta is not None:
        if comfort_delta > 0.5:
            overall = "better"
        elif comfort_delta < -0.5:
            overall = "worse"

    return {
        "status": "ok",
        "window_hours": hours,
        "points": len(rows),
        "overall": overall,
        "comparison": {
            "comfort_score": {"delta": comfort_delta, "trend": trend_label(comfort_delta, True)},
            "temperature_f": {"delta": delta("outdoor_temp_f"), "trend": "info"},
            "humidity_pct": {"delta": delta("humidity_pct"), "trend": "info"},
            "pressure_inhg": {"delta": delta("pressure_inhg"), "trend": "info"},
            "wind_mph": {"delta": delta("wind_mph"), "trend": trend_label(delta("wind_mph"), False)},
            "rain_rate_inhr": {"delta": delta("rain_rate_inhr"), "trend": trend_label(delta("rain_rate_inhr"), False)},
            "uv_index": {"delta": delta("uv_index"), "trend": "info"},
        },
        "latest": dict(last),
    }


@app.get("/api/snapshots")
async def api_snapshots(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be 1..1000")

    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                   wind_mph, rain_rate_inhr, uv_index, comfort_score
            FROM weather_snapshots
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return {"status": "ok", "items": [dict(r) for r in rows]}


@app.get("/api/stats")
async def api_stats(hours: int = 24):
    if hours < 1 or hours > 720:
        raise HTTPException(status_code=400, detail="hours must be between 1 and 720")

    with db_conn() as conn:
        agg = conn.execute(
            """
            SELECT
                COUNT(*) AS points,
                MIN(outdoor_temp_f) AS temp_min_f,
                MAX(outdoor_temp_f) AS temp_max_f,
                AVG(outdoor_temp_f) AS temp_avg_f,
                MIN(humidity_pct) AS humidity_min,
                MAX(humidity_pct) AS humidity_max,
                AVG(humidity_pct) AS humidity_avg,
                AVG(pressure_inhg) AS pressure_avg_inhg,
                MAX(wind_mph) AS wind_max_mph,
                AVG(wind_mph) AS wind_avg_mph,
                SUM(COALESCE(rain_rate_inhr, 0)) AS rain_rate_sum,
                AVG(comfort_score) AS comfort_avg
            FROM weather_snapshots
            WHERE captured_at >= datetime('now', ?)
            """,
            (f"-{hours} hours",),
        ).fetchone()

        latest = conn.execute(
            """
            SELECT captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                   wind_mph, rain_rate_inhr, uv_index, comfort_score
            FROM weather_snapshots
            ORDER BY captured_at DESC
            LIMIT 1
            """
        ).fetchone()

    if not latest:
        return {"status": "insufficient_data", "message": "No snapshots yet"}

    latest_dt = datetime.fromisoformat(latest["captured_at"])
    age_seconds = int((datetime.now(timezone.utc) - latest_dt).total_seconds())

    def round_or_none(value, digits=2):
        if value is None:
            return None
        return round(float(value), digits)

    return {
        "status": "ok",
        "window_hours": hours,
        "points": int(agg["points"] or 0),
        "latest": dict(latest),
        "latest_age_seconds": max(0, age_seconds),
        "summary": {
            "temperature_f": {
                "min": round_or_none(agg["temp_min_f"], 2),
                "max": round_or_none(agg["temp_max_f"], 2),
                "avg": round_or_none(agg["temp_avg_f"], 2),
            },
            "humidity_pct": {
                "min": round_or_none(agg["humidity_min"], 1),
                "max": round_or_none(agg["humidity_max"], 1),
                "avg": round_or_none(agg["humidity_avg"], 1),
            },
            "pressure_inhg": {
                "avg": round_or_none(agg["pressure_avg_inhg"], 3),
            },
            "wind_mph": {
                "max": round_or_none(agg["wind_max_mph"], 2),
                "avg": round_or_none(agg["wind_avg_mph"], 2),
            },
            "rain_rate_sum_inhr": round_or_none(agg["rain_rate_sum"], 3),
            "comfort_score_avg": round_or_none(agg["comfort_avg"], 2),
        },
    }


@app.get("/api/ai-forecast")
async def api_ai_forecast():
    # Build context from last 24h stats + trend + current
    current = await fetch_current_from_ecowitt()

    stats_24 = await api_stats(hours=24)
    trend_24 = await api_trend(hours=24)

    with db_conn() as conn:
        points = conn.execute(
            """
            SELECT captured_at, outdoor_temp_f, humidity_pct, pressure_inhg,
                   wind_mph, rain_rate_inhr, uv_index, comfort_score
            FROM weather_snapshots
            WHERE captured_at >= datetime('now', '-24 hours')
            ORDER BY captured_at ASC
            LIMIT 288
            """
        ).fetchall()

    compact_points = []
    for r in points:
        compact_points.append({
            "t": r["captured_at"],
            "temp_f": r["outdoor_temp_f"],
            "hum_pct": r["humidity_pct"],
            "pressure_inhg": r["pressure_inhg"],
            "wind_mph": r["wind_mph"],
            "rain_rate_inhr": r["rain_rate_inhr"],
            "uv": r["uv_index"],
            "comfort": r["comfort_score"],
        })

    context_payload = {
        "current": current.get("data", {}),
        "stats_24h": stats_24,
        "trend_24h": trend_24,
        "samples_24h": compact_points,
        "timezone_hint": "Europe/London",
    }

    ai = await call_gemini_forecast(context_payload)
    return {
        "status": "ok",
        "model": GEMINI_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ai_forecast": ai,
    }


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
