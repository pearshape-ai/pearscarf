# Contributing to PearScarf

Thanks for considering a contribution. PearScarf is MIT-licensed and welcomes bug reports, patches, and new experts.

## Contributor License Agreement

Every contributor signs a CLA before their first merge. It's administered via [cla-assistant.io](https://cla-assistant.io/) — the bot will comment on your pull request with a one-click sign-in flow the first time you contribute.

The CLA grants the project a license to use your contribution under the current license (MIT) and any future license. You retain copyright on everything you contribute.

## How to contribute

- **Bugs** — open a GitHub issue with a reproducer.
- **Patches** — fork, branch, open a pull request. Keep commits small and focused; one concern per commit is ideal.
- **New experts** — see [docs/expert_guide.md](docs/expert_guide.md). Experts can live in-tree under `experts/` or as separate packages.

## Development setup

Short version (full walkthrough in [docs/getting-started.md](docs/getting-started.md)):

```bash
uv sync
source .venv/bin/activate
docker compose up -d postgres qdrant neo4j
psc install ./experts/gmailscarf
psc run
```

## Checks before submitting

Run the integration smoke test:

```bash
psc integration-test
```

## Questions

Open an issue.
