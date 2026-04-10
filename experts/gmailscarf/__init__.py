"""gmailscarf — Gmail expert agent for PearScarf.

Two runtime components:
- gmail_connect.py — API client + tool definitions (LLM agent surface)
- gmail_ingest.py — background ingestion loop (proactive, no LLM)

Both receive ExpertContext at startup. knowledge/agent.md is the LLM
system prompt.
"""
