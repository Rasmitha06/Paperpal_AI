from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from backend.config import settings
from backend.services.auth_service import (
    check_guest_can_operate,
    decode_token,
    get_user_by_id,
    increment_guest_usage,
    usage_status,
)


async def require_user(
    authorization: Optional[str] = Header(None),
) -> dict:
    user = resolve_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to access this feature.")
    return user


def resolve_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    payload = decode_token(token)
    if not payload:
        return None
    user = get_user_by_id(int(payload["sub"]))
    return user


async def require_operation_slot(
    authorization: Optional[str] = Header(None),
    x_guest_id: Optional[str] = Header(None),
) -> dict:
    """Authenticated users: unlimited. Guests: max 2 ops/day."""
    user = resolve_user(authorization)
    if user:
        return {"type": "user", "user": user, "guest_id": None}

    try:
        check_guest_can_operate(x_guest_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "message": str(exc),
                "code": "GUEST_LIMIT",
                "sign_up_required": True,
            },
        ) from exc

    return {"type": "guest", "user": None, "guest_id": x_guest_id}


def record_operation(identity: dict) -> None:
    if identity["type"] == "guest" and identity.get("guest_id"):
        increment_guest_usage(identity["guest_id"])


async def get_usage_info(
    authorization: Optional[str] = Header(None),
    x_guest_id: Optional[str] = Header(None),
) -> dict:
    user = resolve_user(authorization)
    return usage_status(user, x_guest_id)
