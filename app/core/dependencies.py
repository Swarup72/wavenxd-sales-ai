import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.domain.enums import UserRole
from app.models.session import Session
from app.models.user import User
from app.services.session_service import get_session_by_token


def get_database(request: Request) -> Any:
    """Dependency that extracts the active MongoDB database from app state."""
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable",
        )
    return database


async def get_optional_session_and_user(
    request: Request,
    database: Any = Depends(get_database),
) -> tuple[Session | None, User | None]:
    """
    Attempts to resolve the current active session and user from cookies.
    Returns (None, None) if unauthenticated, expired, or revoked.
    """
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return None, None

    session = await get_session_by_token(database, raw_token)
    if session is None:
        return None, None

    user_doc = await database.users.find_one({"_id": session.user_id})
    if not user_doc:
        return None, None

    user = User(**user_doc)
    if not user.is_active:
        return None, None

    return session, user


async def get_current_session_and_user(
    session_and_user: tuple[Session | None, User | None] = Depends(
        get_optional_session_and_user
    ),
) -> tuple[Session, User]:
    """
    Enforces authentication. Raises 401 Unauthorized if not authenticated.
    """
    session, user = session_and_user
    if session is None or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session, user


async def get_current_user(
    session_and_user: tuple[Session, User] = Depends(get_current_session_and_user),
) -> User:
    """Returns the authenticated current User."""
    return session_and_user[1]


async def require_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Enforces that the current user is an active Administrator.
    Raises 403 Forbidden otherwise.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return current_user


async def require_customer_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Enforces that the current user is an active Customer user belonging to a company.
    Raises 403 Forbidden otherwise.
    """
    if current_user.role != UserRole.CUSTOMER or current_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer company access required",
        )
    return current_user


async def validate_csrf(
    request: Request,
    database: Any = Depends(get_database),
) -> None:
    """
    Validates CSRF tokens on state-changing HTTP methods (POST, PUT, PATCH, DELETE).
    - On /auth/login, validates against the CSRF cookie token (double-submit cookie),
      since login establishes/replaces authentication and pre-existing session cookies
      must not prevent authenticating with the login form's CSRF cookie.
    - If a valid session is present on other endpoints, validates against the session's CSRF token.
    - If unauthenticated, validates against the CSRF cookie token.
    Raises 403 Forbidden if the token is missing or invalid.
    """
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return

    settings = get_settings()
    token = request.headers.get("x-csrf-token") or request.headers.get("X-CSRF-Token")

    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing",
        )

    token = token.strip()

    # For login, authentication is being established, so validate against the CSRF cookie:
    if request.url.path.rstrip("/").endswith("/auth/login"):
        csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
        if not csrf_cookie or not secrets.compare_digest(csrf_cookie.strip(), token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            )
        return

    # Check if this request has a session
    raw_session = request.cookies.get(settings.session_cookie_name)
    if raw_session:
        session = await get_session_by_token(database, raw_session)
        if session is not None:
            if secrets.compare_digest(session.csrf_token, token):
                return
            csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
            if (
                csrf_cookie
                and secrets.compare_digest(csrf_cookie.strip(), token)
                and secrets.compare_digest(csrf_cookie.strip(), session.csrf_token)
            ):
                return
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            )

    # Unauthenticated state-changing request (e.g. invitation acceptance): check CSRF cookie
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_cookie or not secrets.compare_digest(csrf_cookie.strip(), token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

