# Hap-i-ling

Hap-i-ling is a single-page study garden where students upload a photo of their work alongside a task description. Gemini checks whether the image matches the task, responds with encouraging feedback, and verified submissions earn 10 energy points recorded in Tiger Data.

## Run locally

Requires Python 3.10+ and a Tiger Data/PostgreSQL database with the TimescaleDB extension enabled.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with your Gemini API key and Tiger Data/PostgreSQL connection URL.
npm start
```

Open [http://localhost:8000](http://localhost:8000). FastAPI serves the frontend and its API from the same local server. Set `GEMINI_API_KEY` and either `TIGER_DATA_URL` or `DATABASE_URL` in `.env`; the database URL must point to a TimescaleDB-enabled PostgreSQL instance.

## Backend endpoints

- `POST /verify-task`: accepts `homework_image` (PNG/JPEG) and `task_description` multipart fields. Gemini verification is required; verified work earns 10 energy points.
- `GET /rewards`: returns the persisted energy-point and verified-task totals.
- `POST /reset-history`: clears the demo's submission history and energy total. The Settings page also provides a confirmed reset action.

The database table is initialized on demand as a TimescaleDB hypertable. Gemini and database errors are returned as failed requests rather than awarding points without verification or persistence.
