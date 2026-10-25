# Veritas

**Gemini gives you an opinion. Veritas runs an investigation, then shows you the truth.**

Built in a single day at the Gemini hackathon, October 25, 2026 — everything in this repository, every prompt, every line of the pipeline and every pixel of the UI, was written during the event.

## The problem

Misleading and out-of-context videos shape what millions of people believe, and most viewers have neither the time nor the tools to check what they're watching. A video can quote someone accurately and still be a lie, by splicing in old footage, cutting context, or burying a false claim inside a technically-true sentence. Spotting that takes real investigative work — exactly the kind of multi-step, evidence-grounded task a frontier model with search and video understanding is suited for.

## What Veritas does

1. You give it a video — a YouTube link or an upload.
2. Gemini watches the whole thing and pulls out every checkable factual claim, with speaker and timestamp.
3. A pool of investigator agents researches each claim in parallel using Google Search grounding.
4. A judge turns the evidence into a verdict per claim — **true, misleading, false, or unverifiable** — plus an overall video verdict, the misleading techniques used, and a plain-language account of what actually happened.
5. Gemini writes a short, natural-language **narration script** for a shareable explainer and a text-to-speech model voices it.
6. Veritas **renders the explainer, watches it, critiques it against the evidence, and fixes it** — in a loop — until a strict critic approves it.
7. A managed agent, running in its own sandboxed environment, renders a shareable MP4 of the approved explainer and independently re-verifies every cited source.

The whole run streams live to the browser — a pipeline trace shows each investigator, the judge, the explainer writer, the critic, and the managed agent working in real time — and every run is saved so it can be replayed later at its original pace or sped up.

## Why this fits Problem Statement Two

- **Long video understanding:** the extractor watches the full video — speech, on-screen text, and visuals — not a transcript, to catch claims made on screen as well as claims made aloud, and to notice editing signals (cuts, repeated segments, mismatched captions) a transcript alone would miss.
- **Render, watch, critique, fix:** the explainer isn't accepted on faith. It's rendered in a headless browser, the recording is handed back to Gemini as a strict critic that checks it against the ground-truth verdicts (accuracy, fairness, readability, narration-matches-evidence, pacing), and a fixer regenerates it against specific, cited issues — for up to two rounds, with every round and every critique visible in the UI.

## Architecture

```
video → claim extractor → investigators (parallel) → judge → narration + TTS
                                                                     ↓
                                              explainer writer → render → critic → fixer
                                                                     ↓ (approved)
                                                          managed agent: MP4 + source re-check
```

1. **Claim extractor** — watches the video once and returns a structured list of claims (speaker, timestamp, exact wording, claim type) plus any editing signals it notices.
2. **Investigators** — one per claim, run in parallel, each researching with Google Search grounding and returning a summary and sources.
3. **Judge** — reads every claim alongside its investigator's findings and decides a verdict, a confidence, the misleading technique (if any), and an overall video verdict — never marking a claim false or misleading without a source to back it, and never citing a URL that didn't actually come from that claim's search results.
4. **Narration + TTS** — a fixed, code-determined slide plan (overall verdict, up to three claims that drive the verdict, how it misleads, what actually happened, sources) gets a natural, conversational voiceover per segment, synthesized to real audio; each slide's on-screen time is driven by its segment's measured speech length.
5. **Explainer writer** — generates the slide content for a self-contained, auto-playing HTML explainer; a small deterministic harness (not the model) wires up slide timing, the audio, and the "play with narration" / mute controls, so LLM output only ever touches visual content, never playback logic.
6. **Render → critic → fixer loop** — a headless browser records one playthrough, a strict critic checks it against the ground-truth verdicts and the narration script, and a fixer regenerates just the slide content against the critic's specific issues. Repeats up to two rounds.
7. **Managed agent** — once a version is approved, a sandboxed agent independently renders the shareable MP4 and re-verifies every cited source by actually fetching it, classifying each as verified, broken, blocked, or not supporting the claim.

## Which model does what, and why

| Model | Role | Why this model |
|---|---|---|
| **gemini-4-argon** | Claim extraction, judging, narration script, explainer writing, critique, fixing | The reasoning-and-long-context work: watching a full video, weighing evidence fairly, writing natural prose, and self-critiquing against a checklist all need a frontier model, not a fast one. |
| **gemini-3.8-flash** | Investigators (one call per claim, with Google Search grounding) | Up to a dozen of these run in parallel per video; a fast, cheap model keeps the whole investigation phase quick without sacrificing search-grounded accuracy on a single, narrow claim. |
| **gemini-3.8-flash-tts** | Narration audio | A dedicated text-to-speech model producing a warm, natural narrator voice ("Sulafat") — a reasoning model isn't the right tool for synthesizing audio. |
| **antigravity managed agent** | Shareable MP4 rendering + independent source re-verification | This step needs a real sandboxed environment with code execution and live web access (installing Playwright and ffmpeg, fetching 20+ URLs with real HTTP requests) — a managed agent, not a single model call, is what that requires. |

## How to run it locally

```bash
git clone https://github.com/Koushik-Salammagari/veritas.git
cd veritas
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium

echo "GEMINI_API_KEY=your-key-here" > .env

.venv/bin/uvicorn backend.main:app --port 8000
```

Open `http://localhost:8000`, paste a YouTube link (or upload a video), and watch the investigation run live. Past runs are saved under `explainers/` and listed on the start screen, where any of them can be reloaded instantly or replayed at real pace or 4x.

## Next steps

- **Narrated shareable MP4** — the managed agent's MP4 is currently silent (rendering the narration audio into it hit a payload size limit under hackathon time pressure); muxing the narration track back in is the near-term fix.
- **Clip vs. original comparison** — show the exact source footage side by side with the clip as used, so "old footage presented as new" and similar techniques are visible, not just asserted.
- **Claims knowledge graph** — persist claims, verdicts, and sources across videos so recurring claims, repeat sources, and patterns across multiple videos from the same creator become queryable over time.
