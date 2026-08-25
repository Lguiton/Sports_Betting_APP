# schemas.py
from pydantic import BaseModel, Field

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
    message: str
    thread_id: str = "sports_default_session"

class ChatResponse(BaseModel):
    response: str
    intent: str
    thread_id: str