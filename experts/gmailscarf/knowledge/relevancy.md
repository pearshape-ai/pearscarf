Relevancy guidance for Gmail records.

Gmail is hooked to the outside world. The hard filter inside this expert already strips the obvious automated and bulk noise (no-reply senders, list-unsubscribe headers, bounces). What reaches you is the ambiguous middle: personal-looking email that may or may not matter to this deployment.

## Keep as relevant

- Direct human correspondence with a sender or recipient already in the graph
- Replies in an ongoing thread — continuity matters even if the individual message is terse
- Messages that mention a known project, company, or deal by name
- Messages with an explicit commitment (a date, a deliverable, a decision)
- Meeting invites or confirmations tied to known entities
- Calendar-like content about specific, time-bound events in the operational world

## Discard as noise

- Marketing, newsletters, and sales outreach that slipped past the hard filter
- "Thanks for signing up" / "Your account is ready" transactional mail unrelated to operational work
- Automated status emails from services (CI, monitoring, billing) that duplicate information already in other sources
- Cold outreach from senders not in the graph, with no reference to known entities or operational work

## Flag as uncertain

- Unknown sender, personally written, but no anchor in the world (often early customer contact or a new relationship worth a human glance)
- Known sender writing about something unrelated — could be personal, could be a side channel worth noting
- Forwards and quoted mail where the real content belongs to someone outside the graph
- Anything where the signal is subtle and the cost of a wrong auto-decision is higher than a human glance

When in doubt, choose `uncertain`. Let a human decide rather than pollute or lose signal.
