"""Indexer — background agent that processes records into the knowledge graph.

Polls for unindexed records and runs LLM extraction → entity resolution →
Neo4j graph population → Qdrant embedding.
"""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime, timezone

import anthropic

from pearscarf.storage import graph, vectorstore
from pearscarf import log
from pearscarf.config import (
    ANTHROPIC_API_KEY,
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_MODEL,
    EXTRACTION_TEMPERATURE,
)
from pearscarf.storage.db import _get_conn, init_db
from pearscarf.indexing.registry import compose_prompt
from pearscarf.knowledge import load as load_prompt
from pearscarf.tracing import trace_span


import re


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sentence_window(text: str, mention: str, radius: int = 2) -> str:
    """Extract sentences around all occurrences of a mention.

    Finds every sentence containing the mention, includes `radius` sentences
    before and after each, merges overlapping windows, and joins with '...'
    for gaps. Falls back to full text if short or mention not found.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not mention or len(sentences) <= (2 * radius + 1):
        return text

    mention_lower = mention.lower()
    included: set[int] = set()
    for i, s in enumerate(sentences):
        if mention_lower in s.lower():
            for j in range(max(0, i - radius), min(len(sentences), i + radius + 1)):
                included.add(j)

    if not included:
        return text[:600]

    parts: list[str] = []
    prev = -2
    for i in sorted(included):
        if i > prev + 1 and parts:
            parts.append("...")
        parts.append(sentences[i])
        prev = i

    return " ".join(parts)


class Indexer:
    """Background agent that indexes records via LLM extraction."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
        self._resolution_prompt = load_prompt("entity_resolution")

    def _build_content(self, record: dict) -> str:
        """Return the record's content string for extraction.

        The content column is the LLM-ready formatted string, written by
        the expert's ingester at save time. For ingest (seed) records,
        the raw markdown is used directly.
        """
        return record.get("content") or record.get("raw") or "(no content)"

    def _build_source_context(self, record: dict, entity_name: str = "") -> str:
        """Build a context string from the record for the resolution judge.

        If entity_name is provided, extracts a sentence window around each
        mention instead of truncating from the start.
        """
        record_type = record.get("type", "")
        record_id = record["id"]

        if record_type == "email":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT sender, recipient, subject, body FROM emails WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
            if row:
                parts = []
                if row["sender"]:
                    parts.append(f"From: {row['sender']}")
                if row["recipient"]:
                    parts.append(f"To: {row['recipient']}")
                if row["subject"]:
                    parts.append(f"Subject: {row['subject']}")
                if row["body"]:
                    parts.append(f"Body: {_sentence_window(row['body'], entity_name)}")
                return "\n".join(parts)

        elif record_type == "issue":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT identifier, title, assignee, project FROM issues WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
            if row:
                parts = []
                if row["identifier"]:
                    parts.append(f"Issue: {row['identifier']}")
                if row["title"]:
                    parts.append(f"Title: {row['title']}")
                if row["assignee"]:
                    parts.append(f"Assignee: {row['assignee']}")
                if row["project"]:
                    parts.append(f"Project: {row['project']}")
                return "\n".join(parts)

        elif record_type == "issue_change":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT ic.field, ic.from_value, ic.to_value, ic.changed_by, "
                    "i.identifier, i.title "
                    "FROM issue_changes ic "
                    "JOIN issues i ON ic.issue_record_id = i.record_id "
                    "WHERE ic.record_id = %s",
                    (record_id,),
                ).fetchone()
            if row:
                parts = []
                if row["identifier"]:
                    parts.append(f"Issue: {row['identifier']} — {row['title'] or ''}")
                parts.append(f"Field changed: {row['field']}")
                if row["from_value"]:
                    parts.append(f"From: {row['from_value']}")
                if row["to_value"]:
                    parts.append(f"To: {row['to_value']}")
                if row["changed_by"]:
                    parts.append(f"Changed by: {row['changed_by']}")
                return "\n".join(parts)

        elif record_type == "ingest":
            raw = record.get("raw", "")
            if not raw:
                return "(seed file)"
            return _sentence_window(raw, entity_name) if entity_name else raw[:500]

        return "(no context)"

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

    def _extract(self, record: dict, content: str) -> dict:
        """Call Claude to extract entities and facts."""
        record_id = record["id"]
        record_type = record["type"]
        user_message = f"Record ({record_id}, {record_type}):\n\n{content}"

        system_prompt = compose_prompt(record)

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
                system=system_prompt,
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

    def _resolve_entity(self, entity: dict, source_context: str) -> str | None:
        """Resolve an extracted entity against the graph.

        Returns element ID, or None if ambiguous.
        """
        entity_type = entity.get("type", "")
        name = entity.get("name", "")
        metadata = entity.get("metadata", {})

        if not name:
            return ""

        candidates = graph.find_entity_candidates(entity_type, name, metadata)

        # No candidates — create new entity
        if not candidates:
            return graph.create_entity(entity_type, name, metadata)

        # Exact name match — fast path, no LLM
        for c in candidates:
            if c["name"].lower() == name.lower():
                return c["id"]

        # Exact email/domain match — deterministic, no LLM
        email = metadata.get("email", "").lower()
        domain = metadata.get("domain", "").lower()
        if email or domain:
            for c in candidates:
                c_meta = c.get("metadata", {})
                if email and c_meta.get("email", "").lower() == email:
                    if c["name"].lower() != name.lower():
                        graph.create_identified_as_edge(
                            c["id"], name, self._current_record_id, self._current_record_type,
                            confidence="stated",
                            reasoning=f"Email match: {email}",
                        )
                    return c["id"]
                if domain and c_meta.get("domain", "").lower() == domain:
                    if c["name"].lower() != name.lower():
                        graph.create_identified_as_edge(
                            c["id"], name, self._current_record_id, self._current_record_type,
                            confidence="stated",
                            reasoning=f"Domain match: {domain}",
                        )
                    return c["id"]

        # Non-exact — call LLM judge
        context_packages = [
            graph.get_entity_context(c["id"])
            for c in candidates
        ]

        decision = self._resolve_entity_with_llm(entity, source_context, context_packages)

        verdict = decision.get("decision", "new")
        reasoning = decision.get("reasoning", "")

        if verdict == "match":
            candidate_id = decision.get("candidate_id", "")
            log.write(
                "indexer", "--", "action",
                f"Resolution: '{name}' matched to candidate {candidate_id} — {reasoning}",
            )
            graph.create_identified_as_edge(
                candidate_id, name, self._current_record_id, self._current_record_type,
                confidence="inferred",
                reasoning=reasoning,
            )
            return candidate_id

        elif verdict == "new":
            log.write(
                "indexer", "--", "action",
                f"Resolution: '{name}' is new entity — {reasoning}",
            )
            return graph.create_entity(entity_type, name, metadata)

        elif verdict == "ambiguous":
            log.write(
                "indexer", "--", "action",
                f"Resolution: '{name}' is ambiguous — {reasoning}",
            )
            return None  # caller handles ambiguity

        # Unknown verdict — fallback to new
        log.write(
            "indexer", "--", "warning",
            f"Resolution: unknown verdict '{verdict}' for '{name}' — creating new entity",
        )
        return graph.create_entity(entity_type, name, metadata)

    def _resolve_entity_with_llm(
        self,
        entity: dict,
        source_context: str,
        context_packages: list[dict],
    ) -> dict:
        """Call the resolution judge LLM to decide: match, new, or ambiguous.

        Args:
            entity: Extracted entity dict (name, type, metadata).
            source_context: The record content snippet that produced this entity.
            context_packages: List of context packages from get_entity_context(),
                one per candidate.

        Returns:
            {"decision": "match"|"new"|"ambiguous",
             "candidate_id": str (if match),
             "candidate_ids": list[str] (if ambiguous),
             "reasoning": str}
        """
        # Build user message
        lines = []

        # Section 1: Extracted entity
        lines.append("## Extracted entity")
        lines.append(f"Name: {entity.get('name', '')}")
        lines.append(f"Type: {entity.get('type', '')}")
        meta = entity.get("metadata", {})
        if meta:
            lines.append(f"Metadata: {json.dumps(meta)}")

        # Section 2: Source record context
        lines.append("")
        lines.append("## Source record context")
        lines.append(source_context)

        # Section 3: Candidates
        lines.append("")
        lines.append("## Candidates")
        for i, pkg in enumerate(context_packages):
            ent = pkg.get("entity", {})
            lines.append(f"### Candidate {i + 1}")
            lines.append(f"ID: {ent.get('id', '')}")
            lines.append(f"Name: {ent.get('name', '')}")
            lines.append(f"Type: {ent.get('type', '')}")
            ent_meta = ent.get("metadata", {})
            if ent_meta:
                lines.append(f"Metadata: {json.dumps(ent_meta)}")

            facts = pkg.get("facts", [])
            if facts:
                lines.append("Facts:")
                for f in facts:
                    lines.append(f"  - [{f['edge_label']}] {f['fact']}")

            conns = pkg.get("connections", [])
            if conns:
                lines.append("Connections:")
                for c in conns:
                    lines.append(f"  - {c['name']} ({c.get('type', '')})")

            lines.append("")

        user_message = "\n".join(lines)

        with trace_span(
            "indexer_resolve",
            run_type="llm",
            metadata={
                "entity_name": entity.get("name", ""),
                "entity_type": entity.get("type", ""),
                "candidate_count": len(context_packages),
            },
            inputs={"model": EXTRACTION_MODEL, "prompt_length": len(user_message)},
        ) as span:
            response = self._client.messages.create(
                model=EXTRACTION_MODEL,
                max_tokens=512,
                temperature=0.0,
                system=self._resolution_prompt,
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
            log.write(
                "indexer", "--", "error",
                f"Resolution JSON parse failed for '{entity.get('name', '')}': {raw_text[:200]}",
            )
            return {"decision": "new", "reasoning": "JSON parse failure — defaulting to new"}

        return parsed

    def _write_fact_edge(
        self,
        from_id: str,
        to_id: str,
        edge_label: str,
        fact_type: str,
        fact_text: str,
        confidence: str,
        record_id: str,
        record_type: str,
        source_at: str,
        valid_until: str | None,
    ) -> None:
        """Write a fact edge with literal dup check."""
        existing = graph.find_exact_dup_edge(
            from_id, edge_label, fact_type, to_id, record_id, fact_text,
        )
        if existing:
            graph.append_source_record(existing, record_id, confidence)
            log.write(
                "indexer", "--", "action",
                f"dup merged: {record_id} already in edge {existing}",
            )
            return

        graph.create_fact_edge(
            from_id, to_id, edge_label, fact_type, fact_text,
            confidence, record_id, record_type,
            source_at=source_at, valid_until=valid_until,
        )

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
        self._current_record_id = record_id
        self._current_record_type = record_type

        log.write("indexer", "--", "action", f"processing {record_id}")

        content = self._build_content(record)
        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        # Step 1: Extract
        extracted = self._extract(record, content)
        if not extracted:
            log.write("indexer", "--", "action", f"no extraction result for {record_id}")
            self._mark_indexed(record_id)
            return

        # Step 2: Resolve entities — build name → element ID map
        entity_id_map: dict[str, str] = {}
        unresolved: list[dict] = []

        for entity in extracted.get("entities", []):
            name = entity.get("name", "")
            if not name:
                continue
            source_context = self._build_source_context(record, name)
            eid = self._resolve_entity(entity, source_context)
            if eid is None:
                # Ambiguous — collect for pending state
                candidates = graph.find_entity_candidates(
                    entity.get("type", ""), name, entity.get("metadata", {})
                )
                unresolved.append({
                    "name": name,
                    "type": entity.get("type", ""),
                    "candidate_ids": [c["id"] for c in candidates],
                })
            elif eid:
                entity_id_map[name] = eid

        # If any entities are unresolved, mark record as pending
        if unresolved:
            self._set_resolution_pending(record_id, unresolved)
            log.write(
                "indexer", "--", "action",
                f"{record_id}: {len(unresolved)} unresolved entity(ies) — "
                f"resolution pending, skipping fact writes for unresolved entities",
            )

        # Derive source_at — event time from the record's own timestamp
        source_at = str(record.get("created_at", "")) or ""
        if record_type == "email":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT received_at FROM emails WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
                if row and row["received_at"]:
                    source_at = str(row["received_at"])
        elif record_type == "issue":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT linear_created_at FROM issues WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
                if row and row["linear_created_at"]:
                    source_at = str(row["linear_created_at"])
        elif record_type == "issue_change":
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT changed_at FROM issue_changes WHERE record_id = %s",
                    (record_id,),
                ).fetchone()
                if row and row["changed_at"]:
                    source_at = str(row["changed_at"])

        if not source_at:
            source_at = _now()
            log.write(
                "indexer", "--", "warning",
                f"no timestamp for {record_id}, using indexing time as source_at",
            )

        # Step 3: Write facts to Neo4j
        for fact in extracted.get("facts", []):
            edge_label = fact.get("edge_label", "")
            fact_type = fact.get("fact_type", "")
            fact_text = fact.get("fact", "")
            confidence = fact.get("confidence", "stated")
            from_name = fact.get("from_entity", "")
            to_name = fact.get("to_entity")  # None for single-entity facts
            valid_until = fact.get("valid_until")

            if not from_name or not fact_text or not edge_label:
                continue

            # Validate edge_label and fact_type
            if edge_label not in graph.FACT_CATEGORIES:
                log.write(
                    "indexer", "--", "warning",
                    f"unrecognized edge_label '{edge_label}' in {record_id}, skipping",
                )
                continue
            if fact_type and fact_type not in graph.FACT_CATEGORIES[edge_label]:
                log.write(
                    "indexer", "--", "warning",
                    f"unrecognized fact_type '{fact_type}' for {edge_label} in {record_id}, skipping",
                )
                continue

            from_id = entity_id_map.get(from_name)
            if not from_id:
                log.write(
                    "indexer", "--", "warning",
                    f"fact references unknown from_entity '{from_name}' in {record_id}, skipping",
                )
                continue

            to_id = None
            if to_name:
                # Try entity_id_map first
                to_id = entity_id_map.get(to_name)
                if not to_id:
                    # Full resolution for to_entity
                    try:
                        to_candidates = graph.find_entity_candidates("", to_name)
                        if to_candidates:
                            # Exact name match — fast path
                            matched = next(
                                (c for c in to_candidates if c["name"].lower() == to_name.lower()),
                                None,
                            )
                            if matched:
                                to_id = matched["id"]
                            else:
                                # LLM judge
                                to_ctx = [graph.get_entity_context(c["id"]) for c in to_candidates]
                                decision = self._resolve_entity_with_llm(
                                    {"name": to_name, "type": "", "metadata": {}},
                                    self._build_source_context(record, to_name), to_ctx,
                                )
                                verdict = decision.get("decision", "new")
                                if verdict == "match":
                                    to_id = decision.get("candidate_id", "")
                                elif verdict == "new":
                                    to_id = graph.create_entity("", to_name)
                                # ambiguous or other → to_id stays None → Day node
                        else:
                            # No candidates — create new entity
                            to_id = graph.create_entity("", to_name)
                    except Exception as exc:
                        log.write(
                            "indexer", "--", "warning",
                            f"to_entity resolution failed for '{to_name}' in {record_id}: {exc}",
                        )
                        # to_id stays None → Day node

                    if to_id:
                        entity_id_map[to_name] = to_id

            if to_id:
                # Two-entity fact
                self._write_fact_edge(
                    from_id, to_id, edge_label, fact_type, fact_text,
                    confidence, record_id, record_type,
                    source_at, valid_until,
                )
            else:
                # Single-entity fact or degraded to_entity → Day node
                day_date = graph.utc_to_local_date(source_at)
                day_id = graph.get_or_create_day(day_date)
                self._write_fact_edge(
                    from_id, day_id, edge_label, fact_type, fact_text,
                    confidence, record_id, record_type,
                    source_at, valid_until,
                )

        # Step 4: Embed in Qdrant
        self._embed_record(record, content)

        entity_count = len(entity_id_map)
        fact_count = len(extracted.get("facts", []))
        log.write(
            "indexer", "--", "action",
            f"indexed {record_id}: {entity_count} entities, {fact_count} facts",
        )

        # Only mark indexed if all entities resolved
        if not unresolved:
            self._mark_indexed(record_id)
            try:
                from pearscarf.storage.store import enqueue_for_curation
                enqueue_for_curation(record_id)
            except Exception as exc:
                log.write(
                    "indexer", "--", "warning",
                    f"failed to enqueue {record_id} for curation: {exc}",
                )

    def _mark_indexed(self, record_id: str) -> None:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE records SET indexed = TRUE WHERE id = %s", (record_id,)
            )
            conn.commit()

    def _set_resolution_pending(self, record_id: str, unresolved: list[dict]) -> None:
        """Store ambiguity state on the record."""
        with _get_conn() as conn:
            conn.execute(
                "UPDATE records SET resolution_pending = %s, resolution_status = 'pending' "
                "WHERE id = %s",
                (json.dumps(unresolved), record_id),
            )
            conn.commit()

    def _loop(self) -> None:
        init_db()
        graph.ensure_constraints()
        while not self._stop.is_set():
            try:
                with _get_conn() as conn:
                    rows = conn.execute(
                        "SELECT id, type, source, created_at, raw, content, "
                        "metadata, human_context "
                        "FROM records "
                        "WHERE indexed = FALSE AND classification = 'relevant' "
                        "AND (resolution_status IS NULL OR resolution_status != 'pending') "
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
