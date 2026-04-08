"""gmailscarf — Gmail expert agent for PearScarf.

The Gmail expert agent owns two-way access to a Gmail inbox: a connector
daemon that polls for new messages and pushes them onto the PearScarf
bus, an LLM-driven agent that reads, searches, and acts on emails via
Gmail tools, and the knowledge files the indexer uses when extracting
facts from email records.
"""
