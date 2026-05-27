from __future__ import annotations

import secrets
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

import jwt
from passlib.context import CryptContext

from backend.config import settings
from backend.database import get_connection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

GUEST_DAILY_LIMIT = 2


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(user_id: int, email: str, name: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "exp": datetime.utcnow() + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def register_user(email: str, password: str, name: str) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
            (email.lower().strip(), name.strip(), hash_password(password)),
        )
        conn.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("Email already registered.") from exc
    finally:
        conn.close()

    token = create_access_token(user_id, email, name)
    return {"id": user_id, "email": email, "name": name, "token": token}


def authenticate_user(email: str, password: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, email, name, password_hash FROM users WHERE email = ?",
        (email.lower().strip(),),
    ).fetchone()
    conn.close()

    if not row or not verify_password(password, row["password_hash"]):
        raise ValueError("Invalid email or password.")

    token = create_access_token(row["id"], row["email"], row["name"])
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "token": token,
    }


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, email, name FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row["id"], "email": row["email"], "name": row["name"]}


def new_guest_id() -> str:
    return f"guest_{secrets.token_hex(16)}"


def get_guest_usage(guest_id: str) -> int:
    today = date.today().isoformat()
    conn = get_connection()
    row = conn.execute(
        "SELECT operation_count FROM guest_usage WHERE guest_id = ? AND usage_date = ?",
        (guest_id, today),
    ).fetchone()
    conn.close()
    return int(row["operation_count"]) if row else 0


def increment_guest_usage(guest_id: str) -> int:
    today = date.today().isoformat()
    conn = get_connection()
    row = conn.execute(
        "SELECT operation_count FROM guest_usage WHERE guest_id = ? AND usage_date = ?",
        (guest_id, today),
    ).fetchone()
    if row:
        new_count = row["operation_count"] + 1
        conn.execute(
            "UPDATE guest_usage SET operation_count = ? WHERE guest_id = ? AND usage_date = ?",
            (new_count, guest_id, today),
        )
    else:
        new_count = 1
        conn.execute(
            "INSERT INTO guest_usage (guest_id, usage_date, operation_count) VALUES (?, ?, ?)",
            (guest_id, today, 1),
        )
    conn.commit()
    conn.close()
    return new_count


def check_guest_can_operate(guest_id: Optional[str]) -> None:
    if not guest_id:
        raise ValueError("Guest ID required. Refresh the page.")
    used = get_guest_usage(guest_id)
    if used >= GUEST_DAILY_LIMIT:
        raise ValueError(
            f"Guest limit reached ({GUEST_DAILY_LIMIT}/day). Sign up for unlimited access."
        )


def usage_status(user: Optional[dict], guest_id: Optional[str]) -> dict:
    if user:
        return {
            "is_authenticated": True,
            "user": user,
            "operations_used": None,
            "daily_limit": None,
            "remaining": None,
        }
    used = get_guest_usage(guest_id) if guest_id else 0
    return {
        "is_authenticated": False,
        "user": None,
        "operations_used": used,
        "daily_limit": GUEST_DAILY_LIMIT,
        "remaining": max(0, GUEST_DAILY_LIMIT - used),
        "guest_id": guest_id,
    }
