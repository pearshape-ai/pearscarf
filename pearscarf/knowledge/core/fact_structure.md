## Facts

A fact is a specific claim extracted from the record. It connects entities to each other or stands alone as a claim about a single entity.

**Two-entity facts** have both `from_entity` and `to_entity`:
- "Michael works at Acme" → AFFILIATED/employee, from "Michael Chen", to "Acme"
- "Integration blocked by Acme's API changes" → ASSERTED/blocker, from "Acme API Integration", to "Acme"

**Single-entity facts** have `from_entity` but `to_entity` is null:
- "Contract renews March 2026" → ASSERTED/commitment, from "Acme", to null
- "Priority escalated to Urgent" → TRANSITIONED/status_change, from "Acme API Integration", to null

**`valid_until`**: Set only when the fact text explicitly states a specific deadline, expiry, or renewal date. "Contract expires March 15" → `valid_until: "2026-03-15"`. If no specific date is stated, set to `null`. This is NOT the record's own timestamp.

**`fact` text**: Write a concise, self-contained sentence. Someone reading just the fact text should understand what happened without seeing the original record.

Every fact's `from_entity` (and `to_entity` if present) must match an entity name in the `entities` array exactly.

Don't force facts that aren't clearly stated. If two entities appear in the same record but have no stated connection, don't invent one.
