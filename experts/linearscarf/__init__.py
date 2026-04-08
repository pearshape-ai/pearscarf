"""linearscarf — Linear expert agent for PearScarf.

The Linear expert agent owns two-way access to a Linear workspace: a
connector daemon that polls for issues and issue changes, an LLM-driven
agent that reads, searches, creates, updates, and comments on issues via
Linear tools, and the knowledge files the indexer uses when extracting
facts from issue records.
"""
