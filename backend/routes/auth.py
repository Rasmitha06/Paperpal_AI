from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.deps import get_usage_info, resolve_user
from backend.models.auth import AuthResponse, SignInRequest, SignUpRequest, UsageResponse
from backend.services.auth_service import (
    authenticate_user,
    new_guest_id,
    register_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse)
async def signup(body: SignUpRequest):
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    try:
        result = register_user(body.email, body.password, body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return AuthResponse(
        token=result["token"],
        user={"id": result["id"], "email": result["email"], "name": result["name"]},
    )


@router.post("/signin", response_model=AuthResponse)
async def signin(body: SignInRequest):
    try:
        result = authenticate_user(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return AuthResponse(
        token=result["token"],
        user={"id": result["id"], "email": result["email"], "name": result["name"]},
    )


@router.get("/me")
async def me(user: dict = Depends(resolve_user)):
    if not user:
        raise HTTPException(401, "Not authenticated.")
    return {"user": user}


@router.get("/usage", response_model=UsageResponse)
async def usage(info: dict = Depends(get_usage_info)):
    return UsageResponse(**info)


@router.post("/guest")
async def create_guest():
    return {"guest_id": new_guest_id()}
