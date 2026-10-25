import json
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from backend.gemini_client import run_pipeline, run_verification_agent  # noqa: E402
from backend.schemas import Claim, Verdict  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"
EXPLAINERS_DIR = BASE_DIR / "explainers"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
EXPLAINERS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Veritas")

_agent_tasks: dict[str, dict] = {}
_agent_tasks_lock = threading.Lock()


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def _explainer_url(run_id: str, filename: str) -> str:
    return f"/explainers/{run_id}/{filename}"


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

        for event in run_pipeline(explainer_dir=EXPLAINERS_DIR / run_id, **pipeline_kwargs):
            stage = event.get("stage")
            if stage == "critique_result":
                event["url"] = _explainer_url(run_id, event["filename"])
            elif stage == "done":
                versions = event.get("result", {}).get("versions", [])
                for version in versions:
                    version["url"] = _explainer_url(run_id, version["filename"])
                if versions:
                    event["result"]["explainer_url"] = versions[-1]["url"]
                event["result"]["run_id"] = run_id
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


class AgentTaskRequest(BaseModel):
    run_id: str
    filename: str
    claims: list[Claim]
    verdicts: list[Verdict]


def _run_agent_task(task_id: str, html_path: Path, video_output_path: Path, run_id: str, claims, verdicts):
    try:
        result = run_verification_agent(str(html_path), str(video_output_path), claims, verdicts)
        video_url = _explainer_url(run_id, video_output_path.name) if result["video_saved"] else None
        with _agent_tasks_lock:
            _agent_tasks[task_id] = {
                "status": "done",
                "result": {"video_url": video_url, "source_verifications": result["sources"]},
                "error": None,
            }
    except Exception as exc:  # noqa: BLE001
        with _agent_tasks_lock:
            _agent_tasks[task_id] = {"status": "failed", "result": None, "error": str(exc)}


@app.post("/api/agent-tasks")
def start_agent_task(payload: AgentTaskRequest):
    html_path = EXPLAINERS_DIR / payload.run_id / payload.filename
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="Explainer file not found")

    task_id = uuid.uuid4().hex
    video_output_path = EXPLAINERS_DIR / payload.run_id / "explainer.mp4"

    with _agent_tasks_lock:
        _agent_tasks[task_id] = {"status": "working", "result": None, "error": None}

    thread = threading.Thread(
        target=_run_agent_task,
        args=(task_id, html_path, video_output_path, payload.run_id, payload.claims, payload.verdicts),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id}


@app.get("/api/agent-tasks/{task_id}")
def get_agent_task(task_id: str):
    with _agent_tasks_lock:
        task = _agent_tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown task_id")
    return task


app.mount("/explainers", StaticFiles(directory=EXPLAINERS_DIR), name="explainers")
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
