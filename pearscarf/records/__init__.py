"""Default record-capture expert. Records arrive via MCP submission.

Initialized at startup like any other expert (build_context → get_handler);
the resulting RecordsExpert instance is registered on the registry under
its record_type so the MCP server can retrieve it via `get_connect`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext

VALID_OP_AREAS = ("reality",)

_ID_RE = re.compile(r"^Id:\s*(\S.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"^Date:\s*(\S.+?)\s*$", re.MULTILINE)


class RecordSubmissionError(ValueError):
    """Raised when a submission fails the at-the-door guards."""


def _parse_record_date(raw: str) -> datetime:
    """Parse the body's `Date:` value into a timezone-aware datetime.

    Accepts any ISO 8601 form Python 3.12's `datetime.fromisoformat` handles
    — full datetime (`2026-05-12T14:33:51Z`, `2026-05-12T14:33:51-07:00`,
    `2026-05-12 14:33:51+00:00`), or date-only (`2026-05-12`, treated as
    midnight UTC). Datetimes with a time portion but no timezone are
    rejected so we never silently guess a zone.
    """
    raw = raw.strip()
    # Date-only path first — `date.fromisoformat` is strict on `YYYY-MM-DD`
    # and rejects anything with a time component, so a hit here is unambiguous.
    try:
        parsed_date = date.fromisoformat(raw)
        return datetime.combine(parsed_date, time(0, 0), tzinfo=UTC)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RecordSubmissionError(
            f"`Date:` is not a valid ISO 8601 date/datetime: {raw!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise RecordSubmissionError(
            f"`Date:` must include a timezone (e.g. trailing 'Z' or '+00:00'): {raw!r}"
        )
    return parsed


class RecordsExpert:
    """Receives MCP-submitted record bodies and saves them through the
    standard pipeline. Body shape (Title / Id / Date / sections / facts
    YAML) is the extractor's concern via `knowledge/records/extraction.md`.
    """

    RECORD_TYPE = "record"

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx

    def ingest(self, body: str, url: str, op_area: str = "reality") -> str | None:
        """Validate the submission-time guards and save through ctx.storage.

        Reality records only. Intents go through `ingest_intent` so the
        sidecar state row is created atomically with the records row.

        The body's `Date:` line is parsed into `metadata.source_at` (ISO
        timestamp string) so extraction can thread it through onto every
        extracted fact, instead of falling back to the row's insert time.
        """
        if not body or not body.strip():
            raise RecordSubmissionError("body is empty")
        if not url or not url.strip():
            raise RecordSubmissionError("url is required and must be non-empty")
        if op_area not in VALID_OP_AREAS:
            raise RecordSubmissionError(
                f"op_area must be one of {VALID_OP_AREAS}, got {op_area!r}. "
                "Use `submit_intent` for intent records."
            )

        id_match = _ID_RE.search(body)
        if id_match is None:
            raise RecordSubmissionError("body missing required `Id:` line")
        date_match = _DATE_RE.search(body)
        if date_match is None:
            raise RecordSubmissionError("body missing required `Date:` line")

        source_at = _parse_record_date(date_match.group(1))

        return self._ctx.storage.save_record(
            record_type=self.RECORD_TYPE,
            raw=body,
            content=body,
            metadata={
                "op_area": op_area,
                "source_url": url,
                "source_at": source_at.isoformat(),
            },
            dedup_key=id_match.group(1).strip(),
        )

    def ingest_intent(
        self,
        body: str,
        parent_record_id: str | None = None,
        intent_type: str = "executor",
        owner: str | None = None,
        owner_role: str | None = None,
        depends_on: list[str] | None = None,
        set_by: str | None = None,
    ) -> str:
        """Submit an intent — record + sidecar row created atomically.

        `intent_type` is the dispatch lifecycle (`"executor"` | `"coordinator"`);
        validated by the storage layer.
        """
        from pearscarf.storage import intents

        return intents.submit_intent(
            body=body,
            parent_record_id=parent_record_id,
            intent_type=intent_type,
            owner=owner,
            owner_role=owner_role,
            depends_on=depends_on,
            set_by=set_by,
        )


def get_handler(ctx: ExpertContext) -> RecordsExpert:
    """Factory called by startup: build the records expert with its context."""
    return RecordsExpert(ctx)
