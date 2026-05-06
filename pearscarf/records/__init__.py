"""Default record-capture expert. Records arrive via MCP submission."""

from __future__ import annotations

import re

from pearscarf.storage.store import save_record

EXPERT_NAME = "records"
EXPERT_VERSION = "0.1.2"
RECORD_TYPE = "record"
VALID_OP_AREAS = ("reality", "intention")


class RecordSubmissionError(ValueError):
    """Raised when a submission fails the at-the-door guards."""


_ID_RE = re.compile(r"^Id:\s*(\S.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"^Date:\s*\S", re.MULTILINE)


def ingest_record(body: str, url: str, op_area: str = "reality") -> str | None:
    """Save a submitted body through the standard pipeline.

    Body shape (Title / Id / Date / sections / facts YAML) is the
    extractor's concern via `knowledge/records/extraction.md`. This
    function only enforces submission-time provenance guards, then
    hands off to `save_record` like any other expert's ingester.
    """
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

    return save_record(
        record_type=RECORD_TYPE,
        raw=body,
        content=body,
        metadata={"op_area": op_area, "source_url": url},
        dedup_key=id_match.group(1).strip(),
        source=EXPERT_NAME,
        expert_name=EXPERT_NAME,
        expert_version=EXPERT_VERSION,
    )
