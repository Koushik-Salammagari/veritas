import json
import os
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai

from backend.schemas import (
    Claim,
    ClaimExtractionResult,
    Critique,
    EditingSignal,
    ExtractedClaim,
    Finding,
    JudgeResult,
    Verdict,
)

EXTRACTOR_MODEL = "gemini-4-argon"
INVESTIGATOR_MODEL = "gemini-3.8-flash"
JUDGE_MODEL = "gemini-4-argon"
EXPLAINER_MODEL = "gemini-4-argon"
CRITIC_MODEL = "gemini-4-argon"
FIXER_MODEL = "gemini-4-argon"
AGENT = "antigravity-preview-09-2026"
AGENT_UNDERLYING_MODEL = "gemini-4-argon"

CLAIM_EXTRACTION_PROMPT = """Watch this video and extract every factual claim made in it — \
by speech or on-screen text. A factual claim is something that could be checked against evidence \
(a statistic, a described event, a quote attributed to someone, or another checkable assertion). \
Ignore pure opinions, predictions, and value judgments.

For each claim, return:
- speaker: who said or presented it (name, role, or "on-screen text" / "narrator" if no named speaker)
- timestamp: MM:SS where the claim occurs in the video
- exact_wording: the claim transcribed verbatim, not paraphrased or summarized
- claim_type: one of "statistic", "event", "quote", "other"

If the exact same claim is made more than once in the video (e.g. a clip is repeated or spliced back \
in), return it once per occurrence with its own timestamp — do not deduplicate.

Also watch for signs of editing: hard cuts, the same footage or segment appearing more than once, \
overlays, and on-screen captions (especially captions that don't match what is said). For each one you \
notice, return an editing_signal with its timestamp (or MM:SS-MM:SS range) and a short description of \
what you saw.

Return every claim you find, in the order they occur, plus every editing signal you notice."""

INVESTIGATOR_PROMPT_TEMPLATE = """You are a fact-checking investigator. Research the following claim \
using Google Search.

Claim: "{exact_wording}"
Speaker: {speaker}
Claim type: {claim_type}
Timestamp(s) in source video: {timestamps}{repeat_note}

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
found via Google Search), plus any signs of editing noticed while extracting claims. Decide a verdict \
for each claim and one overall verdict for the video, using ONLY the evidence given below.

Judge the substance, not the quote. Many claims report what someone said, claimed, charged, or alleged \
(e.g. "the senator claimed X", "he said X", "Coleman charged that X", "the report says X"). For these, \
verdict and attribution are two SEPARATE questions — never let one influence the other:
1. verdict = is X (the underlying assertion) actually true? Judge this ONLY against the investigator's \
findings, as if X had been stated directly with no attribution at all.
2. attribution = did the speaker actually say/claim/charge X? "accurate" if yes (the quote/attribution \
checks out), "inaccurate" if the video misquotes, fabricates, or misattributes it. Set attribution to \
null only for claims that are NOT reporting someone else's speech (e.g. a narrator or on-screen text \
directly asserting a fact in its own voice).

Worked example: the claim "Coleman charged that the 97% consensus figure was manipulated" — if the \
investigator's findings show Coleman really did say this (he did) AND show the 97% figure was NOT \
manipulated (it wasn't), then verdict = "false" (the assertion that the figure was manipulated is false) \
and attribution = "accurate" (he really did charge this). The verdict must NOT become "misleading" or \
"true" just because the speaker genuinely said it, and it must NOT become "unverifiable" just because the \
claim is attributed to someone — attribution accuracy and substance truth are independent.

Per-claim rules:
- verdict must be one of: true, misleading, false, unverifiable. It is a judgment of the SUBSTANCE only.
- Use "false" whenever the substance is factually wrong — including a reported claim/charge/allegation \
whose content is wrong. Do not downgrade a false substance to "misleading" just because it was quoted \
accurately, repeated from an old broadcast, or left uncorrected; those are separate facts (captured by \
attribution and by the video-level techniques), not reasons to soften the per-claim verdict.
- Use "misleading" only when the substance itself is technically true/defensible but presented in a way \
that creates a false impression (a true number quoted out of context, a cherry-picked timeframe, a \
decontextualized clip) — not merely because a false claim went unchallenged.
- NEVER mark a claim "false" or "misleading" unless the investigator's findings include at least one \
source URL that supports your reasoning. If the evidence is weak, missing, or sources are empty, use \
"unverifiable" instead.
- confidence is a number from 0 to 1 reflecting how certain you are given the evidence.
- misleading_technique applies only when verdict is "misleading": one of "out of context", \
"old footage", "cherry-picked number", "missing context", "fabricated". Leave it null otherwise.
- explanation is exactly one sentence, about the substance (mention attribution only if it adds \
necessary nuance).
- sources: the source URLs (with titles) from THAT CLAIM's investigator findings that support your \
verdict. You MUST copy these exactly from the investigator_sources list given for that claim below — \
never write a URL from memory or from a different claim's findings. If none of that claim's \
investigator_sources actually support your verdict, leave sources empty. Must be non-empty for every \
"false" or "misleading" verdict.
- claim_index must match the index given for each claim below.
- occurrence_count greater than 1 means this exact claim was repeated verbatim in the video. Repeated or \
spliced segments can be a sign of deceptive editing even when the claim's factual content checks out — \
weigh this when judging the claim and, more importantly, when judging the video overall.

Video-level verdict (video_verdict):
- verdict is one of: accurate, misleading, false. Base it on the pattern across all claims and the \
editing signals below, not on any single claim in isolation.
- Use "false" when the video's central message or main claim is itself factually false — check which \
claim(s) carry the video's main point and look at their per-claim verdicts above; if those are "false", \
the video verdict is "false" too. Don't soften this to "misleading" just because the video also uses \
editing tricks; if the core thing it wants you to believe is false, the verdict is false.
- Use "misleading" when the video's individual claims are true (or the central message itself holds up) \
but the overall impression is deceptive through editing, missing context, or selective framing.
- Use "accurate" when there's no deception and the central message is true.
- techniques: zero or more of "repeated or spliced segments", "old footage presented as new", \
"missing context", "misleading title or caption", "cherry-picked clips" — list only techniques actually \
supported by the claims, findings, or editing signals below. Leave empty if verdict is "accurate".
- explanation: 1-3 sentences justifying the overall verdict.

After judging, also write one paragraph for what_actually_happened explaining, in plain language, what \
is actually true about the overall topic covered in the video, synthesizing across all claims.

Editing signals noticed while extracting claims (cuts, repeated segments, overlays, captions):
{editing_signals_json}

Claims and investigator findings:
{claims_and_findings_json}"""

