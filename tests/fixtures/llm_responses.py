"""Canned LLM responses for the test harness.

Tests register entries by setting RESPONSES[key] = json_string before
calling code that triggers an LLM request. The conftest mock looks up
the key in the system prompt being sent — first match wins.

Use distinctive substrings as keys (e.g. "extract entities" or "entity
resolution judge") so the routing is unambiguous.
"""

RESPONSES: dict[str, str] = {}
