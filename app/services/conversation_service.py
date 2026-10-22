import json
import logging
import re
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.config import get_settings
from app.domain.enums import ConversationStatus, MessageRole
from app.models.common import utc_now
from app.models.conversation import Conversation, Message
from app.models.product import Product
from app.models.recommendation import CustomerRequirements, RecommendationResult
from app.models.user import User
from app.services.authorization import list_accessible_products_for_user, parse_object_id
from app.services.llm_provider import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProvider,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMServiceOverloadError,
    LLMTransientRateLimitError,
)
from app.services.prompts import build_sales_system_prompt
from app.services.recommendation_engine import evaluate_recommendations

logger = logging.getLogger(__name__)

# Regex patterns for deterministic parameter extraction from user messages (multilingual support)
VISCOSITY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:cp|centipoise|सीपी|सेंटिपॉइझ|सेंटिपॉइज)",
    re.IGNORECASE,
)
FLOW_RATE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:ml/min|ml\s*/\s*min|milliliters?\s*per\s*min(?:ute)?|एमएल/मिनिट|एमएल/मिनट|मिली/मिनट|मिली/मिनिट)",
    re.IGNORECASE,
)
DROPLET_SIZE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:um|µm|microns?|micrometers?|मायक्रॉन|माइक्रोन|मायक्रोमीटर|माइक्रोमीटर)",
    re.IGNORECASE,
)

MARATHI_KEYWORDS = {"आम्हाला", "पाहिजे", "आहे", "नमस्कार", "पाण्याचा", "साठी", "करा", "होय", "नाही", "हवी", "द्या", "नोझल"}
HINDI_KEYWORDS = {"नमस्ते", "चाहिए", "हमारा", "है", "पानी", "के लिए", "बताइए", "दवा", "नोजल"}
HINGLISH_KEYWORDS = {"hume", "chahiye", "hamara", "hoga", "hai", "karo", "kitna", "ke liye", "pahije", "aamhi", "namaste"}

INITIAL_GREETINGS: dict[str, str] = {
    "en": (
        "Hello! I am your WaveNxD AI Sales Representative. WaveNxD specializes in precision ultrasonic "
        "atomization and precision dispensing nozzles, delivering uniform, low-velocity micro-droplets "
        "with minimal overspray across industrial and medical applications. What coating or dispensing "
        "application are you looking to solve, and what liquid or coating material are you working with?"
    ),
    "hi": (
        "नमस्ते! मैं आपका WaveNxD AI सेल्स प्रतिनिधि हूँ। WaveNxD सटीक अल्ट्रासोनिक एटमाइज़ेशन और डिस्पेंसिंग "
        "तकनीकों में विशेषज्ञता रखता है, जो कम ओवरस्प्रे के साथ एकसमान माइक्रो-बूंदें प्रदान करता है। "
        "आप किस एप्लीकेशन या कोटिंग प्रक्रिया के लिए समाधान खोज रहे हैं, और आपका लिक्विड या कोटिंग मटेरियल क्या है?"
    ),
    "mr": (
        "नमस्कार! मी आपला WaveNxD AI विक्री प्रतिनिधी आहे. WaveNxD अचूक अल्ट्रासोनिक फवारणी आणि डिस्पेंसिंग "
        "तंत्रज्ञानामध्ये तज्ज्ञ आहे, जे कमीत कमी वाया जाणाऱ्या सूक्ष्म थेंबांची अचूक फवारणी प्रदान करते. "
        "आपण कोणत्या कोटिंग किंवा डिस्पेंसिंग ॲप्लिकेशनवर काम करत आहात, आणि आपले द्रव किंवा कोटिंग मटेरियल काय आहे?"
    ),
    "hinglish": (
        "Hello! Main aapka WaveNxD AI Sales Representative hoon. WaveNxD precision ultrasonic spray aur "
        "dispensing technology provide karta hai jo uniform micro-droplets aur minimal overspray deliver karta hai. "
        "Aap kis application ya coating process ke liye solution dekh rahe hain, aur aapka fluid ya coating material kya hai?"
    ),
}


def detect_language(text: str) -> str:
    """Heuristic language detection distinguishing English, Hindi, Marathi, and Hinglish."""
    if not text or not text.strip():
        return "en"

    # Check Devanagari Unicode block
    if re.search(r"[\u0900-\u097F]", text):
        for kw in MARATHI_KEYWORDS:
            if kw in text:
                return "mr"
        return "hi"

    # Check Latin Hinglish
    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    if words.intersection(HINGLISH_KEYWORDS):
        return "hinglish"

    return "en"


