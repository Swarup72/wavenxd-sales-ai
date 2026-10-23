from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.core.dependencies import (
    get_database,
    require_customer_user,
    validate_csrf,
)
from app.domain.enums import AccessRequestStatus, EmailDispatchStatus, FollowUpStatus, LeadStage
from app.models.common import utc_now
from app.models.conversation import (
    Conversation,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.models.lead import CreateLeadRequest, Lead, LeadResponse
from app.models.product import Product
from app.models.recommendation import CustomerRequirements, RecommendationResult
from app.models.user import User
from app.services.calendar_service import generate_google_calendar_url, generate_ics_calendar
from app.services.email_service import create_quotation_email_draft, simulate_email_delivery
from app.services.quotation_service import generate_quotation_data, generate_quotation_html
from app.services.authorization import (
    create_customer_access_request,
    list_accessible_products_for_user,
)
from app.services.conversation_service import (
    create_conversation,
    get_customer_conversation,
    list_customer_conversations,
    process_user_message,
)
from app.services.llm_provider import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProvider,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMServiceOverloadError,
    LLMTransientRateLimitError,
    get_llm_provider,
)
from app.services.recommendation_engine import evaluate_recommendations
from app.services.voice_service import (
    AudioValidationError,
    STTProvider,
    TTSProvider,
    TTSUnsupportedLanguageError,
    get_stt_provider,
    get_tts_provider,
    validate_audio_upload,
)

router = APIRouter(prefix="/customer", tags=["Customer Product Access"])


# --- Schemas ---

class ProductCustomerResponse(BaseModel):
    id: str
    name: str
    catalog_key: str | None = None
    category: str | None = None
    spray_pattern: str | None = None
    feed_configuration: str | None = None
    frequency_khz: float | None = None
    droplet_size_um: float | None = None
    flow_rate_max_ml_min: float | None = None
    flow_rate_description: str | None = None
    viscosity_max_cp: float | None = None
    viscosity_description: str | None = None
    applications: list[str] = []
    catalog_notes: str | None = None


class CreateCustomerAccessRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=50)
    reason: str | None = Field(default=None, max_length=2000)


class CustomerAccessRequestResponse(BaseModel):
    id: str
    product_id: str
    reason: str | None = None
    status: AccessRequestStatus
    review_note: str | None = None
    created_at: str
    updated_at: str
    message: str = "Access request submitted successfully"


def build_product_customer_response(p: Product) -> ProductCustomerResponse:
    return ProductCustomerResponse(
        id=str(p.id),
        name=p.name,
        catalog_key=p.catalog_key,
        category=p.category,
        spray_pattern=p.spray_pattern,
        feed_configuration=p.feed_configuration,
        frequency_khz=p.frequency_khz,
        droplet_size_um=p.droplet_size_um,
        flow_rate_max_ml_min=p.flow_rate_max_ml_min,
        flow_rate_description=p.flow_rate_description,
        viscosity_max_cp=p.viscosity_max_cp,
        viscosity_description=p.viscosity_description,
        applications=p.applications,
        catalog_notes=p.catalog_notes,
    )


# --- Endpoints ---

