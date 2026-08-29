# schemas.py
from pydantic import BaseModel, Field, field_validator

class SportsBettingReviewOutput(BaseModel):
    odds_analysis: str = Field(
        description="Conversion of odds (American/Decimal) to implied probability and vig/no-vig fair probability."
    )
    expected_value_assessment: str = Field(
        description="Calculation or evaluation of Expected Value (+EV / -EV) based on fair probability vs. market price."
    )
    bankroll_management_tip: str = Field(
        description="Staking advice based on unit sizing rules or Fractional Kelly Criterion."
    )
    analytical_guidance: str = Field(
        description="Handicapping advice, line shopping recommendations, model assumption checks, or closing line value (CLV) concepts."
    )

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = "sports_default_session"
    bankroll: float = Field(default=1000.0, gt=0, le=10_000_000)
    risk_profile: str = "Moderate"

    @field_validator("message")
    @classmethod
    def message_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain text")
        return value.strip()

    @field_validator("risk_profile")
    @classmethod
    def risk_profile_must_be_supported(cls, value: str) -> str:
        normalized = value.title()
        if normalized not in {"Conservative", "Moderate", "Aggressive"}:
            raise ValueError("risk_profile must be Conservative, Moderate, or Aggressive")
        return normalized

class ChatResponse(BaseModel):
    response: str
    intent: str
    thread_id: str