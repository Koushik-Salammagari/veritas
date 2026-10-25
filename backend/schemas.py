from typing import Literal

from pydantic import BaseModel, Field

ClaimType = Literal["statistic", "event", "quote", "other"]


class Claim(BaseModel):
    speaker: str = Field(description="Who made the claim, e.g. a name or role shown/heard in the video")
    timestamp: str = Field(description="Timestamp in MM:SS format marking where the claim occurs")
    exact_wording: str = Field(description="The claim transcribed verbatim, not paraphrased")
    claim_type: ClaimType = Field(description="One of: statistic, event, quote, other")


class ClaimExtractionResult(BaseModel):
    claims: list[Claim]


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


class Verdict(BaseModel):
    claim_index: int = Field(description="Index of the claim this verdict is for, matching the input order")
    verdict: VerdictLabel
    confidence: float = Field(ge=0, le=1, description="Confidence in this verdict, from 0 to 1")
    misleading_technique: MisleadingTechnique | None = Field(
        default=None, description="Set only when verdict is 'misleading', otherwise null"
    )
    explanation: str = Field(description="Exactly one sentence explaining the verdict")
    sources: list[Source] = Field(description="Sources supporting this verdict; required for 'false' or 'misleading'")


class JudgeResult(BaseModel):
    verdicts: list[Verdict]
    what_actually_happened: str = Field(
        description="One paragraph explaining what is actually true about the video's overall topic"
    )
