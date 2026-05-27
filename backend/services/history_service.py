from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional

from backend.database import get_connection

HistoryKind = Literal["search", "chat", "upload"]
MAX_HISTORY_ROWS = 200


def owner_key_from_identity(identity: dict) -> str:
    if identity.get("type") == "user" and identity.get("user"):
        return f"user:{identity['user']['id']}"
    guest_id = identity.get("guest_id") or "anonymous"
    return f"guest:{guest_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune_history(conn, owner_key: str) -> None:
    conn.execute(
        """
        DELETE FROM history
        WHERE owner_key = ? AND id NOT IN (
            SELECT id FROM history
            WHERE owner_key = ?
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        )
        """,
        (owner_key, owner_key, MAX_HISTORY_ROWS),
    )


def add_history(
    owner_key: str,
    kind: HistoryKind,
    title: str,
    payload: dict,
    doc_id: Optional[str] = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO history (owner_key, kind, doc_id, title, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                owner_key,
                kind,
                doc_id,
                title[:240],
                json.dumps(payload),
                _now_iso(),
            ),
        )
        conn.commit()
        _prune_history(conn, owner_key)
        return int(cur.lastrowid)
    finally:
        conn.close()


def save_search_history(
    identity: dict,
    doc_id: str,
    filename: str,
    question: str,
    answer: str,
    relevancy_score: Optional[float],
    chunks: Optional[list],
) -> None:
    owner = owner_key_from_identity(identity)
    title = question.strip()[:80] or "Search query"
    chunk_summary = []
    if chunks:
        for c in chunks[:6]:
            chunk_summary.append(
                {
                    "chunk_id": c.get("chunk_id"),
                    "page": c.get("page"),
                    "score": c.get("score"),
                }
            )
    add_history(
        owner,
        "search",
        title,
        {
            "question": question,
            "answer": answer,
            "filename": filename,
            "relevancy_score": relevancy_score,
            "chunks": chunk_summary,
        },
        doc_id=doc_id,
    )


def save_upload_history(
    identity: dict,
    doc_id: str,
    filename: str,
    page_count: int,
    chunk_count: int,
) -> None:
    owner = owner_key_from_identity(identity)
    add_history(
        owner,
        "upload",
        f"Uploaded {filename}",
        {
            "filename": filename,
            "page_count": page_count,
            "chunk_count": chunk_count,
        },
        doc_id=doc_id,
    )


def save_chat_session(
    owner_key: str,
    doc_id: str,
    filename: str,
    messages: list,
) -> None:
    if not doc_id or not messages:
        return
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO chat_sessions (owner_key, doc_id, filename, messages, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_key, doc_id) DO UPDATE SET
                filename = excluded.filename,
                messages = excluded.messages,
                updated_at = excluded.updated_at
            """,
            (owner_key, doc_id, filename, json.dumps(messages), _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_chat_session(owner_key: str, doc_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT doc_id, filename, messages, updated_at
            FROM chat_sessions
            WHERE owner_key = ? AND doc_id = ?
            """,
            (owner_key, doc_id),
        ).fetchone()
        if not row:
            return None
        return {
            "doc_id": row["doc_id"],
            "filename": row["filename"],
            "messages": json.loads(row["messages"]),
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def list_chat_sessions(owner_key: str, limit: int = 50) -> List[dict]:
    conn = get_connection()
    try:
        limit = max(1, min(limit, 100))
        rows = conn.execute(
            """
            SELECT rowid AS id, doc_id, filename, messages, updated_at
            FROM chat_sessions
            WHERE owner_key = ?
            ORDER BY datetime(updated_at) DESC
            LIMIT ?
            """,
            (owner_key, limit),
        ).fetchall()
        items = []
        for row in rows:
            messages = json.loads(row["messages"])
            name = row["filename"] or row["doc_id"]
            items.append(
                {
                    "id": row["id"],
                    "kind": "chat",
                    "doc_id": row["doc_id"],
                    "title": f"Chat — {name} ({len(messages)} msgs)",
                    "payload": {
                        "filename": row["filename"],
                        "messages": messages,
                    },
                    "created_at": row["updated_at"],
                }
            )
        return items
    finally:
        conn.close()


def list_history(
    owner_key: str,
    kind: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    if kind == "chat":
        return list_chat_sessions(owner_key, limit)
    conn = get_connection()
    try:
        limit = max(1, min(limit, 100))
        if kind == "all":
            events = conn.execute(
                """
                SELECT id, kind, doc_id, title, payload, created_at
                FROM history
                WHERE owner_key = ?
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (owner_key, limit),
            ).fetchall()
            try:
                chats = list_chat_sessions(owner_key, limit=min(limit, 20))
            except Exception:
                chats = []
            combined = []
            for row in events:
                combined.append(
                    {
                        "id": row["id"],
                        "kind": row["kind"],
                        "doc_id": row["doc_id"],
                        "title": row["title"],
                        "payload": json.loads(row["payload"]),
                        "created_at": row["created_at"],
                    }
                )
            combined.extend(chats)
            combined.sort(key=lambda x: x["created_at"], reverse=True)
            return combined[:limit]

        if kind and kind != "all":
            rows = conn.execute(
                """
                SELECT id, kind, doc_id, title, payload, created_at
                FROM history
                WHERE owner_key = ? AND kind = ?
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (owner_key, kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, kind, doc_id, title, payload, created_at
                FROM history
                WHERE owner_key = ?
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (owner_key, limit),
            ).fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "doc_id": row["doc_id"],
                    "title": row["title"],
                    "payload": json.loads(row["payload"]),
                    "created_at": row["created_at"],
                }
            )
        return items
    finally:
        conn.close()


def delete_history_item(owner_key: str, item_id: int, kind: Optional[str] = None) -> bool:
    conn = get_connection()
    try:
        if kind == "chat":
            cur = conn.execute(
                "DELETE FROM chat_sessions WHERE rowid = ? AND owner_key = ?",
                (item_id, owner_key),
            )
        else:
            cur = conn.execute(
                "DELETE FROM history WHERE id = ? AND owner_key = ?",
                (item_id, owner_key),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def filename_for_doc(doc_id: str) -> str:
    from backend.config import load_registry

    for doc in load_registry():
        if doc.get("doc_id") == doc_id:
            return doc.get("filename") or doc_id
    return doc_id


def resolve_owner_keys(
    authorization: Optional[str],
    x_guest_id: Optional[str],
) -> List[str]:
    """Signed-in users only; guests do not get persisted history lists."""
    from backend.deps import resolve_user

    _ = x_guest_id
    user = resolve_user(authorization)
    if user:
        return [f"user:{user['id']}"]
    return []


def resolve_owner_key(
    authorization: Optional[str],
    x_guest_id: Optional[str],
) -> Optional[str]:
    keys = resolve_owner_keys(authorization, x_guest_id)
    return keys[0] if keys else None


def list_history_merged(
    owner_keys: List[str],
    kind: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    if not owner_keys:
        return []
    if len(owner_keys) == 1:
        return list_history(owner_keys[0], kind=kind, limit=limit)

    seen: set[str] = set()
    combined: List[dict] = []
    per_owner = max(limit // len(owner_keys) + 5, limit)
    for key in owner_keys:
        for item in list_history(key, kind=kind, limit=per_owner):
            dedupe = f"{item['kind']}:{item['id']}:{item.get('title', '')}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            combined.append(item)
    combined.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return combined[:limit]
