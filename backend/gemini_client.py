import json
import os
import time

from google import genai

from backend.schemas import ClaimExtractionResult

MODEL = "gemini-4-argon"

CLAIM_EXTRACTION_PROMPT = """Watch this video and extract every factual claim made in it — \
by speech or on-screen text. A factual claim is something that could be checked against evidence \
(a statistic, a described event, a quote attributed to someone, or another checkable assertion). \
Ignore pure opinions, predictions, and value judgments.

For each claim, return:
- speaker: who said or presented it (name, role, or "on-screen text" / "narrator" if no named speaker)
- timestamp: MM:SS where the claim occurs in the video
- exact_wording: the claim transcribed verbatim, not paraphrased or summarized
- claim_type: one of "statistic", "event", "quote", "other"

Return every claim you find, in the order they occur."""

_FILE_POLL_INTERVAL_SECONDS = 3
_FILE_POLL_TIMEOUT_SECONDS = 300
_INTERACTION_POLL_INTERVAL_SECONDS = 5
_INTERACTION_POLL_TIMEOUT_SECONDS = 1200


def _client() -> genai.Client:
    api_key = os.environ["GEMINI_API_KEY"]
    return genai.Client(api_key=api_key, http_options={"timeout": 1200000})


def _run_claim_extraction(client: genai.Client, video_content: dict) -> ClaimExtractionResult:
    interaction = client.interactions.create(
        model=MODEL,
        input=[
            {"type": "text", "text": CLAIM_EXTRACTION_PROMPT},
            video_content,
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ClaimExtractionResult.model_json_schema(),
        },
        generation_config={"thinking_level": "medium"},
        background=True,
    )

    deadline = time.time() + _INTERACTION_POLL_TIMEOUT_SECONDS
    while interaction.status in ("in_progress", "queued"):
        if time.time() > deadline:
            raise TimeoutError("Claim extraction timed out waiting on gemini-4-argon")
        time.sleep(_INTERACTION_POLL_INTERVAL_SECONDS)
        interaction = client.interactions.get(interaction.id)

    if interaction.status != "completed":
        raise RuntimeError(f"Claim extraction failed with status={interaction.status}: {interaction.error}")

    raw = interaction.output_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return ClaimExtractionResult.model_validate(json.loads(raw))


def extract_claims_from_youtube(youtube_url: str) -> ClaimExtractionResult:
    client = _client()
    video_content = {"type": "video", "uri": youtube_url}
    return _run_claim_extraction(client, video_content)


def extract_claims_from_file(file_path: str) -> ClaimExtractionResult:
    client = _client()
    uploaded = client.files.upload(file=file_path)

    deadline = time.time() + _FILE_POLL_TIMEOUT_SECONDS
    while uploaded.state == "PROCESSING":
        if time.time() > deadline:
            raise TimeoutError("Video upload timed out processing on Gemini's side")
        time.sleep(_FILE_POLL_INTERVAL_SECONDS)
        uploaded = client.files.get(name=uploaded.name)

    if uploaded.state != "ACTIVE":
        raise RuntimeError(f"Uploaded video failed to process: state={uploaded.state}")

    video_content = {"type": "video", "uri": uploaded.uri, "mime_type": uploaded.mime_type}
    return _run_claim_extraction(client, video_content)
