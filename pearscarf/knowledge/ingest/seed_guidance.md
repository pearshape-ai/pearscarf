## Seed record guidance

Seed files declare known world state before any records are processed. They use structured markdown with pipe-delimited sections.

### Sections

**`## people`** — one person per line: `name | role | email`
**`## companies`** — one company per line: `name | domain`
**`## projects`** — one project per line: `name`
{{deployment_entity_sections}}
**`## facts`** — one fact per line: `from_entity | EDGE_LABEL/fact_type | to_entity | optional fact text`
**`## aliases`** — one alias declaration per line: `canonical_name | alias1 | alias2 | ...`

### Rules — entities

- Every line in people/companies/projects is an entity — extract all of them, never skip
- All seed content is declared ground truth — confidence is always `stated`
- `valid_until` is always `null`
- Capitalize entity names correctly: "Elena Vasquez" not "elena vasquez"
- Put email and role in person metadata, domain in company metadata

### Rules — facts

Every line in `## facts` is a fact. Extract all of them.

Each fact line has **3 or 4** pipe-delimited columns:
- 3 columns: `from_entity | EDGE_LABEL/fact_type | to_entity`
- 4 columns: `from_entity | EDGE_LABEL/fact_type | to_entity | fact text`

**If a 4th column is present, use it VERBATIM as the fact's `fact` text.** Do not modify, paraphrase, or shorten it. The operator wrote that text precisely so downstream agents can read it.

**If only 3 columns are present, generate a short self-contained sentence as the fact text.** The sentence should:
- Use the from-entity and to-entity names directly
- Read as natural English
- Make the relationship type explicit

Examples of good generated fact text:
- `Elena Vasquez | AFFILIATED/employee | Brightlane` → `"Elena Vasquez is employed at Brightlane"`
- `Crestwood Onboarding | AFFILIATED/sub_project | Brightlane` → `"Crestwood Onboarding is a sub-project of Brightlane"`
- `Tom Hayward | AFFILIATED/contributor | Crestwood Onboarding` → `"Tom Hayward contributes to the Crestwood Onboarding project"`

**ANTI-PATTERN — never copy the pipe-separated source line as the fact text.** The fact's `fact` field must NEVER contain `|` characters from the source format. The fact text is what downstream agents read; a pipe-encoded tuple is not readable English.

WRONG: `"Tom Hayward | AFFILIATED/contributor | Crestwood Onboarding"`
RIGHT: `"Tom Hayward contributes to the Crestwood Onboarding project"`

### Aliases

For each line in `## aliases`, the first name is the canonical entity. Every subsequent name is a surface form alias. Include each alias as a separate entity in the output with:
- `resolved_to`: set to "new" (the canonical entity is being created in the same extraction)
- `canonical_name`: the canonical entity name

Example: `Elena Vasquez | Elena | E. Vasquez` produces two alias entities:
- `{"name": "Elena", "type": "person", "resolved_to": "new", "canonical_name": "Elena Vasquez"}`
- `{"name": "E. Vasquez", "type": "person", "resolved_to": "new", "canonical_name": "Elena Vasquez"}`
