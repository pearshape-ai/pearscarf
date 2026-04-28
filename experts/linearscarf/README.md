# linearscarf

linearscarf is the Linear expert for PearScarf. It polls Linear via the GraphQL API, ingests Done issues as reality records, and tags each record with `metadata.op_area = "reality"` so downstream extraction can thread the marker onto fact edges.

## Issue format

Every Done Linear issue ingested by linearscarf should follow the format documented in [`knowledge/issue_format.md`](knowledge/issue_format.md): a markdown body with a `## For humans` prose section and a `## For agents` YAML fact block. The format is loadable as a prompt by any agent that reads or writes Linear issues for this deployment.

## Why this format

**For humans.** A closed Linear issue should read as a human-friendly summary — what shipped, why it mattered, how it works. Without a dedicated narrative space the body devolves into either a code diff or a bullet list, neither of which is useful when someone clicks through the issue later.

**For agents.** The `## For agents` section adds precision to how the record is ingested into the context graph. The record will still be parsed without it — the extractor reads the prose and produces a best-effort set of facts — but with the section in place, there is almost no chance for noise or imprecision in the resulting context.