EXPLAINER_PROMPT_TEMPLATE = """Generate a single self-contained HTML page that works as a SHORT, FAST \
animated explainer of a fact-check report, suitable for sharing (e.g. embedded in a page or shown on a \
projector).

Output requirements:
- Output ONLY the raw HTML document, starting with <!DOCTYPE html>. No markdown, no code fences, no \
commentary before or after it.
- Self-contained: all CSS and JavaScript inline in the page via <style> and <script> tags. Do not use any \
external dependency except, if truly needed, a script from cdnjs.cloudflare.com or cdn.jsdelivr.net/npm/ \
— prefer plain CSS animations and vanilla JS over any library.
- Auto-playing: the animation must start automatically on page load with no interaction required, and run \
for about 14 to 18 seconds total before holding on a final summary frame (looping back to the start after \
a pause is fine). Keep per-slide dwell time short (2.5-3.5s) so the whole thing stays brisk.
- Clean, readable design: dark background, large legible type, generous spacing, one idea on screen at a \
time (a slideshow-style sequence with smooth CSS transitions between frames). Use color to communicate \
verdicts — green for true/accurate, orange for misleading, red for false, gray for unverifiable — \
consistently throughout.
- Responsive enough to still look reasonable in a small embedded iframe around 960x540.

The animation sequence should show, in this order:
1. The video's overall verdict as a bold title card, with the misleading techniques used, if any.
2. Each key claim with its individual verdict badge and a one-line reason (cap this at the 3 most \
important claims if there are more — prefer the ones that drive the overall verdict). The verdict badge \
is about the substance of the claim, not whether someone said it; if a claim has a non-null attribution, \
show a small separate "attribution: accurate" or "attribution: inaccurate" tag next to it.
3. If the video is misleading or false, a card explaining how it misleads, using the techniques and \
explanations given.
4. A "What actually happened" card with the true story in plain language, kept to 2-3 sentences.
5. A final card listing the main sources (title and domain, not full URLs) used to verify the claims, \
capped at 4 sources.

Keep this short and simple — fewer slides, less text per slide, and a simple CSS transition (opacity/\
transform fade) are all fine. Here is the fact-check data to visualize:
{data_json}"""