@router.get(
    "/products",
    response_model=list[ProductCustomerResponse],
    dependencies=[Depends(require_customer_user)],
    summary="List products assigned and available to customer's company",
)
async def list_customer_assigned_products(
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    products = await list_accessible_products_for_user(database, current_customer)
    return [build_product_customer_response(p) for p in products]


@router.post(
    "/access-requests",
    response_model=CustomerAccessRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Submit an access request for a product on behalf of customer's company",
)
async def submit_access_request(
    body: CreateCustomerAccessRequest,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    req = await create_customer_access_request(
        database=database,
        customer_user=current_customer,
        product_id=body.product_id,
        reason=body.reason,
    )
    return CustomerAccessRequestResponse(
        id=str(req.id),
        product_id=str(req.product_id),
        reason=req.reason,
        status=req.status,
        review_note=req.review_note,
        created_at=req.created_at.isoformat(),
        updated_at=req.updated_at.isoformat(),
        message="Access request submitted successfully",
    )


@router.get(
    "/access-requests",
    response_model=list[CustomerAccessRequestResponse],
    dependencies=[Depends(require_customer_user)],
    summary="List access requests submitted by customer's company",
)
async def list_customer_access_requests(
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    cursor = database.access_requests.find(
        {"company_id": current_customer.company_id}
    ).sort("created_at", -1)
    docs = await cursor.to_list(length=1000)

    return [
        CustomerAccessRequestResponse(
            id=str(d["_id"]),
            product_id=str(d["product_id"]),
            reason=d.get("reason"),
            status=d["status"],
            review_note=d.get("review_note"),
            created_at=d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"]),
            updated_at=d["updated_at"].isoformat() if hasattr(d["updated_at"], "isoformat") else str(d["updated_at"]),
            message="Retrieved access request",
        )
        for d in docs
    ]


@router.post(
    "/recommendations",
    response_model=RecommendationResult,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Evaluate deterministic product recommendations for authenticated customer's company",
)
async def get_customer_recommendations(
    requirements: CustomerRequirements,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    # Retrieve candidates strictly via existing authorization layer:
    # only active, published, verified products assigned to current customer's company
    candidate_products = await list_accessible_products_for_user(database, current_customer)
    return evaluate_recommendations(requirements, candidate_products)


def build_conversation_detail_response(
    conv: Conversation,
    rec_result: RecommendationResult | None = None,
) -> ConversationDetailResponse:
    return ConversationDetailResponse(
        id=str(conv.id),
        company_id=str(conv.company_id),
        user_id=str(conv.user_id),
        status=conv.status,
        title=conv.title,
        preferred_language=conv.preferred_language,
        requirements=conv.requirements,
        unresolved_questions=conv.unresolved_questions,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                input_modality=m.input_modality,
                language=m.language,
                created_at=m.created_at.isoformat(),
            )
            for m in conv.messages
        ],
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        recommendation_result=rec_result,
    )


def build_conversation_summary_response(conv: Conversation) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        id=str(conv.id),
        company_id=str(conv.company_id),
        user_id=str(conv.user_id),
        status=conv.status,
        title=conv.title,
        preferred_language=conv.preferred_language,
        message_count=len(conv.messages),
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.post(
    "/conversations",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Create a new conversation session",
)
async def create_new_conversation(
    body: CreateConversationRequest = CreateConversationRequest(),
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
    llm_provider: LLMProvider = Depends(get_llm_provider),
):
    conv = await create_conversation(
        database=database,
        customer_user=current_customer,
        title=body.title,
        preferred_language=body.preferred_language,
    )
    rec_result = None
    if body.initial_message and body.initial_message.strip():
        conv, _, _, rec_result = await process_user_message(
            database=database,
            customer_user=current_customer,
            conversation_id=conv.id,
            user_text=body.initial_message,
            llm_provider=llm_provider,
            explicit_language=body.preferred_language,
        )
    else:
        candidate_products = await list_accessible_products_for_user(database, current_customer)
        rec_result = evaluate_recommendations(conv.requirements, candidate_products)
    return build_conversation_detail_response(conv, rec_result=rec_result)


@router.get(
    "/conversations",
    response_model=list[ConversationSummaryResponse],
    dependencies=[Depends(require_customer_user)],
    summary="List customer's conversations",
)
async def list_conversations_endpoint(
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    convs = await list_customer_conversations(database, current_customer)
    return [build_conversation_summary_response(c) for c in convs]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    dependencies=[Depends(require_customer_user)],
    summary="Retrieve details and messages of a customer conversation",
)
async def get_conversation_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    conv = await get_customer_conversation(database, current_customer, conversation_id)
    candidate_products = await list_accessible_products_for_user(database, current_customer)
    rec_result = evaluate_recommendations(conv.requirements, candidate_products)
    return build_conversation_detail_response(conv, rec_result=rec_result)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageResponse,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Send a message to the AI sales assistant",
)
async def send_conversation_message(
    conversation_id: str,
    body: SendMessageRequest,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
    llm_provider: LLMProvider = Depends(get_llm_provider),
):
    conv, user_msg, assistant_msg, rec_result = await process_user_message(
        database=database,
        customer_user=current_customer,
        conversation_id=conversation_id,
        user_text=body.content,
        llm_provider=llm_provider,
        explicit_language=body.language,
    )
    return SendMessageResponse(
        conversation_id=str(conv.id),
        user_message=MessageResponse(
            id=user_msg.id,
            role=user_msg.role,
            content=user_msg.content,
            input_modality=user_msg.input_modality,
            language=user_msg.language,
            created_at=user_msg.created_at.isoformat(),
        ),
        assistant_message=MessageResponse(
            id=assistant_msg.id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            input_modality=assistant_msg.input_modality,
            language=assistant_msg.language,
            created_at=assistant_msg.created_at.isoformat(),
        ),
        updated_requirements=conv.requirements,
        unresolved_questions=conv.unresolved_questions,
        recommendation_result=rec_result,
    )


@router.post(
    "/conversations/{conversation_id}/voice-messages",
    response_model=SendMessageResponse,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Send a voice message to the AI sales assistant",
)
async def send_voice_message_endpoint(
    conversation_id: str,
    file: UploadFile = File(...),
    language: str | None = Form(None),
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
    llm_provider: LLMProvider = Depends(get_llm_provider),
    stt_provider: STTProvider = Depends(get_stt_provider),
):
    audio_bytes = await file.read()
    try:
        validate_audio_upload(
            filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(audio_bytes),
        )
    except AudioValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    try:
        transcript = await stt_provider.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=file.filename or "audio.wav",
            content_type=file.content_type or "audio/wav",
            language=language,
        )
    except (LLMTransientRateLimitError, LLMQuotaExhaustedError, LLMServiceOverloadError, LLMProviderUnavailableError, LLMAuthenticationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice input is temporarily unavailable due to transcription service limits. Please provide your requirement using text input.",
        ) from exc

    conv, user_msg, assistant_msg, rec_result = await process_user_message(
        database=database,
        customer_user=current_customer,
        conversation_id=conversation_id,
        user_text=transcript,
        llm_provider=llm_provider,
        input_modality="voice",
        explicit_language=language,
    )

    return SendMessageResponse(
        conversation_id=str(conv.id),
        user_message=MessageResponse(
            id=user_msg.id,
            role=user_msg.role,
            content=user_msg.content,
            input_modality=user_msg.input_modality,
            language=user_msg.language,
            created_at=user_msg.created_at.isoformat(),
        ),
        assistant_message=MessageResponse(
            id=assistant_msg.id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            input_modality=assistant_msg.input_modality,
            language=assistant_msg.language,
            created_at=assistant_msg.created_at.isoformat(),
        ),
        updated_requirements=conv.requirements,
        unresolved_questions=conv.unresolved_questions,
        recommendation_result=rec_result,
    )


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/speak",
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Synthesize speech audio from an assistant response",
)
async def speak_assistant_message(
    conversation_id: str,
    message_id: str,
    language: str | None = None,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
    tts_provider: TTSProvider = Depends(get_tts_provider),
):
    conv = await get_customer_conversation(database, current_customer, conversation_id)
    target_msg = None
    for m in conv.messages:
        if m.id == message_id:
            target_msg = m
            break

    if not target_msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if target_msg.role != "assistant":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speech synthesis is only permitted for assistant responses",
        )

    target_lang = language or target_msg.language or conv.preferred_language or "en"
    try:
        audio_bytes, media_type = await tts_provider.synthesize_speech(
            text=target_msg.content,
            language=target_lang,
        )
    except TTSUnsupportedLanguageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LLMQuotaExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech synthesis daily quota reached. Text responses remain fully available. Please switch to text-only mode.",
        ) from exc
    except LLMTransientRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech synthesis is temporarily rate limited. Text responses remain fully available. Please switch to text-only mode.",
        ) from exc
    except (LLMProviderUnavailableError, LLMServiceOverloadError, LLMAuthenticationError, LLMConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech synthesis is temporarily unavailable. Text responses remain fully available. Please switch to text-only mode.",
        ) from exc

    return Response(content=audio_bytes, media_type=media_type)


