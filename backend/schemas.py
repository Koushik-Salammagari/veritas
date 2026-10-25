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