CRITIC_PROMPT_TEMPLATE = """You are a strict critic reviewing a short animated video explainer generated \
from a fact-check report. Watch the attached recording and compare it against the ground-truth fact-check \
data below. Be strict: this explainer will be shown to the public, so anything inaccurate, unfair, \
unreadable, or incomplete must be caught.

Run exactly these checks and report pass/fail with a short note for each:
- claims_and_verdicts_match: every number, confidence, verdict, and attribution tag (when present) shown \
in the video matches the ground-truth data exactly (no rounding errors, no changed verdicts, no invented \
statistics).
- no_missing_or_misrepresented_claims: every claim listed in the ground-truth data appears in the video \
(or, if claims were capped, the video doesn't claim to show all of them) and none are paraphrased in a \
way that changes their meaning.
- overall_verdict_shown_correctly: the video's overall/title verdict and techniques match \
video_verdict exactly.
- language_fair_and_neutral: the wording is neutral and factual, not sensationalized, biased, or \
editorializing beyond what the ground-truth explanation says.
- text_readable: no text is cut off, overlapping, or disappears before a viewer could reasonably read it.
- sources_shown: the main sources from the ground-truth data are visibly listed somewhere in the video.

Then list every specific issue you found (empty list if none), each with:
- slide: which slide/card it's on (e.g. "Overall verdict", "Claim 2", "Sources")
- timestamp: approximate MM:SS in the recording where it appears
- description: exactly what is wrong and, if possible, what it should say instead

Set approved to true only if every check passed and the issues list is empty. Otherwise false.

Ground-truth fact-check data:
{data_json}"""

FIXER_PROMPT_TEMPLATE = """You previously generated the self-contained HTML explainer below. A strict \
critic reviewed a recording of it and found the following issues. Regenerate a complete, corrected \
version of the HTML page that fixes every issue while keeping the same overall design, structure, and \
output requirements (self-contained, auto-playing, 14-18 seconds total, dark theme, verdict colors, \
slide sequence) as the original. Keep it short — do not add slides or length while fixing issues.

Output ONLY the raw corrected HTML document, starting with <!DOCTYPE html>. No markdown, no code fences, \
no commentary.

Issues to fix:
{issues_json}

Ground-truth fact-check data (for re-verifying anything you change):
{data_json}

Current HTML to fix:
{current_html}"""

AGENT_VERIFICATION_PROMPT_TEMPLATE = """You are running inside a sandboxed Linux environment with code \
execution, file management, and web access. Complete BOTH tasks below, then write one JSON summary file.

TASK 1 — Render a shareable video:
The file /workspace/explainer.html is a self-contained, auto-playing HTML animation (pure CSS/JS, no \
build step). Render it to a shareable MP4:
1. Install what you need: `pip install playwright && playwright install --with-deps chromium`. Check \
whether ffmpeg is already available with `which ffmpeg` before trying to install it (e.g. \
`apt-get update && apt-get install -y ffmpeg` if missing).
2. Use Playwright to open /workspace/explainer.html headless at 960x540 and record one full playthrough \
(about 25-30 seconds) using Playwright's built-in video recording (record_video_dir).
3. Convert the resulting .webm to /workspace/explainer.mp4 with ffmpeg \
(e.g. `ffmpeg -y -i input.webm -c:v libx264 -pix_fmt yuv420p /workspace/explainer.mp4`).
4. Confirm /workspace/explainer.mp4 exists and is not 0 bytes.

TASK 2 — Verify sources:
Below is a numbered list of EXACTLY {num_sources} source citations used in a fact-check, each tied to a \
specific claim. You MUST attempt every single one — this list is short enough to do completely; do not \
skip, sample, or summarize a subset. For EACH one:
1. Fetch the URL with curl or Python requests, following redirects, using a realistic browser User-Agent \
header (e.g. "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"). If a plain request is \
blocked, you may try once more before concluding it's blocked.
2. Classify it as exactly one of:
   - "broken": the resource genuinely does not exist — HTTP 404, DNS failure, connection refused, or a \
redirect that lands on a generic "page not found".
   - "blocked": the request was refused by access control, not because the content is missing — HTTP \
401/403/406/429, a paywall, login wall, CAPTCHA, or bot-detection page. (A site returning 406/403 to a \
non-browser request is "blocked", not "broken" — it most likely works fine in a real browser. Do not \
mark these "broken".)
   - "unsupported": it loads successfully (2xx) but, after reading its content, does not actually \
support the specific claim it's cited for (claim_text is given for context).
   - "verified": it loads successfully (2xx) AND its content supports the claim.
3. Write one brief sentence of notes explaining the classification (for "blocked", mention the status \
code or block type you observed).

Sources to verify (exactly {num_sources}, numbered 1-{num_sources}):
{sources_json}

When both tasks are complete, write a JSON file to EXACTLY /workspace/result.json with this shape and \
nothing else in the file:
{{
  "video_rendered": true or false,
  "sources": [
    {{"claim_index": <int>, "url": "<the exact url given above>", "status": "verified" | "broken" | \
"blocked" | "unsupported", "notes": "<one brief sentence>"}}
  ]
}}
Before writing the file, COUNT your sources array and confirm it has exactly {num_sources} entries — one \
per source listed above, in the same order, with claim_index and url copied exactly. If you were unable \
to fully check one, still include your best-effort classification for it rather than omitting it. Do not \
add commentary outside the JSON file."""