def extract_regex_requirements(text: str) -> dict[str, Any]:
    """Deterministically extracts known numeric engineering units from user text."""
    updates: dict[str, Any] = {}

    v_match = VISCOSITY_PATTERN.search(text)
    if v_match:
        try:
            val = float(v_match.group(1))
            if val > 0:
                updates["viscosity_cp"] = val
        except ValueError:
            pass

    f_match = FLOW_RATE_PATTERN.search(text)
    if f_match:
        try:
            val = float(f_match.group(1))
            if val > 0:
                updates["flow_rate_ml_min"] = val
        except ValueError:
            pass

    d_match = DROPLET_SIZE_PATTERN.search(text)
    if d_match:
        try:
            val = float(d_match.group(1))
            if val > 0:
                updates["droplet_size_um"] = val
        except ValueError:
            pass

    return updates


def extract_llm_json_block(llm_content: str) -> tuple[str, dict[str, Any] | None]:
    """
    Extracts structured requirements updates from an LLM response and strips
    the trailing JSON block so only natural language is presented to the user.
    """
    json_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", llm_content, re.DOTALL)
    if not json_block_match:
        bare_match = re.search(r"(\{\s*\"requirements_update\".*?\})\s*$", llm_content, re.DOTALL)
        if bare_match:
            json_str = bare_match.group(1)
            clean_text = llm_content[:bare_match.start()].strip()
            try:
                data = json.loads(json_str)
                return clean_text, data
            except json.JSONDecodeError:
                return llm_content, None
        return llm_content, None

    json_str = json_block_match.group(1)
    clean_text = (llm_content[:json_block_match.start()] + llm_content[json_block_match.end():]).strip()
    try:
        data = json.loads(json_str)
        return clean_text, data
    except json.JSONDecodeError:
        return llm_content, None


def merge_requirements(
    current: CustomerRequirements,
    updates: dict[str, Any],
) -> CustomerRequirements:
    """
    Safely merges new requirements updates into current requirements.
    - Preserves existing values when newly provided values do not mention them.
    - Updates values when explicitly provided (including corrections).
    - Validates all fields through Pydantic; rejects invalid values without corrupting existing state.
    """
    current_dict = current.model_dump()

    for k, v in updates.items():
        if k in current_dict and v is not None:
            try:
                test_dict = {**current_dict, k: v}
                validated = CustomerRequirements(**test_dict)
                current_dict[k] = getattr(validated, k)
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning("Rejected invalid requirement update for '%s'=%s: %s", k, v, exc)

    return CustomerRequirements(**current_dict)


async def create_conversation(
    database: Any,
    customer_user: User,
    title: str | None = None,
    preferred_language: str = "en",
) -> Conversation:
    """Initializes and persists a new customer conversation."""
    if customer_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer must be associated with a company",
        )

    now = utc_now()
    clean_title = title.strip() if title and title.strip() else "New Product Consultation"
    lang = preferred_language.strip().lower() if preferred_language else "en"

    greeting_text = INITIAL_GREETINGS.get(lang, INITIAL_GREETINGS["en"])
    initial_greeting = Message(
        role=MessageRole.ASSISTANT,
        content=greeting_text,
        input_modality="text",
        language=lang,
        created_at=now,
    )

    conversation = Conversation(
        company_id=customer_user.company_id,
        user_id=customer_user.id,
        status=ConversationStatus.ACTIVE,
        title=clean_title,
        preferred_language=lang,
        messages=[initial_greeting],
        created_at=now,
        updated_at=now,
    )

    doc = conversation.model_dump(by_alias=True, exclude={"id"})
    result = await database.conversations.insert_one(doc)
    conversation.id = result.inserted_id
    return conversation


