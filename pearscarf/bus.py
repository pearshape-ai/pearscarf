from __future__ import annotations

from typing import Any

from pearscarf.storage import db


class MessageBus:
    def __init__(self) -> None:
        db.init_db()

    def create_session(self, initiated_by: str, summary: str = "") -> str:
        return db.create_session(initiated_by, summary)

    def send(
        self,
        session_id: str,
        from_agent: str,
        to_agent: str,
        content: str,
        reasoning: str = "",
        data: dict[str, Any] | None = None,
    ) -> int:
        return db.insert_message(
            session_id, from_agent, to_agent, content, reasoning, data
        )

    def poll(self, agent_name: str) -> list[dict]:
        messages = db.poll_unread(agent_name)
        for msg in messages:
            db.mark_read(msg["id"])
        return messages

    def list_sessions(self) -> list[dict]:
        return db.list_sessions()

    def get_session(self, session_id: str) -> dict | None:
        return db.get_session(session_id)

    def get_history(self, session_id: str) -> list[dict]:
        return db.get_history(session_id)