@router.post(
    "/conversations/{conversation_id}/recommendations",
    response_model=RecommendationResult,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Evaluate latest collected requirements in conversation against company's authorized products",
)
async def evaluate_conversation_recommendations_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    conv = await get_customer_conversation(database, current_customer, conversation_id)
    candidate_products = await list_accessible_products_for_user(database, current_customer)
    return evaluate_recommendations(conv.requirements, candidate_products)


# --- Leads & Follow-Up Schemas ---

class ScheduleFollowUpRequest(BaseModel):
    scheduled_at: datetime
    timezone: str = Field(default="UTC", max_length=50)
    duration_minutes: int = Field(default=30, ge=15, le=120)
    notes: str | None = Field(default=None, max_length=2000)


class ScheduleFollowUpResponse(BaseModel):
    conversation_id: str
    scheduled_at: str
    timezone: str
    duration_minutes: int
    notes: str | None = None
    google_calendar_url: str
    message: str = "Follow-up consultation invitation prepared successfully. Download the calendar file to add to your calendar."


def build_lead_response(lead: Lead) -> LeadResponse:
    return LeadResponse(
        id=str(lead.id),
        customer_user_id=str(lead.customer_user_id),
        company_id=str(lead.company_id),
        conversation_id=str(lead.conversation_id),
        customer_name=lead.customer_name,
        company_name=lead.company_name,
        email=str(lead.email),
        phone=lead.phone,
        industry=lead.industry,
        application=lead.application,
        fluid_description=lead.fluid_description,
        viscosity_cp=lead.viscosity_cp,
        viscosity_unit=lead.viscosity_unit,
        flow_rate_ml_min=lead.flow_rate_ml_min,
        flow_rate_unit=lead.flow_rate_unit,
        droplet_size_um=lead.droplet_size_um,
        droplet_size_unit=lead.droplet_size_unit,
        spray_pattern=lead.spray_pattern,
        feed_configuration=lead.feed_configuration,
        notes=lead.notes,
        technical_notes=lead.notes,
        internal_notes=None,  # STRICT PRIVACY: Internal engineering & sales notes NEVER exposed to customer!
        recommended_product_ids=lead.recommended_product_ids,
        recommendation_summary=lead.recommendation_summary,
        lead_source=lead.lead_source,
        stage=lead.stage,
        preferred_follow_up_at=lead.preferred_follow_up_at.isoformat() if lead.preferred_follow_up_at else None,
        preferred_follow_up_timezone=lead.preferred_follow_up_timezone,
        follow_up_notes=lead.follow_up_notes,
        created_at=lead.created_at.isoformat() if hasattr(lead.created_at, "isoformat") else str(lead.created_at),
        updated_at=lead.updated_at.isoformat() if hasattr(lead.updated_at, "isoformat") else str(lead.updated_at),
    )


