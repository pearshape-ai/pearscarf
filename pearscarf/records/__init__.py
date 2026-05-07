"""Default record-capture expert. Records arrive via MCP submission.

Initialized at startup like any other expert (build_context → get_handler);
the resulting RecordsExpert instance is registered on the registry under
its record_type so the MCP server can retrieve it via `get_connect`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pearscarf.expert_context import ExpertContext

VALID_OP_AREAS = ("reality", "intention")

_ID_RE = re.compile(r"^Id:\s*(\S.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"^Date:\s*\S", re.MULTILINE)


class RecordSubmissionError(ValueError):
    """Raised when a submission fails the at-the-door guards."""


class RecordsExpert:
    """Receives MCP-submitted record bodies and saves them through the
    standard pipeline. Body shape (Title / Id / Date / sections / facts
    YAML) is the extractor's concern via `knowledge/records/extraction.md`.
    """

    RECORD_TYPE = "record"

    def __init__(self, ctx: ExpertContext) -> None:
        self._ctx = ctx

    def ingest(self, body: str, url: str, op_area: str = "reality") -> str | None:
        """Validate the submission-time guards and save through ctx.storage."""
        if not body or not body.strip():
            raise RecordSubmissionError("body is empty")
        if not url or not url.strip():
            raise RecordSubmissionError("url is required and must be non-empty")
        if op_area not in VALID_OP_AREAS:
            raise RecordSubmissionError(f"op_area must be one of {VALID_OP_AREAS}, got {op_area!r}")

        id_match = _ID_RE.search(body)
        if id_match is None:
            raise RecordSubmissionError("body missing required `Id:` line")
        if _DATE_RE.search(body) is None:
            raise RecordSubmissionError("body missing required `Date:` line")

        return self._ctx.storage.save_record(
            record_type=self.RECORD_TYPE,
            raw=body,
            content=body,
            metadata={"op_area": op_area, "source_url": url},
            dedup_key=id_match.group(1).strip(),
        )


def get_handler(ctx: ExpertContext) -> RecordsExpert:
    """Factory called by startup: build the records expert with its context."""
    return RecordsExpert(ctx)
