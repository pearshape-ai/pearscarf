# Claude Code Context

## Read first

Before touching any code, read:

- `README.md` — what PearScarf is, what it does, how to run it
- `docs/` — read all files here for architecture context. You will find:
  - `architecture.md` — data model, design principles, system overview
  - `context_query.md` — the read layer; what to call and what not to call directly
  - `eval.md` — scorer, runner, ground truth format, metrics (relevant for eval work)
- `CHANGELOG.md` — read the latest entry only; tells you the current version and what just changed

---

## How to work

Work is either driven by a Linear issue or by a direct instruction in the session.

**When working from a Linear issue:**
- Read the issue before touching any code — it is the source of truth for what to build and why
- The issue has a parent epic — read it too; it holds the high-level intent and the decisions that shaped the issue
- Work through the issue's changes one at a time, in order
- Mark the issue Done once all changes are verified and committed

**When working from a direct instruction (debugging, exploration, ad-hoc):**
- Confirm your understanding of what's being asked before making changes
- Keep changes small and targeted — do not over-reach
- Still verify and commit after each meaningful change

In both cases: one change at a time, verify before moving on, never batch.

---

## Verification

Verification means confirming that the change you just made works as intended and hasn't broken anything adjacent. It is not optional.s

After every meaningful change:
- Run the most direct check available — if the change touches a specific function, call it; if it touches a pipeline, run it end to end on a small input
- Confirm the output matches the expected behaviour described in the issue or instruction
- Confirm nothing adjacent broke — run a broader check if the change touched shared code
- Do not proceed to the next change until the current one is confirmed working

If verification fails, fix it before moving on. Do not accumulate unverified changes.

---

## Chores (always, after every issue)

- Update `docs/` to reflect any changed behaviour
- Update `README.md` if the change affects public-facing usage or CLI output
- Add an entry to `CHANGELOG.md` for the version

---

## What NOT to do

- Do not make changes beyond what the issue or instruction asks — stay in scope
- Do not move to the next change before verifying the current one
- Do not generate a plan document unless explicitly asked — read the issue and work directly
- Do not make assumptions about intent when something is ambiguous — ask
- Do not commit broken code — every commit should leave the project in a working state
- For project-specific constraints and architectural boundaries, refer to `docs/architecture.md`