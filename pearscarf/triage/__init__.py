"""Triage — decides whether a record is relevant, noise, or uncertain.

The triage agent drains records with classification = 'pending_triage',
runs an LLM check grounded in onboarding + per-expert relevancy guidance
+ read-only graph context, and sets the final classification. Uncertain
records sit in the HIL queue until the human-facing path lands.
"""
