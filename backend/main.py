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
EXPLAINERS_DIR = BASE_DIR / "explainers"
EXPLAINERS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Veritas")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def _save_explainer(run_id: str, html: str) -> str:
    explainer_dir = EXPLAINERS_DIR / run_id
    explainer_dir.mkdir(parents=True, exist_ok=True)
    existing_versions = sorted(explainer_dir.glob("v*.html"))
    next_version = len(existing_versions) + 1
    explainer_path = explainer_dir / f"v{next_version}.html"
    explainer_path.write_text(html, encoding="utf-8")
    return f"/explainers/{run_id}/v{next_version}.html"


def _stream_analysis(youtube_url: str | None, video: UploadFile | None):
    temp_path = None
    run_id = uuid.uuid4().hex
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
            if event.get("stage") == "done" and "explainer_html" in event.get("result", {}):
                html = event["result"].pop("explainer_html")
                event["result"]["explainer_url"] = _save_explainer(run_id, html)
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


app.mount("/explainers", StaticFiles(directory=EXPLAINERS_DIR), name="explainers")
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
