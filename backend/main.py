import json
import threading
import time
import uuid
from datetime import datetime, timezone
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
_meta_lock = threading.Lock()


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def _explainer_url(run_id: str, filename: str) -> str:
    return f"/explainers/{run_id}/{filename}"


def _run_dir(run_id: str) -> Path:
    return EXPLAINERS_DIR / run_id


def _read_meta(run_id: str) -> dict | None:
    meta_path = _run_dir(run_id) / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_meta(run_id: str, meta: dict) -> None:
    with _meta_lock:
        (_run_dir(run_id) / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _update_meta(run_id: str, updates: dict) -> None:
    with _meta_lock:
        meta_path = _run_dir(run_id) / "meta.json"
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        meta.update(updates)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _compute_timing_report(events: list[dict]) -> list[dict]:
    """Derive how long each real pipeline stage took from the timestamped event log."""

    def first(stage: str):
        return next((e for e in events if e.get("stage") == stage and "t" in e), None)

    def all_of(stage: str):
        return [e for e in events if e.get("stage") == stage and "t" in e]

    report: list[dict] = []

    for label, start_stage, end_stage in (
        ("extract", "extracting", "claims_extracted"),
        ("judge", "judging", "judged"),
        ("explainer", "generating_explainer", "explainer_generated"),
    ):
        start, end = first(start_stage), first(end_stage)
        if start is not None and end is not None:
            report.append({"stage": label, "seconds": round(end["t"] - start["t"], 1)})

    investigating_start = first("investigating_start")
    investigated = all_of("investigated")
    if investigating_start is not None and investigated:
        last_t = max(e["t"] for e in investigated)
        report.append(
            {
                "stage": f"investigators (x{len(investigated)}, parallel)",
                "seconds": round(last_t - investigating_start["t"], 1),
            }
        )

    rendering = all_of("rendering")
    critique_results = all_of("critique_result")
    for r in rendering:
        cr = next((c for c in critique_results if c.get("version") == r.get("version")), None)
        if cr is not None:
            report.append({"stage": f"render+critic v{r['version']}", "seconds": round(cr["t"] - r["t"], 1)})

    fixing = all_of("fixing")
    for f in fixing:
        next_render = next((r for r in rendering if r.get("version") == f.get("to_version")), None)
        if next_render is not None:
            report.append(
                {
                    "stage": f"fixer v{f['from_version']}->v{f['to_version']}",
                    "seconds": round(next_render["t"] - f["t"], 1),
                }
            )

    extracting, judged, done = first("extracting"), first("judged"), first("done")
    if extracting is not None and judged is not None:
        report.append({"stage": "TIME TO VERDICT", "seconds": round(judged["t"] - extracting["t"], 1)})
    if extracting is not None and done is not None:
        report.append({"stage": "TIME TO FINAL EXPLAINER", "seconds": round(done["t"] - extracting["t"], 1)})

    return report


def _print_timing_report(run_id: str, label: str, report: list[dict]) -> None:
    print(f"\n--- Timing report: {label} (run {run_id}) ---")
    for item in report:
        print(f"  {item['stage']:<32} {item['seconds']:>7.1f}s")
    print("-" * 46)


def _stream_analysis(youtube_url: str | None, video: UploadFile | None):
    temp_path = None
    run_id = uuid.uuid4().hex
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    run_start = time.time()
    events_log: list[dict] = []
    source_label = youtube_url or (f"upload:{video.filename}" if video else "unknown")
    final_error: str | None = None

    try:
        if video:
            suffix = Path(video.filename).suffix or ".mp4"
            temp_path = UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
            with temp_path.open("wb") as out:
                out.write(video.file.read())
            pipeline_kwargs = {"file_path": str(temp_path)}
        else:
            pipeline_kwargs = {"youtube_url": youtube_url}

        for event in run_pipeline(explainer_dir=run_dir, **pipeline_kwargs):
            event["t"] = round(time.time() - run_start, 3)
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
            events_log.append(event)
            yield json.dumps(event) + "\n"
    except Exception as exc:  # noqa: BLE001
        final_error = str(exc)
        error_event = {"stage": "error", "message": final_error, "t": round(time.time() - run_start, 3)}
        events_log.append(error_event)
        yield json.dumps(error_event) + "\n"
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

        (run_dir / "events.ndjson").write_text(
            "\n".join(json.dumps(e) for e in events_log) + "\n", encoding="utf-8"
        )

        report = _compute_timing_report(events_log)
        _print_timing_report(run_id, "pipeline", report)

        done_event = next((e for e in events_log if e.get("stage") == "done"), None)
        video_verdict = None
        claim_count = 0
        if done_event:
            result = done_event.get("result", {})
            video_verdict = result.get("video_verdict", {}).get("verdict")
            claim_count = len(result.get("verdicts", []))

        _write_meta(
            run_id,
            {
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": source_label,
                "video_verdict": video_verdict,
                "claim_count": claim_count,
                "run_start_epoch": run_start,
                "duration_seconds": round(time.time() - run_start, 1),
                "timings": report,
                "error": final_error,
                "agent": None,
            },
        )


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
    agent_start = time.time()
    run_dir = _run_dir(run_id)
    meta = _read_meta(run_id) or {}
    run_start = meta.get("run_start_epoch", agent_start)

    def _append_event(event: dict) -> None:
        event["t"] = round(time.time() - run_start, 3)
        with (run_dir / "events.ndjson").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    total_sources = sum(len(v.sources) for v in verdicts)
    _append_event({"stage": "agent_started", "total_sources": total_sources})

    try:
        result = run_verification_agent(str(html_path), str(video_output_path), claims, verdicts)
        video_url = _explainer_url(run_id, video_output_path.name) if result["video_saved"] else None
        agent_result = {"video_url": video_url, "source_verifications": result["sources"]}
        with _agent_tasks_lock:
            _agent_tasks[task_id] = {"status": "done", "result": agent_result, "error": None}
        _append_event({"stage": "agent_done", "result": agent_result})
        agent_seconds = round(time.time() - agent_start, 1)
        _print_timing_report(run_id, "managed agent", [{"stage": "managed agent", "seconds": agent_seconds}])
        _update_meta(run_id, {"agent": {"status": "done", "seconds": agent_seconds, "video_url": video_url}})
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        with _agent_tasks_lock:
            _agent_tasks[task_id] = {"status": "failed", "result": None, "error": error_message}
        _append_event({"stage": "agent_failed", "error": error_message})
        agent_seconds = round(time.time() - agent_start, 1)
        _print_timing_report(run_id, "managed agent (failed)", [{"stage": "managed agent", "seconds": agent_seconds}])
        _update_meta(run_id, {"agent": {"status": "failed", "seconds": agent_seconds, "error": error_message}})


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


@app.get("/api/runs")
def list_runs():
    runs = []
    for run_dir in EXPLAINERS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        meta = _read_meta(run_dir.name)
        if meta is not None:
            runs.append(meta)
    runs.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return {"runs": runs}


app.mount("/explainers", StaticFiles(directory=EXPLAINERS_DIR), name="explainers")
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
