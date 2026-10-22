from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.core.dependencies import (
    get_current_user,
    get_database,
    require_admin_user,
    validate_csrf,
)
from app.core.rate_limit import check_rate_limit, clear_attempts, record_attempt
from app.core.security import generate_secure_token, verify_password
from app.domain.enums import UserRole
from app.models.user import User
from app.services.invitation_service import (
    InvitationError,
    InvitationNotFoundError,
    accept_invitation,
    create_invitation,
)
from app.services.session_service import create_session, get_session_by_token, revoke_session

router = APIRouter(prefix="/auth", tags=["Authentication"])


# --- Schemas ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    company_id: str | None = None
    must_change_password: bool


class LoginResponse(BaseModel):
    user: UserResponse
    csrf_token: str
    message: str = "Login successful"


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    company_id: str
    expiry_hours: int | None = Field(default=None, gt=0, le=168)


class InvitationResponse(BaseModel):
    id: str
    email: EmailStr
    company_id: str
    invitation_token: str
    expires_at: str
    message: str = "Invitation created successfully"


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)


def build_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        company_id=str(user.company_id) if user.company_id else None,
        must_change_password=user.must_change_password,
    )


# --- Endpoints ---

@router.get("/csrf", summary="Obtain a CSRF token")
async def get_csrf_token(
    request: Request,
    response: Response,
    database: Any = Depends(get_database),
):
    """
    Issues a CSRF token for the client, setting a companion cookie.
    Must be called before submitting state-changing requests if unauthenticated.
    If an active session exists, synchronizes and returns the session's CSRF token.
    """
    settings = get_settings()

    # If an active session already exists, synchronize and return its CSRF token
    raw_session = request.cookies.get(settings.session_cookie_name)
    if raw_session:
        session = await get_session_by_token(database, raw_session)
        if session is not None:
            csrf_token = session.csrf_token
            response.set_cookie(
                key=settings.csrf_cookie_name,
                value=csrf_token,
                max_age=settings.session_max_age_seconds,
                httponly=False,
                secure=settings.is_cookie_secure,
                samesite=settings.session_cookie_samesite,
                path="/",
            )
            return {"csrf_token": csrf_token}

    # Otherwise issue a fresh secure CSRF token
    csrf_token = generate_secure_token(32)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_max_age_seconds,
        httponly=False,  # Allow frontend reading for double-submit header
        secure=settings.is_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    return {"csrf_token": csrf_token}


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(validate_csrf)],
    summary="Authenticate with email and password",
)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    database: Any = Depends(get_database),
):
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    normalized_email = body.email.strip().lower()

    # Rate limiting protection
    rate_key_ip = f"ip:{client_ip}"
    rate_key_email = f"email:{normalized_email}"

    if not check_rate_limit(rate_key_ip, max_attempts=15) or not check_rate_limit(
        rate_key_email, max_attempts=10
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please try again later.",
        )

    user_doc = await database.users.find_one({"email": normalized_email})

    # Always use generic error response to prevent user enumeration
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )

    if not user_doc:
        record_attempt(rate_key_ip)
        record_attempt(rate_key_email)
        raise generic_error

    user = User(**user_doc)

    if not user.is_active or not user.password_hash:
        record_attempt(rate_key_ip)
        record_attempt(rate_key_email)
        raise generic_error

    if not verify_password(body.password, user.password_hash):
        record_attempt(rate_key_ip)
        record_attempt(rate_key_email)
        raise generic_error

    # Successful authentication
    clear_attempts(rate_key_email)

    # Invalidate any old session if cookie present to prevent fixation
    old_cookie = request.cookies.get(settings.session_cookie_name)
    if old_cookie:
        await revoke_session(database, old_cookie)

    user_agent = request.headers.get("user-agent")
    session, raw_token = await create_session(
        database,
        user_id=user.id,
        user_agent=user_agent,
        ip_address=client_ip,
    )

    # Set secure session cookie
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_max_age_seconds,
        httponly=settings.session_cookie_httponly,
        secure=settings.is_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )

    # Set CSRF cookie matching session CSRF token
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=session.csrf_token,
        max_age=settings.session_max_age_seconds,
        httponly=False,
        secure=settings.is_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )

    return LoginResponse(
        user=build_user_response(user),
        csrf_token=session.csrf_token,
    )


@router.post(
    "/logout",
    dependencies=[Depends(validate_csrf)],
    summary="Log out and revoke current session",
)
async def logout(
    request: Request,
    response: Response,
    database: Any = Depends(get_database),
):
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        await revoke_session(database, raw_token)

    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
    )

    return {"status": "ok", "message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse, summary="Get current authenticated user")
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    return build_user_response(current_user)


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    dependencies=[Depends(require_admin_user), Depends(validate_csrf)],
    summary="Create an invitation for a customer user (Admin only)",
)
async def create_customer_invitation(
    body: CreateInvitationRequest,
    current_admin: User = Depends(require_admin_user),
    database: Any = Depends(get_database),
):
    if not ObjectId.is_valid(body.company_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid company ID",
        )

    company_oid = ObjectId(body.company_id)
    try:
        invitation, raw_token = await create_invitation(
            database=database,
            email=body.email,
            company_id=company_oid,
            invited_by_user_id=current_admin.id,
            expiry_hours=body.expiry_hours,
        )
    except InvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return InvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        company_id=str(invitation.company_id),
        invitation_token=raw_token,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.post(
    "/invitations/accept",
    response_model=UserResponse,
    dependencies=[Depends(validate_csrf)],
    summary="Accept an invitation and set customer account password",
)
async def accept_customer_invitation(
    body: AcceptInvitationRequest,
    database: Any = Depends(get_database),
):
    try:
        user = await accept_invitation(
            database=database,
            raw_token=body.token,
            password=body.password,
            full_name=body.full_name,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except InvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return build_user_response(user)
