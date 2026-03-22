"""Indexer — background agent that processes records into the knowledge graph.

Polls for unindexed records and runs LLM extraction → entity resolution →
Neo4j graph population → Qdrant embedding.
"""

from __future__ import annotations

import json
import threading
import traceback

import anthropic

from pearscaff import graph, log, vectorstore
from pearscaff.config import (
    ANTHROPIC_API_KEY,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL,
    EXTRACTION_TEMPERATURE,
)
from pearscaff.db import _get_conn, init_db
from pearscaff.prompts import load as load_prompt
from pearscaff.tracing import trace_span


class Indexer:
    """Background agent that indexes records via LLM extraction."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
        self._system_prompt = load_prompt("extraction")

    def _build_content(self, record: dict) -> str:
        """Build the record content string for extraction."""
        record_type = record["type"]

        if record_type == "email":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT sender, recipient, subject, body, received_at "
                    "FROM emails WHERE record_id = %s",
                    (record["id"],),
                ).fetchone()
            if row:
                email = dict(row)
                parts = []
                if email["sender"]:
                    parts.append(f"From: {email['sender']}")
                if email["recipient"]:
                    parts.append(f"To: {email['recipient']}")
                if email["subject"]:
                    parts.append(f"Subject: {email['subject']}")
                if email["received_at"]:
                    parts.append(f"Date: {email['received_at']}")
                if email["body"]:
                    body = email["body"][:3000]
                    parts.append(f"\n{body}")
                return "\n".join(parts)

        elif record_type == "issue":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT identifier, title, description, status, priority, "
                    "assignee, project, labels, comments, "
                    "linear_created_at, linear_updated_at "
                    "FROM issues WHERE record_id = %s",
                    (record["id"],),
                ).fetchone()
            if row:
                issue = dict(row)
                parts = []
                if issue["identifier"]:
                    parts.append(f"Issue: {issue['identifier']}")
                if issue["title"]:
                    parts.append(f"Title: {issue['title']}")
                meta = []
                if issue["status"]:
                    meta.append(f"Status: {issue['status']}")
                if issue["priority"]:
                    meta.append(f"Priority: {issue['priority']}")
                if issue["assignee"]:
                    meta.append(f"Assignee: {issue['assignee']}")
                if meta:
                    parts.append(" | ".join(meta))
                if issue["project"]:
                    parts.append(f"Project: {issue['project']}")
                labels = issue.get("labels") or []
                if labels:
                    parts.append(f"Labels: {', '.join(labels)}")
                if issue["linear_created_at"]:
                    parts.append(f"Created: {issue['linear_created_at']}")
                if issue["linear_updated_at"]:
                    parts.append(f"Updated: {issue['linear_updated_at']}")
                if issue["description"]:
                    desc = issue["description"][:3000]
                    parts.append(f"\n{desc}")
                comments = issue.get("comments") or []
                if comments:
                    parts.append(f"\nComments ({len(comments)}):")
                    for c in comments:
                        author = c.get("author", "Unknown")
                        date = c.get("created_at", "")
                        body = c.get("body", "")[:500]
                        parts.append(f"[{author}, {date}] {body}")
                return "\n".join(parts)

        elif record_type == "issue_change":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT ic.field, ic.from_value, ic.to_value, "
                    "ic.changed_by, ic.changed_at, "
                    "i.identifier, i.title "
                    "FROM issue_changes ic "
                    "JOIN issues i ON ic.issue_record_id = i.record_id "
                    "WHERE ic.record_id = %s",
                    (record["id"],),
                ).fetchone()
            if row:
                change = dict(row)
                parts = []
                ident = change.get("identifier") or ""
                title = change.get("title") or ""
                if ident or title:
                    parts.append(f"Issue: {ident} — {title}")
                parts.append(f"Change: {change['field']}")
                if change["from_value"]:
                    parts.append(f"From: {change['from_value']}")
                if change["to_value"]:
                    parts.append(f"To: {change['to_value']}")
                if change["changed_by"]:
                    parts.append(f"Changed by: {change['changed_by']}")
                if change["changed_at"]:
                    parts.append(f"At: {change['changed_at']}")
                return "\n".join(parts)

        # Fallback: use raw content from records table
        return record.get("raw") or "(no content)"

    def _parse_json_response(self, text: str) -> dict | None:
        """Parse JSON from an LLM response, handling ```json fencing."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _extract(self, record_type: str, record_id: str, content: str) -> dict:
        """Call Claude to extract entities and facts."""
        user_message = f"Record ({record_id}, {record_type}):\n\n{content}"

        with trace_span(
            "indexer_extract",
            run_type="llm",
            metadata={"record_id": record_id, "record_type": record_type},
            inputs={"model": EXTRACTION_MODEL, "prompt_length": len(user_message)},
        ) as span:
            response = self._client.messages.create(
                model=EXTRACTION_MODEL,
                max_tokens=EXTRACTION_MAX_TOKENS,
                temperature=EXTRACTION_TEMPERATURE,
                system=self._system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            if span:
                span.end(outputs={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                })

        raw_text = ""
        for block in response.content:
            if block.type == "text":
                raw_text += block.text

        parsed = self._parse_json_response(raw_text)
        if parsed is None:
            log.write("indexer", "--", "error", f"JSON parse failed for {record_id}: {raw_text[:200]}")
            return {}

        return parsed

    def _resolve_entity(self, entity: dict) -> str:
        """Resolve an extracted entity against the graph. Returns element ID."""
        entity_type = entity.get("type", "")
        name = entity.get("name", "")
        metadata = entity.get("metadata", {})

        if not name:
            return ""

        # Check for match by email (person) or domain (company)
        metadata_match = None
        if entity_type == "person":
            metadata_match = metadata.get("email")
        elif entity_type == "company":
            metadata_match = metadata.get("domain")

        existing = graph.find_entity(entity_type, name, metadata_match)
        if existing:
            return existing["id"]

        return graph.create_entity(entity_type, name, metadata)

    def _embed_record(self, record: dict, content: str) -> None:
        """Embed record content into Qdrant."""
        record_id = record["id"]
        metadata = {
            "type": record.get("type", ""),
            "source": record.get("source", ""),
        }
        # Add type-specific metadata
        if record.get("type") == "email":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT sender, subject FROM emails WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
            if row:
                metadata["sender"] = row["sender"] or ""
                metadata["subject"] = row["subject"] or ""
        elif record.get("type") == "issue":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT identifier, title FROM issues WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
            if row:
                metadata["identifier"] = row["identifier"] or ""
                metadata["title"] = row["title"] or ""
        elif record.get("type") == "issue_change":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT ic.field, ic.changed_by, i.identifier "
                    "FROM issue_changes ic "
                    "JOIN issues i ON ic.issue_record_id = i.record_id "
                    "WHERE ic.record_id = %s",
                    (record_id,),
                ).fetchone()
            if row:
                metadata["field"] = row["field"] or ""
                metadata["changed_by"] = row["changed_by"] or ""
                metadata["identifier"] = row["identifier"] or ""

        try:
            vectorstore.add_record(record_id, content, metadata)
        except Exception as exc:
            log.write("indexer", "--", "error", f"Qdrant embed failed for {record_id}: {exc}")

    def _process_record(self, record: dict) -> None:
        """Process a single record: extract → resolve → write to Neo4j → embed in Qdrant."""
        record_id = record["id"]
        record_type = record["type"]

        log.write("indexer", "--", "action", f"processing {record_id}")

        content = self._build_content(record)
        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        # Step 1: Extract
        extracted = self._extract(record_type, record_id, content)
        if not extracted:
            log.write("indexer", "--", "action", f"no extraction result for {record_id}")
            self._mark_indexed(record_id)
            return

        # Step 2: Resolve entities — build name → element ID map
        entity_id_map: dict[str, str] = {}
        for entity in extracted.get("entities", []):
            name = entity.get("name", "")
            if not name:
                continue
            eid = self._resolve_entity(entity)
            if eid:
                entity_id_map[name] = eid

        # For issue_change records, use changed_at as the temporal valid_at
        valid_at = None
        if record_type == "issue_change":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT changed_at FROM issue_changes WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
                if row and row["changed_at"]:
                    valid_at = str(row["changed_at"])

        # Step 3: Write facts to Neo4j
        for fact in extracted.get("facts", []):
            category = fact.get("category", "")
            fact_text = fact.get("fact", "")
            confidence = fact.get("confidence", "stated")
            from_name = fact.get("from_entity", "")
            to_name = fact.get("to_entity")  # None for single-entity facts
            fact_valid_at = fact.get("valid_at")

            if not from_name or not fact_text or not category:
                continue

            from_id = entity_id_map.get(from_name)
            if not from_id:
                log.write(
                    "indexer", "--", "warning",
                    f"fact references unknown from_entity '{from_name}' in {record_id}, skipping",
                )
                continue

            if to_name:
                # Two-entity fact: from_entity → to_entity
                to_id = entity_id_map.get(to_name)
                if not to_id:
                    log.write(
                        "indexer", "--", "warning",
                        f"fact references unknown to_entity '{to_name}' in {record_id}, skipping",
                    )
                    continue
                graph.create_fact_edge(
                    from_id, to_id, category, fact_text, confidence,
                    record_id, record_type,
                    valid_at=fact_valid_at or valid_at,
                )
            else:
                # Single-entity fact: from_entity → Day node
                if fact_valid_at:
                    day_date = fact_valid_at[:10]
                else:
                    record_ts = record.get("created_at", "")
                    day_date = graph.utc_to_local_date(str(record_ts)) if record_ts else None
                if day_date:
                    day_id = graph.get_or_create_day(day_date)
                    graph.create_fact_edge(
                        from_id, day_id, category, fact_text, confidence,
                        record_id, record_type,
                        valid_at=fact_valid_at or valid_at,
                    )
                else:
                    log.write(
                        "indexer", "--", "warning",
                        f"cannot determine Day for single-entity fact in {record_id}, skipping",
                    )

        # Step 4: Embed in Qdrant
        self._embed_record(record, content)

        entity_count = len(entity_id_map)
        fact_count = len(extracted.get("facts", []))
        log.write(
            "indexer", "--", "action",
            f"indexed {record_id}: {entity_count} entities, {fact_count} facts",
        )

        self._mark_indexed(record_id)

    def _mark_indexed(self, record_id: str) -> None:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE records SET indexed = TRUE WHERE id = %s", (record_id,)
            )
            conn.commit()

    def _loop(self) -> None:
        init_db()
        graph.ensure_constraints()
        while not self._stop.is_set():
            try:
                with _get_conn() as conn:
                    rows = conn.execute(
                        "SELECT id, type, source, created_at, raw, human_context "
                        "FROM records "
                        "WHERE indexed = FALSE AND classification = 'relevant' "
                        "ORDER BY created_at"
                    ).fetchall()

                if rows:
                    log.write(
                        "indexer", "--", "action",
                        f"found {len(rows)} unindexed record(s): "
                        + ", ".join(r["id"] for r in rows),
                    )
                    for row in rows:
                        if self._stop.is_set():
                            break
                        self._process_record(dict(row))
            except Exception:
                traceback.print_exc()

            self._stop.wait(5)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="indexer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
