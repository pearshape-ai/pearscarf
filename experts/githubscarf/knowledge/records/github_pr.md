# Pull request record

The GitHub connector pushes PR records onto the PearScarf bus. Each
record corresponds to one pull request.

## Fields

| Field | Type | Description |
|---|---|---|
| `record_id` | text | PearScarf record identifier (e.g. `github_pr_001`) |
| `github_id` | integer | GitHub's internal PR ID — used for deduplication |
| `number` | integer | PR number (e.g. #42) |
| `title` | text | PR title |
| `body` | text | PR description — markdown, may contain motivation and test plan |
| `state` | text | open, closed, or merged |
| `author` | text | GitHub username of the PR author |
| `branch` | text | Feature branch name |
| `base_branch` | text | Target branch (usually main) |
| `labels` | array | Label names |
| `reviewers` | array | Requested reviewer usernames |
| `url` | text | GitHub URL |
| `created_at` | timestamp | When the PR was opened |
| `updated_at` | timestamp | Last activity |
| `merged_at` | timestamp | When merged (empty if not merged) |

## Identity

A PR is uniquely identified by `github_id`. The connector dedups
against this field before saving.

## Source-of-truth boundaries

Metadata fields (author, branch, state, labels) are structured.
The `body` is where free-form human-written content lives —
motivation, design decisions, test plans, and context. Extraction
should focus on the body.
