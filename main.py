import json
import os
from typing import Any
import psycopg2
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI()

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024


def _is_supported_image(filename: str | None, content_type: str | None) -> bool:
    if content_type and content_type.lower() in SUPPORTED_IMAGE_TYPES:
        return True
    if filename:
        lowered = filename.lower()
        return lowered.endswith(".jpg") or lowered.endswith(".jpeg") or lowered.endswith(".png")
    return False


async def _verify_with_gemini(file_bytes: bytes, filename: str, task_description: str) -> dict[str, Any]:
    """Analyzes the image and returns a friendly human evaluation based on the specific task."""
    try:
        from google import genai
        client = genai.Client()

        prompt = (
            "You are a friendly, encouraging academic mentor. "
            f"The student claims they completed the following specific task: '{task_description}'. "
            "Examine this uploaded image and determine if it shows genuine schoolwork that directly aligns with and satisfies this specific task. "
            "Respond strictly in valid JSON format with two fields:\n"
            "1. 'verified': boolean (true if the image clearly matches the stated task, false if it does not align or isn't schoolwork)\n"
            "2. 'feedback': string (A warm 1-2 sentence response. If verified, praise their specific effort on this task. If not verified, gently explain why the image doesn't seem to match the stated task and ask them to re-upload.)"
        )

        mime = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
        response = client.models.generate_content(
            # Using 1.5-flash to avoid 503 traffic errors
            model="gemini-3.8-flash",
            contents=[
                prompt,
                {"inline_data": {"mime_type": mime, "data": file_bytes}}
            ],
            config={"response_mime_type": "application/json"},
        )

        text = getattr(response, "text", "")
        if not text:
            return {
                "verified": False,
                "feedback": "We couldn't process the image clearly. Please try re-uploading a sharper photo of your assignment.",
                "source": "gemini-empty-response",
            }

        payload = json.loads(text)
        verified = payload.get("verified")
        feedback = payload.get("feedback")
        if not isinstance(verified, bool) or not isinstance(feedback, str) or not feedback.strip():
            raise ValueError("Gemini returned an invalid verification response.")
        return {
            "verified": verified,
            "feedback": feedback.strip(),
            "source": "gemini-api",
        }

    except Exception as e:
        print(f"Gemini API Error: {e}")
        raise HTTPException(
            status_code=502,
            detail="Gemini verification failed. Please try again.",
        ) from e


def _update_tiger_data(filename: str, task_description: str, verified: bool, energy: int) -> None:
    """Logs the submission event and the stated task into Tiger Data."""
    tiger_data_url = os.getenv("TIGER_DATA_URL")
    if not tiger_data_url:
        print("TIGER_DATA_URL is not set. Skipping database update.")
        return

    try:
        conn = psycopg2.connect(tiger_data_url)
        conn.autocommit = True
        cursor = conn.cursor()

        # 1. Create the base table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_tasks (
                timestamp TIMESTAMPTZ NOT NULL,
                filename TEXT NOT NULL,
                verified BOOLEAN NOT NULL,
                energy_earned INT NOT NULL
            );
        """)

        # 2. Add the task_description column if it is missing
        cursor.execute("""
            ALTER TABLE pet_tasks 
            ADD COLUMN IF NOT EXISTS task_description TEXT;
        """)

        # 3. Convert to time-series hypertable
        cursor.execute("""
            SELECT create_hypertable('pet_tasks', 'timestamp', if_not_exists => TRUE);
        """)

        # 4. Insert the new log
        cursor.execute(
            """
            INSERT INTO pet_tasks (timestamp, filename, task_description, verified, energy_earned)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (datetime.now(timezone.utc), filename, task_description, verified, energy)
        )

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Tiger Data Error: {e}")


def _get_reward_summary() -> dict[str, int]:
    """Calculates total points and verified tasks."""
    tiger_data_url = os.getenv("TIGER_DATA_URL")
    if not tiger_data_url:
        return {"total_energy": 0, "tasks_completed": 0}

    try:
        conn = psycopg2.connect(tiger_data_url)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COALESCE(SUM(energy_earned), 0),
                COUNT(*) FILTER (WHERE verified = TRUE)
            FROM pet_tasks;
        """)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return {
            "total_energy": int(row[0]) if row else 0,
            "tasks_completed": int(row[1]) if row else 0,
        }
    except Exception as e:
        print(f"Error fetching rewards: {e}")
        return {"total_energy": 0, "tasks_completed": 0}


@app.get("/rewards")
def get_rewards():
    """Returns current cumulative points and completed tasks."""
    return _get_reward_summary()


@app.post("/verify-task")
async def verify_homework(
    homework_image: UploadFile = File(...),
    task_description: str = Form(...)
):
    """The main endpoint that receives the image AND the text description from the frontend."""
    task_description = task_description.strip()
    if not task_description:
        raise HTTPException(status_code=400, detail="Enter a description of the task.")

    if not _is_supported_image(homework_image.filename, homework_image.content_type):
        raise HTTPException(status_code=400, detail="Upload a PNG or JPEG image.")

    file_bytes = await homework_image.read(MAX_IMAGE_SIZE + 1)
    if len(file_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="Images must be 10 MB or smaller.")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image was empty.")

    validation = await _verify_with_gemini(file_bytes, homework_image.filename or "upload", task_description)
    verified = validation["verified"]
    points_earned = 10 if verified else 0

    # Record every attempt in Tiger Data
    _update_tiger_data(homework_image.filename or "upload", task_description, verified, points_earned)

    rewards = _get_reward_summary()

    return {
        "filename": homework_image.filename,
        "verified": verified,
        "feedback": validation["feedback"],
        "points_earned": points_earned,
        "total_points": rewards["total_energy"],
        "tasks_completed": rewards["tasks_completed"],
    }


@app.post("/reset-history")
def reset_history():
    """Instantly wipes the pet_tasks table to reset all points and history."""
    tiger_data_url = os.getenv("TIGER_DATA_URL")
    if not tiger_data_url:
        return {"status": "error", "message": "Database URL not found."}

    try:
        conn = psycopg2.connect(tiger_data_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # This clears the database directly from the API request
        cursor.execute("TRUNCATE pet_tasks;")
        
        cursor.close()
        conn.close()
        return {"status": "success", "message": "History and points completely reset."}
        
    except Exception as e:
        print(f"Error resetting database: {e}")
        return {"status": "error", "message": "Failed to reset database."}