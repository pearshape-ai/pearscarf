## GitHub extraction guidance

GitHub records come in two types: pull requests and issues.

### Pull requests

- `author` — the person who opened the PR
- `title` — the PR title, often a short description of the change
- `body` — the PR description, may contain context, motivation, test plan
- `branch` — the feature branch name
- `reviewers` — requested reviewers

Extract from the body, not the metadata fields.

#### What to extract from PRs

- **People involved.** Author and reviewers are in metadata — only extract people mentioned by name in the body if they add new information.
- **Decisions and rationale.** PR descriptions often explain why a change was made — these are ASSERTED/decision facts.
- **Blockers and dependencies.** "Blocked on X" or "Depends on #123" are ASSERTED/blocker facts.
- **Scope descriptions.** "This PR adds/removes/changes X" describes what changed in the codebase.

### Issues

- `author` — the person who opened the issue
- `title` — the issue title
- `body` — the issue description
- `assignees` — people assigned to work on it
- `labels` — categorization labels

#### What to extract from issues

- **People mentioned in the body.** Same rule as PRs — only extract if they add new info beyond the metadata.
- **Bug reports and feature requests.** The title + body describe what's broken or requested.
- **Commitments.** "Will fix by Friday" or assignee implies ownership.
- **Status transitions.** Open → closed implies resolution.

### GitHub-specific noise to ignore

- Bot-generated comments (dependabot, CI status updates)
- Template boilerplate that wasn't filled in
- Auto-generated changelogs and release notes
