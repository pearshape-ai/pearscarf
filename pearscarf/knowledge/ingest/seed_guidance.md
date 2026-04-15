## Seed record guidance

Seed files declare the known world state before any records are processed. They use structured markdown with pipe-delimited sections.

### Sections

**`## people`** — one person per line: `name | role | email`
**`## companies`** — one company per line: `name | domain`
**`## projects`** — one project per line: `name`
**`## facts`** — one fact per line: `from_entity | EDGE_LABEL/fact_type | to_entity`
**`## aliases`** — one alias declaration per line: `canonical_name | alias1 | alias2 | ...`

### Rules

- Every line in people/companies/projects is an entity — extract all of them, never skip
- Every line in facts is a fact — extract all of them
- All seed content is declared ground truth — confidence is always `stated`
- `valid_until` is always `null`
- Capitalize entity names correctly: "Elena Vasquez" not "elena vasquez"
- Put email and role in person metadata, domain in company metadata
- For facts, generate a short self-contained fact text from the three fields

### Aliases

For each line in `## aliases`, the first name is the canonical entity. Every subsequent name is a surface form alias. Include each alias as a separate entity in the output with:
- `resolved_to`: set to "new" (the canonical entity is being created in the same extraction)
- `canonical_name`: the canonical entity name

Example: `Elena Vasquez | Elena | E. Vasquez` produces two alias entities:
- `{"name": "Elena", "type": "person", "resolved_to": "new", "canonical_name": "Elena Vasquez"}`
- `{"name": "E. Vasquez", "type": "person", "resolved_to": "new", "canonical_name": "Elena Vasquez"}`