async def get_customer_conversation(
    database: Any,
    customer_user: User,
    conversation_id: str | ObjectId,
) -> Conversation:
    """
    Retrieves a conversation owned strictly by the authenticated customer.
    Raises 400 on malformed ID, 404 on non-existent or cross-tenant access.
    """
    cid = parse_object_id(conversation_id, error_status=status.HTTP_400_BAD_REQUEST, detail="Invalid conversation ID")

    doc = await database.conversations.find_one({"_id": cid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if doc.get("company_id") != customer_user.company_id or doc.get("user_id") != customer_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return Conversation(**doc)


async def list_customer_conversations(
    database: Any,
    customer_user: User,
) -> list[Conversation]:
    """Lists conversations belonging to the authenticated customer."""
    if customer_user.company_id is None:
        return []

    cursor = database.conversations.find(
        {"company_id": customer_user.company_id, "user_id": customer_user.id}
    ).sort("created_at", -1)
    docs = await cursor.to_list(length=1000)
    return [Conversation(**d) for d in docs]


async def process_user_message(
    database: Any,
    customer_user: User,
    conversation_id: str | ObjectId,
    user_text: str,
    llm_provider: LLMProvider,
    input_modality: str = "text",
    explicit_language: str | None = None,
) -> tuple[Conversation, Message, Message, RecommendationResult | None]:
    """
    Processes a customer message (text or voice-transcribed) in an existing conversation:
    1. Validates ownership and input length.
    2. Determines customer language preference and modality.
    3. Retrieves only authorized, active, published, verified products for customer's company.
    4. Merges deterministic extracted requirements and model updates.
    5. Evaluates recommendation engine using verified catalog boundaries.
    6. Stores updated conversation history and returns response.
    """
    settings = get_settings()
    cleaned_text = user_text.strip()
    if not cleaned_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content cannot be empty",
        )

    if len(cleaned_text) > settings.message_max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message exceeds maximum allowed length of {settings.message_max_length} characters",
        )

    conversation = await get_customer_conversation(database, customer_user, conversation_id)

    if len(conversation.messages) >= settings.conversation_max_messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conversation has reached maximum history limit of {settings.conversation_max_messages} messages",
        )

    # Resolve language
    detected_lang = detect_language(cleaned_text)
    if explicit_language and explicit_language.strip():
        active_language = explicit_language.strip().lower()
        conversation.preferred_language = active_language
    elif detected_lang != "en":
        active_language = detected_lang
        conversation.preferred_language = detected_lang
    else:
        active_language = conversation.preferred_language or "en"

    # 1. Authorize and retrieve company products
    authorized_products = await list_accessible_products_for_user(database, customer_user)

    company_name = "Your Company"
    comp_doc = await database.companies.find_one({"_id": customer_user.company_id})
    if comp_doc and comp_doc.get("name"):
        company_name = comp_doc["name"]

    # 2. Deterministic unit extraction from user message
    direct_updates = extract_regex_requirements(cleaned_text)
    updated_requirements = merge_requirements(conversation.requirements, direct_updates)

    # 3. Pre-evaluation with deterministic recommendation engine
    rec_result = evaluate_recommendations(updated_requirements, authorized_products)

    # 4. Format messages for LLM context
    history_messages: list[dict[str, str]] = []
    for m in conversation.messages[-20:]:
        history_messages.append({"role": m.role.value, "content": m.content})
    history_messages.append({"role": MessageRole.USER.value, "content": cleaned_text})

    system_prompt = build_sales_system_prompt(
        company_name=company_name,
        authorized_products=authorized_products,
        current_requirements=updated_requirements,
        recommendation_result=rec_result,
        preferred_language=active_language,
    )

    # 5. Call LLM provider
    try:
        llm_response = await llm_provider.generate_chat_response(
            messages=history_messages,
            system_prompt=system_prompt,
        )
    except (LLMProviderUnavailableError, LLMRateLimitError, LLMQuotaExhaustedError, LLMServiceOverloadError) as exc:
        logger.warning("AI sales assistant LLM provider unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI sales assistant service is temporarily unavailable. Please try again shortly or contact support.",
        ) from exc
    except (LLMAuthenticationError, LLMConfigurationError) as exc:
        logger.error("LLM provider configuration or authentication error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI sales assistant service configuration error. Please contact support.",
        ) from exc

    # 6. Parse assistant output and extract structured requirement proposals
    clean_assistant_text, structured_data = extract_llm_json_block(llm_response.content)

    if structured_data and isinstance(structured_data, dict):
        model_updates = structured_data.get("requirements_update")
        if isinstance(model_updates, dict):
            updated_requirements = merge_requirements(updated_requirements, model_updates)

        unresolved = structured_data.get("unresolved_questions")
        if isinstance(unresolved, list):
            for q in unresolved:
                if isinstance(q, str) and q.strip() and q.strip() not in conversation.unresolved_questions:
                    conversation.unresolved_questions.append(q.strip())

        if "detected_language" in structured_data and structured_data["detected_language"]:
            dl = str(structured_data["detected_language"]).strip().lower()
            if dl in ("en", "hi", "mr", "hinglish"):
                conversation.preferred_language = dl

    # 7. Re-evaluate recommendation engine with final merged requirements
    final_rec_result = evaluate_recommendations(updated_requirements, authorized_products)

    # 8. Record user and assistant messages
    now = utc_now()
    user_msg = Message(
        role=MessageRole.USER,
        content=cleaned_text,
        input_modality=input_modality,
        language=active_language,
        created_at=now,
    )
    assistant_msg = Message(
        role=MessageRole.ASSISTANT,
        content=clean_assistant_text,
        input_modality="text",
        language=conversation.preferred_language,
        created_at=now,
    )

    conversation.messages.append(user_msg)
    conversation.messages.append(assistant_msg)
    conversation.requirements = updated_requirements
    conversation.updated_at = now

    if conversation.title == "New Product Consultation" and len(cleaned_text) <= 50:
        conversation.title = cleaned_text

    # Persist in MongoDB
    await database.conversations.update_one(
        {"_id": conversation.id},
        {
            "$set": {
                "title": conversation.title,
                "preferred_language": conversation.preferred_language,
                "requirements": conversation.requirements.model_dump(),
                "unresolved_questions": conversation.unresolved_questions,
                "messages": [m.model_dump() for m in conversation.messages],
                "updated_at": now,
            }
        },
    )

    return conversation, user_msg, assistant_msg, final_rec_result
