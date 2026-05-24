<<<<<<< HEAD
# Ecowitt-Weather-API-Dashboard
=======
# Ecowitt Weather Dashboard (FastAPI + SQLite + AI Forecast)

Live weather dashboard for Ecowitt stations with:
- live current conditions
- local SQLite history storage
- trend/stat summaries from saved data
- optional Gemini AI 24-hour forecast narrative

## What this does

This project has two parts:
1. `api/` FastAPI backend that pulls Ecowitt data and stores snapshots to SQLite.
2. `static/weather.html` dashboard frontend that reads backend endpoints.

The backend can auto-save periodic snapshots (recommended on VPS via systemd timer), so your trends and AI summary survive browser refreshes and reconnects.

## Project structure

- `api/app.py` main backend app
- `api/requirements.txt` Python dependencies
- `api/.env.example` environment template
- `static/weather.html` dashboard UI
- `data/weather_data.db` SQLite database (created automatically)
- `index.html` redirect to `/weather-dashboard/static/weather.html`

## Requirements

- Python 3.10+
- `pip`
- `venv` (recommended)
- Reverse proxy (Caddy/Nginx) for production

## 1) Get Ecowitt API credentials

1. Sign in at [Ecowitt](https://www.ecowitt.net/).
2. Open the developer/API section and create/find:
   - Application Key
   - API Key
3. Find your station MAC address (format like `AA:BB:CC:DD:EE:FF`).
4. Test quickly (optional):
   - `GET https://api.ecowitt.net/api/v3/device/real_time?...`

## 2) (Optional) Get Gemini API key for AI Forecast

1. Create a key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Copy the key into `GEMINI_API_KEY` in `.env`.
3. Default model is `gemini-2.5-flash-lite` (low-cost).

If `GEMINI_API_KEY` is blank, the dashboard still works, but AI forecast will show unavailable.

## 3) Configure environment variables

From `api/`:

```bash
cp .env.example .env
```

Edit `.env` and fill:

- `APPLICATION_KEY=...`
- `API_KEY=...`
- `MAC_ADDRESS=AA:BB:CC:DD:EE:FF`
- `WEATHER_DB_PATH=../data/weather_data.db` (or absolute path on VPS)
- `GEMINI_API_KEY=...` (optional)
- `GEMINI_MODEL=gemini-2.5-flash-lite` (optional)
- `BACKUP_LLM_PROVIDER=openrouter` (or `openai`)
- `OPENROUTER_API_KEY=...` (recommended backup)
- `OPENROUTER_MODEL=openai/gpt-4o-mini`
- `OPENAI_API_KEY=...` (optional alternative backup)
- `OPENAI_MODEL=gpt-4o-mini`

## 4) Run locally

Linux/macOS:

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Windows (PowerShell):

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open:
- `http://127.0.0.1:8000/weather-dashboard/static/weather.html`

## 5) Backend API endpoints

- `GET /health` health check
- `GET /api/current` fetch latest Ecowitt payload
- `GET /api/current?save=1` fetch latest + save snapshot
- `POST /api/snapshot` save one snapshot
- `GET /api/trend?hours=6` trend summary from DB
- `GET /api/stats?hours=24` 24h DB stats
- `GET /api/snapshots?limit=100` recent snapshots
- `GET /api/ai-forecast` AI text summary using DB + current data

## AI failover behavior

The AI endpoint uses provider failover:
1. Primary: Gemini (`GEMINI_API_KEY`)
2. Backup: OpenRouter or OpenAI (based on `BACKUP_LLM_PROVIDER`)
3. Final fallback: local DB-generated forecast text

If Gemini quota is exhausted, the app will automatically try the backup provider before falling back locally.

## 6) Recommended production setup (VPS)

1. Put project at `/var/www/weather-dashboard`
2. Create Python venv in project folder
3. Install requirements
4. Create `weather-dashboard.service` (uvicorn)
5. Create `weather-collector.timer` + `weather-collector.service` for periodic `GET /api/current?save=1`
6. Reverse proxy `/api/*` to `127.0.0.1:8000`
7. Serve static from `/var/www`

## 7) Data persistence behavior

- Browser refresh/close does **not** delete history.
- DB lives on disk (`WEATHER_DB_PATH`), so history remains across restarts.
- Trend/Stats/AI quality improves as more snapshots are collected.

## 8) Security notes

- Never commit real keys in `.env`.
- Keep `.env` server-side only.
- Rotate keys if accidentally exposed.


>>>>>>> 29a35f0 (Initial public release: Ecowitt dashboard + FastAPI backend + docs)
