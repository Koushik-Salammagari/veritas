# Veritas

**Gemini gives you an opinion. Veritas runs an investigation, then shows you the truth.**

Built at the Gemini 4 Argon SF Hackathon, October 25, 2026.
Problem statement: **Two, More Dimensions** (long video understanding plus a render, watch, critique, fix loop).

> Note: everything in this repository was written during the event. This README holds the plan and notes prepared beforehand, as allowed by the organizers.

---

## The problem

I see a lot of misinformation in posts and videos, and I often can't figure out what's actually true. Most people don't have the time or tools to check what they watch, so convincing but misleading videos shape what millions of people believe.

## What Veritas does

1. You give it a video (YouTube link or upload).
2. Gemini 4 Argon watches it and pulls out every factual claim, with speaker and timestamp.
3. An investigator agent checks each claim against trusted sources.
4. A judge turns the evidence into claim-by-claim verdicts: **true, misleading, false or unverifiable**, with how it misleads and what actually happened.
5. Veritas **generates a short visual explainer** of the truth.
6. Veritas **renders the explainer, watches it, critiques it against the evidence and fixes it**, in a loop, until it is accurate, fair and clear.

## Why this fits Problem Statement Two

- **Long video understanding:** Argon watches the full video, including speech, on-screen text and visuals.
- **Render, watch, critique, fix:** the explainer is generated, rendered, watched by Argon, checked against the goal and evidence, and improved over several rounds.

## Argon capabilities used

| Capability | Where |
|---|---|
| Long video understanding | Claim extraction; watching the rendered explainer |
| Frontier reasoning | Judge and critique steps |
| Search grounding | Investigator agent finding sources |
| Long output | Generating the full explainer in one pass |
| Managed Agents | Investigator runs as a managed agent in its own sandbox |

## Architecture

1. **Input:** YouTube link or video upload.
2. **Claim extractor (Argon):** returns a structured list of claims with speaker, timestamp and claim type.
3. **Investigator (Managed Agent, coverage):** for each claim, finds how trusted sources reported it, returns findings plus source links.
4. **Judge (Argon):** verdict per claim, the misleading technique (cropped clip, old footage, cherry-picked number, missing context), and a plain-language "what actually happened."
5. **Explainer generator (Argon):** produces a self-contained web page with a short animated explainer of the verdicts.
6. **Render:** a headless browser records the explainer as a short video or set of screenshots.
7. **Critic (Argon):** watches the render and scores it against a checklist: accurate to the evidence, fair, readable, every claim covered, sources shown. Lists concrete fixes.
8. **Fixer (Argon):** applies the fixes and regenerates. Repeat steps 6 to 8 up to 3 rounds.
9. **Frontend:** shows the agents working live, the verdicts, and each explainer version with what the critic caught.

## Scope for today

**Must have (the core):** video in, claims, judge verdicts, explainer, at least one visible critique-and-fix round.
**Nice to have:** investigator as a Managed Agent, live agent progress view, before/after explainer comparison.
**Cut first if short on time:** the investigator agent (let the judge use search grounding directly).
**Later, after the hackathon:** data agent that recomputes statistics, context agent that finds original footage, knowledge graph of claims and public figures, mobile share sheet.

Do not build: a Streamlit app, or a screen where a dashboard is the main feature (both are on the avoid list).

## Timeline

| Time | Goal |
|---|---|
| 10:30 to 11:30 | Project set up; Argon watches one video and lists claims |
| 11:30 to 1:00 | Investigator plus judge produce verdicts |
| 1:00 to 2:30 | Explainer generation |
| 2:30 to 3:30 | Render, watch, critique, fix loop |
| 3:30 to 4:30 | Frontend polish; test with all demo videos |
| 4:30 to 5:00 | Record 1-minute demo video; submit; repo public |

Rule: if a step runs 30 minutes over, cut scope and move on.

## Claude Code prompts (use in order)

Paste each one when starting that stage. Keep the API key in an environment variable; never paste it into a prompt.

1. **Setup:** "Create a new web app for Veritas. Use a simple stack you can scaffold fast (not Streamlit). Set up the Gemini API using the model gemini-4-argon, with the API key read from an environment variable. Make a page where I can paste a YouTube link or upload a video."
2. **Claim extraction:** "Send the video to gemini-4-argon and ask it to return structured output: a list of factual claims, each with speaker, timestamp, exact wording, and claim type (statistic, event, quote, other). Ignore opinions. Show the list on the page."
3. **Investigator:** "For each claim, run an investigation using Gemini with Google Search grounding (or a Managed Agent if available in the DeepMind resources). Return what trusted sources say and the source links. Run claims in parallel and show live status for each one."
4. **Judge:** "Send all claims and findings to gemini-4-argon. For each claim return a verdict (true, misleading, false, unverifiable), confidence, the misleading technique if any, a one-sentence explanation, and sources. Also return a short paragraph on what actually happened. Never mark a claim false without a source; use unverifiable when evidence is weak."
5. **Explainer:** "Have gemini-4-argon generate one self-contained HTML page that works as a 20 to 30 second animated explainer of the verdicts: the claim, the verdict, what actually happened, and sources. Save each version."
6. **Render and critique loop:** "Render the explainer in a headless browser and record it as a video or screenshots. Send the recording plus the verdicts to gemini-4-argon as a critic: score accuracy against the evidence, fairness, readability, and coverage of every claim, and list specific fixes. Then have it regenerate the explainer with the fixes. Repeat up to 3 rounds or until the critic approves. Show every version and the critic's notes in the UI."
7. **Polish:** "Make the results screen clear for a live demo: the video with claim markers, verdict cards, and the explainer versions side by side with what changed."

## Demo plan (3 minutes, no slides)

- **0:00 to 0:30:** The user and problem: "You see a viral video and can't tell if it's true."
- **0:30 to 1:45:** Paste a misleading video live. Show claims appearing, the investigation running, verdicts landing.
- **1:45 to 2:30:** Show the explainer loop: version 1, the critic catching a mistake, the fixed version.
- **2:30 to 3:00:** "Gemini gives you an opinion. Veritas runs an investigation." Then what's next: recomputing statistics, finding original footage, a knowledge graph of claims.

Always have one pre-run result ready in case the live run is slow.

## Demo videos (prepare tonight)

Pick 3 to 5 videos where you already know the truth:
- One clearly false
- One misleading but real (out of context)
- One true (shows Veritas doesn't call everything fake)

For each, write down: the claims, the truth, the best sources.

## Checklist before leaving home

- Government-issued photo ID
- Laptop, charger, extension cord
- Gemini API key set up (check the participant guide for DeepMind resources or credits)
- Demo video links saved
- This README
- Claude Code working on the laptop

## Open questions to check at the event

- Does gemini-4-argon accept YouTube links directly, or do videos need uploading?
- Are Managed Agents available on gemini-4-argon, or only on Flash models?
- Any DeepMind credits or special access for participants?
