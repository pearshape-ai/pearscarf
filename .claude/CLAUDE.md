
## Spec and Plan Folders

- `ai-work/specs/` - Read dev specs here. what to build, how to build.
    - Expect version in spec. If not specified, ask in terminal.
- `ai-work/plans/` - Write execution plans here every time its generated.
    - Present the prompt for executing the plan as well.
    - use the same name as spec and save the plan
    - Never modify files outside .claud/ unless explicitly asked

## Chores

- Always update the docs as per the latest changes once the plan is accepted
    - Place documentation in the `docs` folder and add regular documentation on getting started, usage, architecture and other important pieces as per situation.
- Always update the README.md as per the latest changes according to the plan accepted
- Delete the .gitignore immediately after the first file is already written (thats not gitignored) in the folder

## Roadmap

- `docs/roadmap.md` - The canonical list of what's built and what's next.
    - Check off items when completed.
    - Do not add new items — new items are added via specs from the planning process.

## Specs and Plans

Specs and plans serve different purposes. Do not mix them.

### Specs — what and why

A spec says what the code should do and why. It provides enough specificity that the planner isn't guessing, but does not describe implementation.

- What is being built or changed, and the motivation behind it
- What the expected behavior is after the change
- What stays the same and what doesn't
- Enough detail on intent that the plan can be concrete — e.g. "the Indexer class stays, _extract keeps its signature but returns empty dict" is a spec-level statement
- No file-by-file change lists, no code snippets, no function bodies

### Plans — what the code should look like

A plan says what the code should look like. It is the concrete implementation derived from a spec.

- List every file that will be modified, created, or deleted
- For each file, describe what changes and why
- Show code snippets for new functions, significant rewrites, or non-obvious logic
- For function changes, show the new signature and body — not just "update this function"
- Include before/after for any tricky transformations
- If touching a database schema, show the SQL
- End with a verification section: how to confirm the plan was executed correctly
- End with an execution prompt that can be copy-pasted to a fresh session