# --- Leads Endpoints ---

@router.post(
    "/leads",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Create or update structured customer inquiry lead from consultation",
)
async def create_or_update_lead_endpoint(
    body: CreateLeadRequest,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    conv = await get_customer_conversation(database, current_customer, body.conversation_id)

    comp_doc = await database.companies.find_one({"_id": current_customer.company_id})
    company_name = comp_doc.get("name") if comp_doc else "Client Company"

    candidate_products = await list_accessible_products_for_user(database, current_customer)
    rec_result = evaluate_recommendations(conv.requirements, candidate_products)

    recommended_ids = [p.product_id for p in rec_result.confirmed_recommendations]
    summary_text = "; ".join(rec_result.summary_reasons) if rec_result.summary_reasons else None

    existing_doc = await database.leads.find_one({
        "company_id": current_customer.company_id,
        "conversation_id": conv.id,
    })

    now = utc_now()
    if existing_doc:
        lead = Lead(**existing_doc)
        lead.customer_name = body.customer_name.strip()
        lead.email = body.email
        lead.phone = body.phone.strip() if body.phone else None
        lead.notes = body.notes.strip() if body.notes else lead.notes
        if body.preferred_follow_up_at:
            lead.preferred_follow_up_at = body.preferred_follow_up_at
        if body.preferred_follow_up_timezone:
            lead.preferred_follow_up_timezone = body.preferred_follow_up_timezone
        lead.industry = conv.requirements.industry
        lead.application = conv.requirements.application
        lead.fluid_description = conv.requirements.fluid_description
        lead.viscosity_cp = conv.requirements.viscosity_cp
        lead.flow_rate_ml_min = conv.requirements.flow_rate_ml_min
        lead.droplet_size_um = conv.requirements.droplet_size_um
        lead.spray_pattern = conv.requirements.spray_pattern
        lead.feed_configuration = conv.requirements.feed_configuration
        lead.recommended_product_ids = recommended_ids
        lead.recommendation_summary = summary_text
        lead.updated_at = now

        await database.leads.replace_one(
            {"_id": lead.id},
            lead.model_dump(by_alias=True, exclude={"id"}),
        )
    else:
        lead = Lead(
            customer_user_id=current_customer.id,
            company_id=current_customer.company_id,
            conversation_id=conv.id,
            customer_name=body.customer_name.strip(),
            company_name=company_name,
            email=body.email,
            phone=body.phone.strip() if body.phone else None,
            industry=conv.requirements.industry,
            application=conv.requirements.application,
            fluid_description=conv.requirements.fluid_description,
            viscosity_cp=conv.requirements.viscosity_cp,
            flow_rate_ml_min=conv.requirements.flow_rate_ml_min,
            droplet_size_um=conv.requirements.droplet_size_um,
            spray_pattern=conv.requirements.spray_pattern,
            feed_configuration=conv.requirements.feed_configuration,
            notes=body.notes.strip() if body.notes else None,
            recommended_product_ids=recommended_ids,
            recommendation_summary=summary_text,
            lead_source="customer_consultation",
            stage=LeadStage.QUALIFIED if recommended_ids else LeadStage.NEW,
            preferred_follow_up_at=body.preferred_follow_up_at,
            preferred_follow_up_timezone=body.preferred_follow_up_timezone,
            created_at=now,
            updated_at=now,
        )
        res = await database.leads.insert_one(lead.model_dump(by_alias=True, exclude={"id"}))
        lead.id = res.inserted_id

    return build_lead_response(lead)


@router.get(
    "/leads/conversation/{conversation_id}",
    response_model=LeadResponse | None,
    dependencies=[Depends(require_customer_user)],
    summary="Retrieve existing lead record for a consultation",
)
async def get_lead_by_conversation_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    conv = await get_customer_conversation(database, current_customer, conversation_id)
    doc = await database.leads.find_one({
        "company_id": current_customer.company_id,
        "conversation_id": conv.id,
    })
    if not doc:
        return None
    return build_lead_response(Lead(**doc))


# --- Quotation Preview & Download Endpoints ---

@router.get(
    "/conversations/{conversation_id}/quote-preview",
    dependencies=[Depends(require_customer_user)],
    summary="Generate a structured quotation draft preview from conversation requirements",
)
async def get_quote_preview_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    return await generate_quotation_data(database, current_customer, conversation_id)


@router.get(
    "/conversations/{conversation_id}/quote-preview/download",
    dependencies=[Depends(require_customer_user)],
    summary="Download print-ready quotation HTML document",
)
async def download_quote_html_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    quote_data = await generate_quotation_data(database, current_customer, conversation_id)
    html_content = generate_quotation_html(quote_data)
    ref = quote_data.get("quote_reference", "quotation")
    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="WaveNxD-Quotation-{ref}.html"'},
    )


