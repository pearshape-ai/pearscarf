# Issue record

The Linear connector pushes issue records onto the PearScarf bus. Each
record corresponds to one Linear issue and is stored in the `issues`
table joined to a row in `records`.

## Fields

| Field | Type | Description |
|---|---|---|
| `record_id` | text | PearScarf record identifier (e.g. `issue_042`) |
| `linear_id` | text | Linear's internal issue UUID — used for deduplication |
| `identifier` | text | Human-readable ID (e.g. `ENG-42`) |
| `title` | text | Issue title |
| `description` | text | Issue description (markdown) |
| `status` | text | Workflow state name (e.g. `In Progress`, `Done`) |
| `priority` | text | Priority label (e.g. `Urgent`, `High`) |
| `assignee` | text | Assignee display name |
| `project` | text | Project name |
| `labels` | jsonb | Array of label name strings |
| `comments` | jsonb | Array of `{author, body, created_at}` |
| `url` | text | Issue URL on linear.app |
| `linear_created_at` | timestamp | When the issue was created in Linear |
| `linear_updated_at` | timestamp | When the issue was last updated in Linear |

## Identity

An issue is uniquely identified by `linear_id` (Linear's internal UUID).
The connector dedups against this column before saving — re-polling
never produces duplicate records.

## Source-of-truth boundaries

Status, priority, assignee, project, and labels are **structured data**.
They are stored separately in the issues table. Extraction does not need
to (and should not) re-extract them as entities or facts — they are
context, not substance.

The unstructured content lives in `description` and `comments`. That's
where free-form human-written content is. Extraction lives or dies on
what those fields say.

## Source timing

For facts derived from issue records, `source_at` should be set to
`linear_created_at` — the moment the issue came into existence — not
the indexing time. This preserves temporal accuracy when issues are
created in the past and indexed later.
