# Reading PearScarf — how to ground yourself

PearScarf is the shared operational graph — the one place every agent converges for the truth about the operation. Before you act, you read it. Reading it *well* is a skill, and this is the guide. (Its mirror is the submission discipline: how you record what you ship.)

## 1. What you're querying — the model

- **Everything you get back is a fact** — the atomic unit of operational change, the currency you reason in. Not documents, not opinions: current, normalized facts.
- **The graph is the authority on "now."** A fact you retrieve is true *currently* unless you explicitly ask for stale ones. You never have to second-guess freshness.
- **Records are provenance, not the answer.** Every fact links back to the record it came from. Open the record for the *why* and the texture — but the fact is the truth, the record is the receipt.
- **Facts are what *happened*; intents are what's *planned*.** Two surfaces. The fact graph is reality (`recall` / `query_facts`); the intent DAG is committed-but-maybe-unfinished work (`query_intents` / `get_intent_tree`). Grounding on "what's the state of X" usually means reading *both* — what shipped *and* what's in flight.
- **Absence is not nonexistence.** An empty result means the truth isn't recorded — *or it's outside your scope.* Never read silence as "this doesn't exist anywhere."

## 2. How to query well — the method

You enter the graph through one of a few doors. Pick by the shape of your need.

- **Ground on a task or topic** (most common) → `recall("<your task in plain language>")`. Returns the matching facts plus the **entities and records** they involve. Those entities are your next hops — read them.
- **Get up to speed on the whole operation** (broad / "where do we stand") → *don't* use recall. Sweep with structured queries: recent change (`query_facts(edge_label=TRANSITIONED, since=…)`), open obligations (`query_facts(edge_label=ASSERTED, fact_type=blocker|commitment)`), work in flight (`query_intents(status=in_progress)`). Synthesize.
- **Go deep on a known entity** → `get_entity_context("<name>")`. If it reports resolving to something other than what you meant (`resolved_to` / `alternatives`), correct course — don't proceed on the wrong entity.
- **How two things connect** → `get_relationship("a", "b")`.

### The loop — first hits are never the whole picture

A `recall` is **precise but narrow**: it returns facts from the records that matched, not the full current state of everything they mention. So:

1. `recall` on your task.
2. Note the entities that matter in the hits.
3. `get_entity_context` on each → their full current state.
4. New entities surfaced? Repeat.
5. *Then* act.

### Knowing when to stop

You are grounded when you can **name the specific facts that answer your task**, and no entity in your working set is still unexplored — *not* when the first recall returns something plausible. Under-querying is how agents fabricate; over-querying burns the session. Stop at "I can cite it."

## 3. What you must never do — the guardrails

- **Never fabricate.** If the graph doesn't have it, it isn't known. Omit it, query again, or surface a `[NEEDS OPERATOR INPUT]` note — never fill the gap with a plausible pattern from your training (`pip install …`, `contact sales`, "on the App Store"). A vague-but-true line beats a specific-but-wrong one.
- **Never conclude from a single hit.** Expand before you act.
- **Never trust a name blindly.** Confirm the entity you got is the entity you meant.
- **Stay within your scope.** You see what your scope permits. Don't treat scoped-out absence as global truth, and never try to route around the filter.
- **Halt if the MCP is unreachable.** Surface to the operator; never proceed on memory.