# --- Email Draft Endpoints ---

@router.get(
    "/conversations/{conversation_id}/email-draft",
    dependencies=[Depends(require_customer_user)],
    summary="Preview quotation email draft without external sending",
)
async def get_email_draft_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    quote_data = await generate_quotation_data(database, current_customer, conversation_id)
    recipient = quote_data["customer"].get("email") or str(current_customer.email)
    metadata, _ = create_quotation_email_draft(quote_data, recipient)
    return metadata


@router.get(
    "/conversations/{conversation_id}/email-draft/download",
    dependencies=[Depends(require_customer_user)],
    summary="Download RFC 822 .eml email draft file",
)
async def download_email_draft_eml_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    quote_data = await generate_quotation_data(database, current_customer, conversation_id)
    recipient = quote_data["customer"].get("email") or str(current_customer.email)
    metadata, eml_bytes = create_quotation_email_draft(quote_data, recipient)
    filename = metadata.get("eml_filename", "WaveNxD-Quote.eml")
    return Response(
        content=eml_bytes,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/conversations/{conversation_id}/email-simulate",
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Simulate email dispatch in development mode (explicitly never sent)",
)
async def simulate_email_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    quote_data = await generate_quotation_data(database, current_customer, conversation_id)
    recipient = quote_data["customer"].get("email") or str(current_customer.email)
    return simulate_email_delivery(quote_data, recipient)


# --- Follow-Up Scheduling & Calendar Endpoints ---

