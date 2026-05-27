from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, Field


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=80)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: Dict[str, Any]


class UsageResponse(BaseModel):
    is_authenticated: bool
    user: Optional[Dict[str, Any]] = None
    operations_used: Optional[int] = None
    daily_limit: Optional[int] = None
    remaining: Optional[int] = None
    guest_id: Optional[str] = None
