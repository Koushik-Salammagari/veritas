import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai

from backend.schemas import Claim, ClaimExtractionResult, Finding, JudgeResult

EXTRACTOR_MODEL = "gemini-4-argon"
INVESTIGATOR_MODEL = "gemini-3.8-flash"
JUDGE_MODEL = "gemini-4-argon"

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

INVESTIGATOR_PROMPT_TEMPLATE = """You are a fact-checking investigator. Research the following claim \
using Google Search.

Claim: "{exact_wording}"
Speaker: {speaker}
Claim type: {claim_type}
Timestamp in source video: {timestamp}

Find what trusted sources say about this specific claim. Prefer, in this order: primary sources \
(official data, direct records, the original footage or statement), established fact-checkers \
(Reuters Fact Check, AP Fact Check, PolitiFact, FactCheck.org, Snopes, Full Fact), and reputable news \
organizations. Avoid low-quality or unverified sources.

Return:
- summary: 2-4 sentences on what the evidence shows about this claim.
- sources: the specific sources you found, each with a title and the exact URL.

If you cannot find reliable evidence either way, say so plainly in the summary and return an empty \
sources list."""

JUDGE_PROMPT_TEMPLATE = """You are the judge in a fact-checking pipeline. Below is a list of claims \
extracted from a video, each paired with an investigator's research findings (a summary plus sources \
found via Google Search). Decide a verdict for each claim using ONLY the evidence given below.

Rules:
- verdict must be one of: true, misleading, false, unverifiable.
- NEVER mark a claim "false" or "misleading" unless the investigator's findings include at least one \
source URL that supports your reasoning. If the evidence is weak, missing, or sources are empty, use \
"unverifiable" instead.
- confidence is a number from 0 to 1 reflecting how certain you are given the evidence.
- misleading_technique applies only when verdict is "misleading": one of "out of context", \
"old footage", "cherry-picked number", "missing context", "fabricated". Leave it null otherwise.
- explanation is exactly one sentence.
- sources: the source URLs (with titles) from the investigator's findings that support your verdict. \
Must be non-empty for every "false" or "misleading" verdict.
- claim_index must match the index given for each claim below.

After judging every claim individually, write one paragraph for what_actually_happened explaining, in \
plain language, what is actually true about the overall topic covered in the video, synthesizing across \
all claims.

Claims and investigator findings:
{claims_and_findings_json}"""

_FILE_POLL_INTERVAL_SECONDS = 3
_FILE_POLL_TIMEOUT_SECONDS = 300
_INTERACTION_POLL_INTERVAL_SECONDS = 5
_EXTRACTION_TIMEOUT_SECONDS = 1200
_INVESTIGATION_TIMEOUT_SECONDS = 180
_JUDGE_TIMEOUT_SECONDS = 1200
_MAX_PARALLEL_INVESTIGATIONS = 8


def _client() -> genai.Client:
    api_key = os.environ["GEMINI_API_KEY"]
    return genai.Client(api_key=api_key, http_options={"timeout": 1200000})


def _await_interaction(client: genai.Client, interaction, timeout_seconds: float):
    deadline = time.time() + timeout_seconds
    while interaction.status in ("in_progress", "queued"):
        if time.time() > deadline:
            raise TimeoutError(f"Gemini call timed out after {timeout_seconds}s")
        time.sleep(_INTERACTION_POLL_INTERVAL_SECONDS)
        interaction = client.interactions.get(interaction.id)

    if interaction.status != "completed":
        raise RuntimeError(f"Gemini call failed with status={interaction.status}: {interaction.error}")
    return interaction


def _parse_json_output(interaction) -> dict:
    raw = interaction.output_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def _await_file_active(client: genai.Client, uploaded):
    deadline = time.time() + _FILE_POLL_TIMEOUT_SECONDS
    while uploaded.state == "PROCESSING":
        if time.time() > deadline:
            raise TimeoutError("Video upload timed out processing on Gemini's side")
        time.sleep(_FILE_POLL_INTERVAL_SECONDS)
        uploaded = client.files.get(name=uploaded.name)

    if uploaded.state != "ACTIVE":
        raise RuntimeError(f"Uploaded video failed to process: state={uploaded.state}")
    return uploaded


