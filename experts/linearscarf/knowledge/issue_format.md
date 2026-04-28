# Linear issue format

PearScarf's linearscarf expert ingests Done Linear issues as reality records. To keep the resulting graph precise, every Done issue should follow the format below.

## Why two sections

Linear issues serve two audiences:

- **Humans** clicking through the issue want a narrative — what changed, why, how at a high level.
- **Agents** (linearscarf's extractor) turn each Done issue into graph facts.

A single prose narrative serves neither well. The format makes the boundary explicit: `## For humans` for prose, `## For agents` for a YAML fact block. The agent block is optional — without it the body is extracted as prose with reasonable defaults — but its presence makes extraction precise and operator-controlled.

## Format

````
Title: <verb-phrase describing the change, scope-clear>

Shipped in <repo> <version>.

## For humans

<Prose paragraph(s). What changed, why it matters, how it works at a
high level. No code, no file paths.>

## For agents

```yaml
facts:
  - subject: <entity name>
    edge_label: TRANSITIONED | ASSERTED | AFFILIATED
    fact_type: <lower_snake_case>
    target: <entity name | (Day)>
    fact_text: <readable English sentence>
```
````

## Field guide for `## For agents`

- **`subject`**: the entity that has the property or did the action. Usually the repo, sub-system, or component the issue is about. Resolved against the graph by name.

- **`edge_label`**: one of three foundational labels.
  - `TRANSITIONED` — events that happened on a specific date (something shipped, deployed, transitioned, was created). Almost always paired with `target: (Day)`.
  - `AFFILIATED` — structural / relational facts (X is a component of Y, X uses Y, X is owned by Y). Paired with another entity as `target`.
  - `ASSERTED` — state-of-the-world facts that aren't structural (X is configured as Y, X has property Z). Target is usually an entity; occasionally `(Day)` when the assertion is time-anchored.

- **`fact_type`**: `lower_snake_case`. Use a canonical type when one fits (`feature_shipped`, `component_of`, `runs_on`, `ingests_from`, …); otherwise propose a new one. PearScarf treats `fact_type` as an anchor-set with extensibility — novel types are accepted and flagged for the curator.

- **`target`**:
  - **`(Day)`** for time-anchored facts. The day node resolves to the date the issue was recorded. Pair with `TRANSITIONED` for events.
  - **An entity name** for relational facts. Resolved by name against the graph; a new entity is created only if no match exists. Pair with `AFFILIATED` or `ASSERTED` for relationships between entities.

- **`fact_text`**: readable English. Anchor on `<repo> <version>` for shipping events. Imagine it being read out loud as a graph fact.

## Writing guidance

- **Title**: verb-phrase. No version numbers (those live in the body), scope-clear at a glance.
- **`## For humans`**: prose. One or two paragraphs is plenty — what was the world like before, what's different now, why it mattered, how it works at a high level.
- **`## For agents`**: prefer one TRANSITIONED fact per issue (the shipping event itself). Add ASSERTED / AFFILIATED facts only when they encode information not implicit in the TRANSITIONED fact. Skip metadata restatements (assignee, project, status are already structural).

## Examples

### Shipping event (target = `(Day)`)

The most common shape — a Done issue describing what shipped:

````
Title: Seed ingestion produces readable fact text

Shipped in pearscarf 1.27.10.

## For humans

Before 1.27.10 the seed extraction prompt under-specified how to
write fact text and the LLM fell back to copying the seed source
line verbatim. Every seed fact ended up as an encoded tuple instead
of a sentence, which degraded answer quality wherever an agent
grounded its response on seed-derived facts.

## For agents

```yaml
facts:
  - subject: pearscarf
    edge_label: TRANSITIONED
    fact_type: feature_shipped
    target: (Day)
    fact_text: Seed ingestion produces readable fact text — shipped in pearscarf 1.27.10
```
````

### Structural relationship (target = entity) and shipping event combined

When an issue both ships a change and declares a structural relationship between entities, multiple fact entries can coexist:

````
Title: linearscarf restricts ingestion to Done issues

Shipped in linearscarf 0.1.6.

## For humans

linearscarf now polls only Done issues. The consumer initialises its
sync state to start time, so no historical issues are pulled — only
new Done transitions are captured going forward.

## For agents

```yaml
facts:
  - subject: linearscarf
    edge_label: TRANSITIONED
    fact_type: behavior_changed
    target: (Day)
    fact_text: linearscarf restricted ingestion to Done issues — shipped in linearscarf 0.1.6
  - subject: linearscarf
    edge_label: AFFILIATED
    fact_type: ingests_from
    target: Linear
    fact_text: linearscarf ingests Done issues from Linear via the GraphQL API
```
````