_FILE_POLL_INTERVAL_SECONDS = 3
_FILE_POLL_TIMEOUT_SECONDS = 300
_INTERACTION_POLL_INTERVAL_SECONDS = 5
_EXTRACTION_TIMEOUT_SECONDS = 1200
_INVESTIGATION_TIMEOUT_SECONDS = 180
_JUDGE_TIMEOUT_SECONDS = 1200
_EXPLAINER_TIMEOUT_SECONDS = 1200
_CRITIC_TIMEOUT_SECONDS = 1200
_FIXER_TIMEOUT_SECONDS = 1200
_AGENT_TIMEOUT_SECONDS = 1800
_AGENT_POLL_INTERVAL_SECONDS = 10
_MAX_PARALLEL_INVESTIGATIONS = 8
_MAX_EXPLAINER_SOURCES = 4
_MAX_RENDER_CRITIQUE_ROUNDS = 2
_RENDER_WAIT_MS = 19000
_RENDER_VIEWPORT = {"width": 960, "height": 540}
_AGENT_WRITE_FILE_MARKER = "EOF_EXPLAINER_HTML_9f3a"


def _client() -> genai.Client:
    api_key = os.environ["GEMINI_API_KEY"]
    return genai.Client(api_key=api_key, http_options={"timeout": 1200000})


def _await_interaction(
    client: genai.Client,
    interaction,
    timeout_seconds: float,
    poll_interval_seconds: float = _INTERACTION_POLL_INTERVAL_SECONDS,
):
    deadline = time.time() + timeout_seconds
    while interaction.status in ("in_progress", "queued"):
        if time.time() > deadline:
            raise TimeoutError(f"Gemini call timed out after {timeout_seconds}s")
        time.sleep(poll_interval_seconds)
        interaction = client.interactions.get(interaction.id)

    if interaction.status != "completed":
        raise RuntimeError(f"Gemini call failed with status={interaction.status}: {interaction.error}")
    return interaction


def _strip_code_fence(raw: str, lang_prefix: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith(lang_prefix):
            raw = raw[len(lang_prefix) :]
        raw = raw.strip()
    return raw


def _parse_json_output(interaction) -> dict:
    return json.loads(_strip_code_fence(interaction.output_text, "json"))


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
        generation_config={"thinking_level": "low"},
        background=True,
    )
    interaction = _await_interaction(client, interaction, _EXTRACTION_TIMEOUT_SECONDS)
    return ClaimExtractionResult.model_validate(_parse_json_output(interaction))


def _merge_claims(extracted: list[ExtractedClaim]) -> list[Claim]:
    """Merge occurrences of the exact same claim into one Claim with multiple timestamps."""
    merged: list[Claim] = []
    index_by_wording: dict[str, int] = {}
    for item in extracted:
        key = item.exact_wording.strip().lower()
        if key in index_by_wording:
            merged[index_by_wording[key]].timestamps.append(item.timestamp)
        else:
            index_by_wording[key] = len(merged)
            merged.append(
                Claim(
                    speaker=item.speaker,
                    timestamps=[item.timestamp],
                    exact_wording=item.exact_wording,
                    claim_type=item.claim_type,
                )
            )
    return merged


