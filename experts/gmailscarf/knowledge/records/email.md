# Email record

The Gmail connector pushes email records onto the PearScarf bus. Each
record corresponds to one Gmail message and is stored in the `emails`
table joined to a row in `records`.

## Fields

| Field | Type | Description |
|---|---|---|
| `record_id` | text | PearScarf record identifier (e.g. `email_042`) |
| `message_id` | text | Gmail's message ID — used for deduplication |
| `sender` | text | The From: header, formatted as "Name <addr@domain>" |
| `recipient` | text | The primary To: header |
| `subject` | text | Email subject line |
| `body` | text | Plain text body, with quoted history preserved |
| `received_at` | timestamp | Server-side received time |

## Identity

An email is uniquely identified by `message_id` (Gmail's internal ID).
The connector dedups against this column before saving — re-polling the
same inbox never produces duplicate records.

## Source-of-truth boundaries

Headers are structured data. Subject and recipient are already separated
from the body before extraction sees the record. Extraction should not
re-extract sender/recipient as entities just because they appear in the
headers — they appear there because the protocol puts them there, not
because the human wrote them as content.

The body is the only field that contains free-form human-written
content. Extraction lives or dies on what the body says.
