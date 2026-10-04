# Mossling with Gemini verification

The WordPress page uploads each task photo and its matching task description to the FastAPI backend in `main.py`. Gemini verifies the image on the server; the browser never receives the Gemini API key. A failed backend/Gemini request does not complete the task.

## Deploy the backend

Deploy `main.py` as a Python 3.10+ ASGI app on a host that provides HTTPS. Install `requirements.txt`, set the server-side `GEMINI_API_KEY`, and configure:

- `CORS_ORIGINS`: the exact WordPress site origin, for example `https://your-domain.com` (no page path). Use comma-separated origins if both `www` and non-`www` domains serve the page.
- `TIGER_DATA_URL`: optional PostgreSQL/Timescale connection string if you want the attached backend's event logging and rewards.

Copy `.env.example` to `.env` for local development only; do not upload real secrets to WordPress or commit them.

For local development:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set GEMINI_API_KEY and CORS_ORIGINS in .env.
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The API verification route is `POST /verify-task`. It expects multipart fields `homework_image` (PNG/JPEG) and `task_description`.

## Connect the WordPress page

In `Mossling-WordPress.html` (or `index.html` for a custom integration), set the `VERIFICATION_API_URL` constant near the top of the app script to the deployed backend origin, such as `https://api.your-domain.com`. Leave it empty only when the backend is reverse-proxied on the exact same origin as WordPress. Then paste the full WordPress fragment into a Custom HTML block. The WordPress account must allow inline scripts and styles; otherwise use a trusted insertion plugin or the hosting administrator's supported method.

The app still saves pet progress locally in each visitor's browser. Gemini verification requires the independently deployed backend and a valid server-side API key. Tiger Data logging additionally requires `TIGER_DATA_URL` and a TimescaleDB-enabled PostgreSQL service.
