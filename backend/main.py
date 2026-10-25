import json
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from backend.gemini_client import run_pipeline  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"

app = FastAPI(title="Veritas")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def _stream_analysis(youtube_url: str | None, video: UploadFile | None):
    temp_path = None
    try:
        if video:
            suffix = Path(video.filename).suffix or ".mp4"
            temp_path = UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
            with temp_path.open("wb") as out:
                out.write(video.file.read())
            pipeline_kwargs = {"file_path": str(temp_path)}
        else:
            pipeline_kwargs = {"youtube_url": youtube_url}

        for event in run_pipeline(**pipeline_kwargs):
            yield json.dumps(event) + "\n"
    except Exception as exc:  # noqa: BLE001
        yield json.dumps({"stage": "error", "message": str(exc)}) + "\n"
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


@app.post("/api/analyze")
def analyze(youtube_url: str | None = Form(None), video: UploadFile | None = File(None)):
    if bool(youtube_url) == bool(video):
        raise HTTPException(status_code=400, detail="Provide exactly one of youtube_url or video")

    return StreamingResponse(_stream_analysis(youtube_url, video), media_type="application/x-ndjson")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