@router.post(
    "/conversations/{conversation_id}/follow-up",
    response_model=ScheduleFollowUpResponse,
    dependencies=[Depends(require_customer_user), Depends(validate_csrf)],
    summary="Schedule follow-up consultation date and time, updating lead and returning calendar links",
)
async def schedule_follow_up_endpoint(
    conversation_id: str,
    body: ScheduleFollowUpRequest,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    conv = await get_customer_conversation(database, current_customer, conversation_id)
    comp_doc = await database.companies.find_one({"_id": current_customer.company_id})
    company_name = comp_doc.get("name") if comp_doc else "Client Company"

    lead_doc = await database.leads.find_one({
        "company_id": current_customer.company_id,
        "conversation_id": conv.id,
    })

    now = utc_now()
    if lead_doc:
        lead = Lead(**lead_doc)
        lead.preferred_follow_up_at = body.scheduled_at
        lead.preferred_follow_up_timezone = body.timezone
        lead.follow_up_notes = body.notes
        lead.stage = LeadStage.FOLLOW_UP_REQUESTED
        lead.updated_at = now
        await database.leads.replace_one(
            {"_id": lead.id},
            lead.model_dump(by_alias=True, exclude={"id"}),
        )
        cust_name = lead.customer_name
    else:
        lead = Lead(
            customer_user_id=current_customer.id,
            company_id=current_customer.company_id,
            conversation_id=conv.id,
            customer_name=current_customer.full_name or "Authorized Representative",
            company_name=company_name,
            email=current_customer.email,
            industry=conv.requirements.industry,
            application=conv.requirements.application,
            fluid_description=conv.requirements.fluid_description,
            viscosity_cp=conv.requirements.viscosity_cp,
            flow_rate_ml_min=conv.requirements.flow_rate_ml_min,
            droplet_size_um=conv.requirements.droplet_size_um,
            spray_pattern=conv.requirements.spray_pattern,
            feed_configuration=conv.requirements.feed_configuration,
            stage=LeadStage.FOLLOW_UP_REQUESTED,
            preferred_follow_up_at=body.scheduled_at,
            preferred_follow_up_timezone=body.timezone,
            follow_up_notes=body.notes,
            created_at=now,
            updated_at=now,
        )
        res = await database.leads.insert_one(lead.model_dump(by_alias=True, exclude={"id"}))
        cust_name = lead.customer_name

    gcal_url = generate_google_calendar_url(
        customer_name=cust_name,
        company_name=company_name,
        application=conv.requirements.application,
        event_start=body.scheduled_at,
        duration_minutes=body.duration_minutes,
    )

    return ScheduleFollowUpResponse(
        conversation_id=str(conv.id),
        scheduled_at=body.scheduled_at.isoformat(),
        timezone=body.timezone,
        duration_minutes=body.duration_minutes,
        notes=body.notes,
        google_calendar_url=gcal_url,
        message="Follow-up consultation invitation prepared successfully. Download the calendar file to add to your calendar.",
    )


@router.get(
    "/conversations/{conversation_id}/follow-up/calendar.ics",
    dependencies=[Depends(require_customer_user)],
    summary="Download RFC 5545 .ics calendar invitation file for scheduled follow-up",
)
async def download_calendar_ics_endpoint(
    conversation_id: str,
    current_customer: User = Depends(require_customer_user),
    database: Any = Depends(get_database),
):
    conv = await get_customer_conversation(database, current_customer, conversation_id)
    comp_doc = await database.companies.find_one({"_id": current_customer.company_id})
    company_name = comp_doc.get("name") if comp_doc else "Client Company"

    lead_doc = await database.leads.find_one({
        "company_id": current_customer.company_id,
        "conversation_id": conv.id,
    })

    if not lead_doc or not lead_doc.get("preferred_follow_up_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No follow-up appointment has been scheduled for this consultation yet.",
        )

    event_start = lead_doc["preferred_follow_up_at"]
    cust_name = lead_doc.get("customer_name") or current_customer.full_name or "Authorized Representative"
    notes = lead_doc.get("follow_up_notes")

    ics_content = generate_ics_calendar(
        customer_name=cust_name,
        company_name=company_name,
        application=conv.requirements.application,
        event_start=event_start,
        duration_minutes=30,
        notes=notes,
    )

    short_id = str(conv.id)[-6:].lower()
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="wavenxd-consultation-{short_id}.ics"'},
    )