def _investigate_claim(client: genai.Client, claim: Claim) -> Finding:
    repeat_note = (
        f"\nThis exact claim appears {len(claim.timestamps)} times in the video."
        if len(claim.timestamps) > 1
        else ""
    )
    prompt = INVESTIGATOR_PROMPT_TEMPLATE.format(
        exact_wording=claim.exact_wording,
        speaker=claim.speaker,
        claim_type=claim.claim_type,
        timestamps=", ".join(claim.timestamps),
        repeat_note=repeat_note,
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
        generation_config={"thinking_level": "low"},
    )
    interaction = _await_interaction(client, interaction, _INVESTIGATION_TIMEOUT_SECONDS)
    return Finding.model_validate(_parse_json_output(interaction))


def _judge_claims(
    client: genai.Client,
    claims: list[Claim],
    findings: list[Finding],
    editing_signals: list[EditingSignal],
) -> JudgeResult:
    claims_and_findings = [
        {
            "claim_index": i,
            "speaker": claim.speaker,
            "timestamps": claim.timestamps,
            "occurrence_count": len(claim.timestamps),
            "claim_type": claim.claim_type,
            "exact_wording": claim.exact_wording,
            "investigator_summary": finding.summary,
            "investigator_sources": [s.model_dump() for s in finding.sources],
        }
        for i, (claim, finding) in enumerate(zip(claims, findings))
    ]
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        editing_signals_json=json.dumps([s.model_dump() for s in editing_signals], indent=2),
        claims_and_findings_json=json.dumps(claims_and_findings, indent=2),
    )
    interaction = client.interactions.create(
        model=JUDGE_MODEL,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": JudgeResult.model_json_schema(),
        },
        generation_config={"thinking_level": "medium"},
        background=True,
    )
    interaction = _await_interaction(client, interaction, _JUDGE_TIMEOUT_SECONDS)
    result = JudgeResult.model_validate(_parse_json_output(interaction))

    # Real sources only: drop any cited URL that isn't verbatim in that claim's own investigator
    # findings, closing the door on the model citing a URL from memory or from another claim.
    for verdict in result.verdicts:
        finding = findings[verdict.claim_index] if verdict.claim_index < len(findings) else None
        allowed_urls = {s.url for s in finding.sources} if finding else set()
        verdict.sources = [s for s in verdict.sources if s.url in allowed_urls]

    # Safety net for the "never false/misleading without a source" rule — re-checked AFTER the
    # filter above, since stripping a fabricated URL can leave a false/misleading verdict bare.
    for verdict in result.verdicts:
        if verdict.verdict in ("false", "misleading") and not verdict.sources:
            verdict.verdict = "unverifiable"
            verdict.misleading_technique = None

    return result


def _build_explainer_data(claims: list[Claim], judge_result: JudgeResult) -> dict:
    verdict_by_index = {v.claim_index: v for v in judge_result.verdicts}
    claims_payload = []
    for i, claim in enumerate(claims):
        verdict = verdict_by_index.get(i)
        if verdict is None:
            continue
        claims_payload.append(
            {
                "exact_wording": claim.exact_wording,
                "timestamps": claim.timestamps,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "misleading_technique": verdict.misleading_technique,
                "attribution": verdict.attribution,
                "explanation": verdict.explanation,
                "sources": [s.model_dump() for s in verdict.sources],
            }
        )

    seen_urls: set[str] = set()
    main_sources = []
    for verdict in judge_result.verdicts:
        for source in verdict.sources:
            if source.url not in seen_urls:
                seen_urls.add(source.url)
                main_sources.append(source.model_dump())
    main_sources = main_sources[:_MAX_EXPLAINER_SOURCES]

    return {
        "video_verdict": judge_result.video_verdict.model_dump(),
        "claims": claims_payload,
        "what_actually_happened": judge_result.what_actually_happened,
        "main_sources": main_sources,
    }


def _generate_explainer_html(client: genai.Client, claims: list[Claim], judge_result: JudgeResult) -> str:
    data = _build_explainer_data(claims, judge_result)
    prompt = EXPLAINER_PROMPT_TEMPLATE.format(data_json=json.dumps(data, indent=2))
    interaction = client.interactions.create(
        model=EXPLAINER_MODEL,
        input=prompt,
        generation_config={"thinking_level": "low"},
        background=True,
    )
    interaction = _await_interaction(client, interaction, _EXPLAINER_TIMEOUT_SECONDS)
    return _strip_code_fence(interaction.output_text, "html")