def _extract_claims(client: genai.Client, video_content: dict) -> ClaimExtractionResult:
    interaction = client.interactions.create(
        model=EXTRACTOR_MODEL,
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
    interaction = _await_interaction(client, interaction, _EXTRACTION_TIMEOUT_SECONDS)
    return ClaimExtractionResult.model_validate(_parse_json_output(interaction))


def _investigate_claim(client: genai.Client, claim: Claim) -> Finding:
    prompt = INVESTIGATOR_PROMPT_TEMPLATE.format(
        exact_wording=claim.exact_wording,
        speaker=claim.speaker,
        claim_type=claim.claim_type,
        timestamp=claim.timestamp,
    )
    interaction = client.interactions.create(
        model=INVESTIGATOR_MODEL,
        input=prompt,
        tools=[{"type": "google_search"}],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Finding.model_json_schema(),
        },
    )
    interaction = _await_interaction(client, interaction, _INVESTIGATION_TIMEOUT_SECONDS)
    return Finding.model_validate(_parse_json_output(interaction))


def _judge_claims(client: genai.Client, claims: list[Claim], findings: list[Finding]) -> JudgeResult:
    claims_and_findings = [
        {
            "claim_index": i,
            "speaker": claim.speaker,
            "timestamp": claim.timestamp,
            "claim_type": claim.claim_type,
            "exact_wording": claim.exact_wording,
            "investigator_summary": finding.summary,
            "investigator_sources": [s.model_dump() for s in finding.sources],
        }
        for i, (claim, finding) in enumerate(zip(claims, findings))
    ]
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        claims_and_findings_json=json.dumps(claims_and_findings, indent=2)
    )
    interaction = client.interactions.create(
        model=JUDGE_MODEL,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": JudgeResult.model_json_schema(),
        },
        generation_config={"thinking_level": "high"},
        background=True,
    )
    interaction = _await_interaction(client, interaction, _JUDGE_TIMEOUT_SECONDS)
    result = JudgeResult.model_validate(_parse_json_output(interaction))

    # Safety net for the "never false/misleading without a source" rule.
    for verdict in result.verdicts:
        if verdict.verdict in ("false", "misleading") and not verdict.sources:
            verdict.verdict = "unverifiable"
            verdict.misleading_technique = None

    return result


def run_pipeline(youtube_url: str | None = None, file_path: str | None = None) -> Iterator[dict]:
    client = _client()

    yield {"stage": "extracting"}
    if youtube_url:
        video_content = {"type": "video", "uri": youtube_url}
    else:
        uploaded = client.files.upload(file=file_path)
        uploaded = _await_file_active(client, uploaded)
        video_content = {"type": "video", "uri": uploaded.uri, "mime_type": uploaded.mime_type}

    extraction = _extract_claims(client, video_content)
    claims = extraction.claims
    yield {"stage": "claims_extracted", "claims": [c.model_dump() for c in claims]}

    if not claims:
        yield {
            "stage": "done",
            "result": {
                "verdicts": [],
                "what_actually_happened": "No checkable factual claims were found in this video.",
            },
        }
        return

    yield {"stage": "investigating_start", "total": len(claims)}

    findings: list[Finding | None] = [None] * len(claims)
    with ThreadPoolExecutor(max_workers=min(len(claims), _MAX_PARALLEL_INVESTIGATIONS)) as pool:
        future_to_index = {pool.submit(_investigate_claim, client, claim): i for i, claim in enumerate(claims)}
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            try:
                finding = future.result()
            except Exception as exc:  # noqa: BLE001
                finding = Finding(summary=f"Investigation failed: {exc}", sources=[])
            findings[i] = finding
            yield {"stage": "investigated", "claim_index": i, "finding": finding.model_dump()}

    yield {"stage": "judging"}
    judge_result = _judge_claims(client, claims, findings)
    yield {"stage": "done", "result": judge_result.model_dump()}
