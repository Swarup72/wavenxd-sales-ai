from pydantic import BaseModel, Field, field_validator

from app.domain.enums import ProductMatchStatus


class CustomerRequirements(BaseModel):
    industry: str | None = Field(default=None, max_length=200)
    application: str | None = Field(default=None, max_length=200)
    fluid_description: str | None = Field(default=None, max_length=500)
    viscosity_cp: float | None = Field(default=None, gt=0)
    flow_rate_ml_min: float | None = Field(default=None, gt=0)
    droplet_size_um: float | None = Field(default=None, gt=0)
    spray_pattern: str | None = Field(default=None, max_length=100)
    feed_configuration: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    unresolved_questions: list[str] = Field(default_factory=list)

    @field_validator("industry", "application", "fluid_description", "spray_pattern", "feed_configuration", "notes")
    @classmethod
    def clean_strings(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None

    @field_validator("unresolved_questions")
    @classmethod
    def clean_questions(cls, values: list[str]) -> list[str]:
        return [q.strip() for q in values if q and q.strip()]


class CandidateEvaluation(BaseModel):
    product_id: str
    catalog_key: str | None = None
    product_name: str
    category: str | None = None
    status: ProductMatchStatus
    is_confirmed_recommendation: bool
    technical_review_required: bool
    reasons: list[str] = Field(default_factory=list)
    limitations_and_gaps: list[str] = Field(default_factory=list)
    clarifications_required: list[str] = Field(default_factory=list)
    ranking_score: int = 0
    ranking_explanation: str | None = None


class RecommendationResult(BaseModel):
    overall_outcome: ProductMatchStatus
    candidate_evaluations: list[CandidateEvaluation] = Field(default_factory=list)
    confirmed_recommendations: list[CandidateEvaluation] = Field(default_factory=list)
    potential_matches: list[CandidateEvaluation] = Field(default_factory=list)
    unmatched_candidates: list[CandidateEvaluation] = Field(default_factory=list)
    summary_reasons: list[str] = Field(default_factory=list)
    specification_gaps: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    technical_review_required: bool = False
    requirements: CustomerRequirements | None = None
    extracted_requirements: CustomerRequirements | None = None
    recommended_product: CandidateEvaluation | None = None
