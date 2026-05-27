"""Tests for `pearscarf.records.RecordsExpert.ingest` validation paths.

The ingest path validates body/url/op_area then delegates to
`ctx.storage.save_record`. These tests cover the validation branches with a
mocked context — no DB involved.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from pearscarf.expert_context import ExpertContext
from pearscarf.records import RecordsExpert, RecordSubmissionError

VALID_BODY = """\
Title: Test record

Id: test-record-20260510
Date: 2026-05-10

Anchor.

## For humans

Some prose.

## For agents

```yaml
facts:
  - Some fact about something.
```
"""


def _expert_with_mock_storage() -> tuple[RecordsExpert, MagicMock]:
    """Return a RecordsExpert wired to a Mock storage."""
    ctx = MagicMock()
    ctx.storage.save_record.return_value = "record_test123"
    return RecordsExpert(cast("ExpertContext", ctx)), ctx.storage.save_record


# ---- validation rejections ----


def test_empty_body_raises() -> None:
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="body is empty"):
        expert.ingest("", "https://example.com/x", "reality")


def test_whitespace_only_body_raises() -> None:
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="body is empty"):
        expert.ingest("   \n\n   ", "https://example.com/x", "reality")


def test_empty_url_raises() -> None:
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="url is required"):
        expert.ingest(VALID_BODY, "", "reality")


def test_invalid_op_area_raises() -> None:
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="op_area must be one of"):
        expert.ingest(VALID_BODY, "https://example.com/x", "bogus")


def test_body_missing_id_raises() -> None:
    expert, _ = _expert_with_mock_storage()
    body = "Title: x\n\nDate: 2026-05-10\n\nAnchor."
    with pytest.raises(RecordSubmissionError, match=r"missing required `Id:` line"):
        expert.ingest(body, "https://example.com/x", "reality")


def test_body_missing_date_raises() -> None:
    expert, _ = _expert_with_mock_storage()
    body = "Title: x\n\nId: x123\n\nAnchor."
    with pytest.raises(RecordSubmissionError, match=r"missing required `Date:` line"):
        expert.ingest(body, "https://example.com/x", "reality")


# ---- happy path ----


def test_valid_input_calls_storage_with_correct_args() -> None:
    expert, save_record = _expert_with_mock_storage()
    result = expert.ingest(VALID_BODY, "https://example.com/x", "reality")
    assert result == "record_test123"

    save_record.assert_called_once_with(
        record_type="record",
        raw=VALID_BODY,
        content=VALID_BODY,
        metadata={
            "op_area": "reality",
            "source_url": "https://example.com/x",
            "source_at": "2026-05-10T00:00:00+00:00",
        },
        dedup_key="test-record-20260510",
    )


def test_ingest_rejects_intent_op_area() -> None:
    """submit_record is reality-only; intents go through submit_intent."""
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="submit_intent"):
        expert.ingest(VALID_BODY, "https://example.com/x", "intent")


# ---- Date parsing ----


def _body_with_date(date_value: str) -> str:
    return VALID_BODY.replace("Date: 2026-05-10", f"Date: {date_value}")


def test_date_with_utc_z_is_parsed_with_time() -> None:
    expert, save_record = _expert_with_mock_storage()
    expert.ingest(_body_with_date("2026-05-12T14:33:51Z"), "https://x", "reality")
    metadata = save_record.call_args.kwargs["metadata"]
    assert metadata["source_at"] == "2026-05-12T14:33:51+00:00"


def test_date_with_offset_is_normalized_to_utc() -> None:
    expert, save_record = _expert_with_mock_storage()
    expert.ingest(_body_with_date("2026-05-12T07:33:51-07:00"), "https://x", "reality")
    metadata = save_record.call_args.kwargs["metadata"]
    # Offsets are converted to UTC at ingest so every stored source_at shares
    # one zone — 07:33:51-07:00 is the same instant as 14:33:51Z.
    assert metadata["source_at"] == "2026-05-12T14:33:51+00:00"


def test_date_only_becomes_midnight_utc() -> None:
    expert, save_record = _expert_with_mock_storage()
    expert.ingest(_body_with_date("2026-05-12"), "https://x", "reality")
    metadata = save_record.call_args.kwargs["metadata"]
    assert metadata["source_at"] == "2026-05-12T00:00:00+00:00"


def test_naive_datetime_rejected() -> None:
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="must include a timezone"):
        expert.ingest(_body_with_date("2026-05-12T14:33:51"), "https://x", "reality")


def test_garbage_date_rejected() -> None:
    expert, _ = _expert_with_mock_storage()
    with pytest.raises(RecordSubmissionError, match="not a valid ISO 8601"):
        expert.ingest(_body_with_date("yesterday afternoon"), "https://x", "reality")
