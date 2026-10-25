from typing import Literal

from pydantic import BaseModel, Field

ClaimType = Literal["statistic", "event", "quote", "other"]


class ExtractedClaim(BaseModel):
    """One occurrence of a claim exactly as the extractor saw it (pre-merge)."""

    speaker: str = Field(description="Who made the claim, e.g. a name or role shown/heard in the video")
    timestamp: str = Field(description="Timestamp in MM:SS format marking where the claim occurs")
    exact_wording: str = Field(description="The claim transcribed verbatim, not paraphrased")
    claim_type: ClaimType = Field(description="One of: statistic, event, quote, other")


class EditingSignal(BaseModel):
    timestamp: str = Field(description="Timestamp in MM:SS format, or a MM:SS-MM:SS range")
    description: str = Field(
        description="What the sign of editing is, e.g. a cut, a repeated segment, an overlay, or a caption"
    )


class ClaimExtractionResult(BaseModel):
    claims: list[ExtractedClaim]
    editing_signals: list[EditingSignal] = Field(
        default_factory=list,
        description="Signs of editing noticed while watching: cuts, repeated segments, overlays, captions",
    )


class Claim(BaseModel):
    """A claim after merging duplicate occurrences from the extraction step."""

    speaker: str
    timestamps: list[str] = Field(description="All timestamps (MM:SS) where this exact claim occurs, in order")
    exact_wording: str
    claim_type: ClaimType


class Source(BaseModel):
    title: str = Field(description="Title of the source page or article")
    url: str = Field(description="Exact URL of the source")


class Finding(BaseModel):
    summary: str = Field(description="2-4 sentences on what the evidence shows about this claim")
    sources: list[Source] = Field(description="Sources found via search; empty if nothing reliable was found")


VerdictLabel = Literal["true", "misleading", "false", "unverifiable"]
MisleadingTechnique = Literal[
    "out of context", "old footage", "cherry-picked number", "missing context", "fabricated"
]
AttributionLabel = Literal["accurate", "inaccurate"]


class Verdict(BaseModel):
    claim_index: int = Field(description="Index of the claim this verdict is for, matching the input order")
    verdict: VerdictLabel = Field(
        description="Verdict on the SUBSTANCE of the claim (whether the underlying assertion is true), "
        "not on whether an attributed speaker actually said it"
    )
    confidence: float = Field(ge=0, le=1, description="Confidence in this verdict, from 0 to 1")
    misleading_technique: MisleadingTechnique | None = Field(
        default=None, description="Set only when verdict is 'misleading', otherwise null"
    )
    attribution: AttributionLabel | None = Field(
        default=None,
        description="For claims that report what someone said/claimed/wrote: whether that attribution "
        "itself is accurate (they really said it) or inaccurate (misquoted, fabricated, misattributed). "
        "Null for claims that are not reporting someone else's speech.",
    )
    explanation: str = Field(description="Exactly one sentence explaining the verdict")
    sources: list[Source] = Field(description="Sources supporting this verdict; required for 'false' or 'misleading'")


VideoVerdictLabel = Literal["accurate", "misleading", "false"]
VideoEditingTechnique = Literal[
    "repeated or spliced segments",
    "old footage presented as new",
    "missing context",
    "misleading title or caption",
    "cherry-picked clips",
]


class VideoVerdict(BaseModel):
    verdict: VideoVerdictLabel
    techniques: list[VideoEditingTechnique] = Field(
        default_factory=list, description="Video-level editing techniques used; empty if verdict is 'accurate'"
    )
    explanation: str = Field(description="Short explanation (1-3 sentences) of the overall video verdict")


class JudgeResult(BaseModel):
    video_verdict: VideoVerdict
    verdicts: list[Verdict]
    what_actually_happened: str = Field(
        description="One paragraph explaining what is actually true about the video's overall topic"
    )


CritiqueCheckName = Literal[
    "claims_and_verdicts_match",
    "no_missing_or_misrepresented_claims",
    "overall_verdict_shown_correctly",
    "language_fair_and_neutral",
    "text_readable",
    "sources_shown",
]


class CritiqueCheckResult(BaseModel):
    check: CritiqueCheckName
    passed: bool
    notes: str = Field(description="Brief justification for the pass/fail")


class CritiqueIssue(BaseModel):
    slide: str = Field(description="Which slide or card the issue is on, e.g. 'Overall verdict' or 'Claim 2'")
    timestamp: str = Field(description="Approximate MM:SS in the recording where the issue appears")
    description: str = Field(description="Specific description of what is wrong and how to fix it")


class Critique(BaseModel):
    checks: list[CritiqueCheckResult]
    issues: list[CritiqueIssue]
    approved: bool = Field(description="True only if every check passed and issues is empty")


SourceVerificationStatus = Literal["verified", "broken", "unsupported"]


class SourceVerification(BaseModel):
    claim_index: int
    url: str
    title: str
    status: SourceVerificationStatus = Field(
        description="'verified': loads and supports the claim. 'broken': doesn't load. "
        "'unsupported': loads but content doesn't support the claim."
    )
    notes: str = Field(description="One brief sentence explaining the status")


class AgentTaskResult(BaseModel):
    video_url: str | None = Field(default=None, description="URL to download the rendered MP4, if rendering succeeded")
    source_verifications: list[SourceVerification] = Field(default_factory=list)
