# Issue change record

The Linear connector pushes issue change records as a side effect of
polling. Each record corresponds to one history event on a Linear issue
(status change, assignee change, priority change, etc.) and is stored
in the `issue_changes` table joined to a row in `records`.

## Fields

| Field | Type | Description |
|---|---|---|
| `record_id` | text | PearScarf record identifier (e.g. `change_017`) |
| `issue_record_id` | text | The parent issue's `record_id` |
| `linear_history_id` | text | Linear's internal history event ID — used for deduplication |
| `field` | text | Which field changed (e.g. `state`, `assignee`, `priority`) |
| `from_value` | text | Previous value (display string) |
| `to_value` | text | New value (display string) |
| `changed_by` | text | Display name of the user who made the change |
| `changed_at` | timestamp | When the change happened in Linear |

## Identity

A change is uniquely identified by `linear_history_id`. The connector
dedups against this column before saving.

## Extraction model

A change is a single transition in time. Extraction for change records
should produce at most one TRANSITIONED fact:

- `field=state` → `TRANSITIONED/status_change` from the project entity, fact text describes the transition (e.g. "moved from In Progress to In Review")
- Other field changes are usually noise — extract only when there is concrete operational meaning

## Source timing

For facts derived from change records, `source_at` should be set to
`changed_at` — the moment the change happened — not the indexing time.
