from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import LeadStage
from app.models.common import MongoModel, PyObjectId, utc_now


class Lead(MongoModel):
    customer_user_id: PyObjectId
    company_id: PyObjectId
    conversation_id: PyObjectId
    customer_name: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    industry: str | None = Field(default=None, max_length=200)
    application: str | None = Field(default=None, max_length=200)
    fluid_description: str | None = Field(default=None, max_length=500)
    viscosity_cp: float | None = Field(default=None, ge=0)
    viscosity_unit: str = Field(default="cP", max_length=20)
    flow_rate_ml_min: float | None = Field(default=None, ge=0)
    flow_rate_unit: str = Field(default="ml/min", max_length=20)
    droplet_size_um: float | None = Field(default=None, ge=0)
    droplet_size_unit: str = Field(default="µm", max_length=20)
    spray_pattern: str | None = Field(default=None, max_length=100)
    feed_configuration: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    internal_notes: str | None = Field(default=None, max_length=4000)
    recommended_product_ids: list[str] = Field(default_factory=list)
    recommendation_summary: str | None = Field(default=None, max_length=2000)
    lead_source: str = Field(default="customer_consultation", max_length=100)
    stage: LeadStage = Field(default=LeadStage.NEW)
    preferred_follow_up_at: datetime | None = None
    preferred_follow_up_timezone: str | None = Field(default=None, max_length=50)
    follow_up_notes: str | None = Field(default=None, max_length=2000)


class CreateLeadRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=50)
    customer_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)
    preferred_follow_up_at: datetime | None = None
    preferred_follow_up_timezone: str | None = Field(default=None, max_length=50)


class UpdateLeadStageRequest(BaseModel):
    stage: LeadStage | None = None
    notes: str | None = Field(default=None, max_length=4000)
    internal_notes: str | None = Field(default=None, max_length=4000)


class LeadResponse(BaseModel):
    id: str
    customer_user_id: str
    company_id: str
    conversation_id: str
    customer_name: str
    company_name: str
    email: str
    phone: str | None = None
    industry: str | None = None
    application: str | None = None
    fluid_description: str | None = None
    viscosity_cp: float | None = None
    viscosity_unit: str = "cP"
    flow_rate_ml_min: float | None = None
    flow_rate_unit: str = "ml/min"
    droplet_size_um: float | None = None
    droplet_size_unit: str = "µm"
    spray_pattern: str | None = None
    feed_configuration: str | None = None
    notes: str | None = None
    technical_notes: str | None = None
    internal_notes: str | None = None
    recommended_product_ids: list[str] = []
    recommendation_summary: str | None = None
    lead_source: str
    stage: LeadStage
    preferred_follow_up_at: str | None = None
    preferred_follow_up_timezone: str | None = None
    follow_up_notes: str | None = None
    created_at: str
    updated_at: str
