# GitHub issue record

The GitHub connector pushes issue records onto the PearScarf bus. Each
record corresponds to one GitHub issue (not a pull request).

## Fields

| Field | Type | Description |
|---|---|---|
| `record_id` | text | PearScarf record identifier (e.g. `github_issue_001`) |
| `github_id` | integer | GitHub's internal issue ID — used for deduplication |
| `number` | integer | Issue number (e.g. #15) |
| `title` | text | Issue title |
| `body` | text | Issue description — markdown, may contain bug reports or feature requests |
| `state` | text | open or closed |
| `author` | text | GitHub username of the issue author |
| `assignees` | array | Assigned usernames |
| `labels` | array | Label names |
| `url` | text | GitHub URL |
| `created_at` | timestamp | When the issue was opened |
| `updated_at` | timestamp | Last activity |
| `closed_at` | timestamp | When closed (empty if open) |

## Identity

An issue is uniquely identified by `github_id`. The connector dedups
against this field before saving.

## Source-of-truth boundaries

Metadata fields (author, assignees, state, labels) are structured.
The `body` is where free-form content lives — bug descriptions,
feature requests, reproduction steps, and context. Extraction
should focus on the body and title.
