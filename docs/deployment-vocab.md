# Deployment vocabulary

Pearscarf ships with a small anchor set of entity types
(`person`, `company`, `project`, `event`) and fact_types (per-edge-label
in `pearscarf/storage/graph.py FACT_CATEGORIES`). Operators extend the
vocabulary specific to their deployment without forking the framework
or attaching the additions to a record-source expert.

## Mechanism

Set `DEPLOYMENT_VOCAB_PATH` to a `vocab.yaml`. Pearscarf loads it at
startup, merges declared types into `_LABELS` and `FACT_CATEGORIES`,
and surfaces declared entity types in the seed-extraction prompt as
recognised sections.

When `DEPLOYMENT_VOCAB_PATH` is unset, behaviour is unchanged.

## `vocab.yaml` format

```yaml
entity_types:
  - name: sub_system
    description: A deployed service or component in this stack.
    section: sub_systems   # optional; defaults to f"{name}s"

  - name: data_store
    description: Persistent storage backend.

fact_types:
  AFFILIATED:
    - name: component_of
      description: A is a structural component of B.
    - name: runs_on
      description: A's operational substrate is B.

  TRANSITIONED:
    - name: attribute_change
      description: A property or configuration of an entity changed.
```

`entity_types[].name` is the canonical type name (snake_case). The
Neo4j label is derived as `name[0].upper() + name[1:]`, e.g.
`sub_system` → `:Sub_system`. The optional `section` overrides the
default plural section name in seed files (default: `name + "s"`).

`fact_types` are merged by edge label. Only the three canonical edge
labels (`AFFILIATED`, `ASSERTED`, `TRANSITIONED`) are valid keys; other
keys are ignored.

## How seed files use it

Once `sub_system` is declared, a seed file can declare entities of that
type via the convention section:

```markdown
## sub_systems

psc-mcp | HTTP MCP server exposing graph queries.
psc-postgres | Postgres 16 container.
```

The seed-extraction prompt picks up the `## sub_systems` section
automatically — no other configuration needed.
