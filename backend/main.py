import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from backend.gemini_client import extract_claims_from_file, extract_claims_from_youtube  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"

app = FastAPI(title="Veritas")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.post("/api/extract-claims")
def extract_claims(youtube_url: str | None = Form(None), video: UploadFile | None = File(None)):
    if bool(youtube_url) == bool(video):
        raise HTTPException(status_code=400, detail="Provide exactly one of youtube_url or video")

    if youtube_url:
        result = extract_claims_from_youtube(youtube_url)
        return result.model_dump()

    suffix = Path(video.filename).suffix or ".mp4"
    temp_path = UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        with temp_path.open("wb") as out:
            out.write(video.file.read())
        result = extract_claims_from_file(str(temp_path))
        return result.model_dump()
    finally:
        temp_path.unlink(missing_ok=True)


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