def _render_explainer_video(html_path: str, video_dir: str) -> str:
    """Render an explainer HTML file in headless Chromium and record one playthrough."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=_RENDER_VIEWPORT,
            record_video_dir=video_dir,
            record_video_size=_RENDER_VIEWPORT,
        )
        page = context.new_page()
        page.goto(f"file://{Path(html_path).resolve()}")
        page.wait_for_timeout(_RENDER_WAIT_MS)
        context.close()
        browser.close()

    videos = sorted(Path(video_dir).glob("*.webm"), key=lambda p: p.stat().st_mtime)
    if not videos:
        raise RuntimeError("Playwright did not produce a video recording of the explainer")
    return str(videos[-1])


def _critique_explainer(
    client: genai.Client,
    video_path: str,
    claims: list[Claim],
    judge_result: JudgeResult,
) -> Critique:
    data = _build_explainer_data(claims, judge_result)
    uploaded = client.files.upload(file=video_path)
    uploaded = _await_file_active(client, uploaded)
    prompt = CRITIC_PROMPT_TEMPLATE.format(data_json=json.dumps(data, indent=2))
    interaction = client.interactions.create(
        model=CRITIC_MODEL,
        input=[
            {"type": "text", "text": prompt},
            {"type": "video", "uri": uploaded.uri, "mime_type": uploaded.mime_type},
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Critique.model_json_schema(),
        },
        generation_config={"thinking_level": "medium"},
        background=True,
    )
    interaction = _await_interaction(client, interaction, _CRITIC_TIMEOUT_SECONDS)
    return Critique.model_validate(_parse_json_output(interaction))


def _fix_explainer(
    client: genai.Client,
    current_html: str,
    critique: Critique,
    claims: list[Claim],
    judge_result: JudgeResult,
) -> str:
    data = _build_explainer_data(claims, judge_result)
    prompt = FIXER_PROMPT_TEMPLATE.format(
        issues_json=json.dumps([i.model_dump() for i in critique.issues], indent=2),
        data_json=json.dumps(data, indent=2),
        current_html=current_html,
    )
    interaction = client.interactions.create(
        model=FIXER_MODEL,
        input=prompt,
        generation_config={"thinking_level": "low"},
        background=True,
    )
    interaction = _await_interaction(client, interaction, _FIXER_TIMEOUT_SECONDS)
    return _strip_code_fence(interaction.output_text, "html")


def _run_render_critique_fix(
    client: genai.Client,
    explainer_dir: Path,
    claims: list[Claim],
    judge_result: JudgeResult,
    initial_html: str,
) -> Iterator[dict]:
    """Render, critique, and fix an explainer for up to _MAX_RENDER_CRITIQUE_ROUNDS rounds.

    Writes each version to explainer_dir/v{n}.html and yields progress events, ending with a
    'loop_done' event carrying every version's filename, approval, checks, and issues.
    """
    explainer_dir.mkdir(parents=True, exist_ok=True)
    html = initial_html
    versions: list[dict] = []
    version = 1

    while True:
        filename = f"v{version}.html"
        (explainer_dir / filename).write_text(html, encoding="utf-8")

        yield {"stage": "rendering", "version": version}
        with tempfile.TemporaryDirectory() as video_dir:
            video_path = _render_explainer_video(str(explainer_dir / filename), video_dir)

            yield {"stage": "critiquing", "version": version}
            critique = _critique_explainer(client, video_path, claims, judge_result)

        checks = [c.model_dump() for c in critique.checks]
        issues = [i.model_dump() for i in critique.issues]
        version_summary = {
            "version": version,
            "filename": filename,
            "approved": critique.approved,
            "checks": checks,
            "issues": issues,
        }
        versions.append(version_summary)
        yield {"stage": "critique_result", **version_summary}

        if critique.approved or version >= _MAX_RENDER_CRITIQUE_ROUNDS:
            break

        yield {"stage": "fixing", "from_version": version, "to_version": version + 1}
        html = _fix_explainer(client, html, critique, claims, judge_result)
        version += 1

    yield {"stage": "loop_done", "versions": versions}


def _build_agent_sources_payload(claims: list[Claim], verdicts: list[Verdict]) -> list[dict]:
    payload = []
    for verdict in verdicts:
        claim = claims[verdict.claim_index] if verdict.claim_index < len(claims) else None
        claim_text = claim.exact_wording if claim else ""
        for source in verdict.sources:
            payload.append(
                {
                    "claim_index": verdict.claim_index,
                    "claim_text": claim_text,
                    "url": source.url,
                    "title": source.title,
                }
            )
    return payload


def run_verification_agent(
    html_path: str,
    video_output_path: str,
    claims: list[Claim],
    verdicts: list[Verdict],
) -> dict:
    """Run the antigravity managed agent to render a shareable MP4 and verify every cited source.

    Saves the MP4 to video_output_path if rendering succeeds. Returns
    {"video_saved": bool, "sources": [{"claim_index", "url", "title", "status", "notes"}, ...]}.
    """
    client = _client()
    html = Path(html_path).read_text(encoding="utf-8")
    sources_payload = _build_agent_sources_payload(claims, verdicts)

    write_file_cmd = (
        f"mkdir -p /workspace && cat > /workspace/explainer.html << '{_AGENT_WRITE_FILE_MARKER}'\n"
        f"{html}\n{_AGENT_WRITE_FILE_MARKER}\n"
    )
    prompt = (
        "First, run this exact bash command to create the input file (do not modify its contents):\n\n"
        + write_file_cmd
        + "\n\n"
        + AGENT_VERIFICATION_PROMPT_TEMPLATE.format(
            num_sources=len(sources_payload), sources_json=json.dumps(sources_payload, indent=2)
        )
    )

    interaction = client.interactions.create(
        agent=AGENT,
        agent_config={"type": "antigravity", "model": AGENT_UNDERLYING_MODEL},
        environment="remote",
        input=prompt,
        background=True,
    )
    interaction = _await_interaction(
        client, interaction, _AGENT_TIMEOUT_SECONDS, poll_interval_seconds=_AGENT_POLL_INTERVAL_SECONDS
    )
    env_id = interaction.environment_id

    result_bytes = client.environments.files.download(environment=env_id, path="/workspace/result.json")
    result = json.loads(result_bytes)

    video_saved = False
    if result.get("video_rendered"):
        try:
            video_bytes = client.environments.files.download(environment=env_id, path="/workspace/explainer.mp4")
            Path(video_output_path).write_bytes(video_bytes)
            video_saved = True
        except Exception:  # noqa: BLE001
            video_saved = False

    status_by_key = {(s.get("claim_index"), s.get("url")): s for s in result.get("sources", [])}
    source_verifications = []
    for item in sources_payload:
        key = (item["claim_index"], item["url"])
        matched = status_by_key.get(key)
        source_verifications.append(
            {
                "claim_index": item["claim_index"],
                "url": item["url"],
                "title": item["title"],
                "status": matched["status"] if matched else "not_checked",
                "notes": matched.get("notes", "")
                if matched
                else "The agent did not report a result for this source.",
            }
        )

    return {"video_saved": video_saved, "sources": source_verifications}


def run_pipeline(
    youtube_url: str | None = None,
    file_path: str | None = None,
    explainer_dir: Path | None = None,
) -> Iterator[dict]:
    client = _client()

    yield {"stage": "extracting"}
    if youtube_url:
        video_content = {"type": "video", "uri": youtube_url}
    else:
        uploaded = client.files.upload(file=file_path)
        uploaded = _await_file_active(client, uploaded)
        video_content = {"type": "video", "uri": uploaded.uri, "mime_type": uploaded.mime_type}

    extraction = _extract_claims(client, video_content)
    claims = _merge_claims(extraction.claims)
    yield {"stage": "claims_extracted", "claims": [c.model_dump() for c in claims]}

    if not claims:
        yield {
            "stage": "done",
            "result": {
                "video_verdict": {
                    "verdict": "accurate",
                    "techniques": [],
                    "explanation": "No checkable factual claims were found in this video.",
                },
                "verdicts": [],
                "what_actually_happened": "No checkable factual claims were found in this video.",
                "versions": [],
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
    judge_result = _judge_claims(client, claims, findings, extraction.editing_signals)
    yield {"stage": "judged", "result": judge_result.model_dump()}

    yield {"stage": "generating_explainer"}
    explainer_html = _generate_explainer_html(client, claims, judge_result)
    yield {"stage": "explainer_generated"}

    versions: list[dict] = []
    if explainer_dir is not None:
        for event in _run_render_critique_fix(client, explainer_dir, claims, judge_result, explainer_html):
            if event["stage"] == "loop_done":
                versions = event["versions"]
            else:
                yield event

    yield {"stage": "done", "result": {**judge_result.model_dump(), "versions": versions}}
