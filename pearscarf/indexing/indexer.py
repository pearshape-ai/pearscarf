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

    def __init__(self, debug_dir: str | None = None) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None, max_retries=3)
        self._resolution_prompt = load_prompt("entity_resolution")
        self._debug_dir = debug_dir
        self.token_usage: dict[str, dict[str, int]] = {}  # record_id → {input, output}

    def _debug_folder_name(self, record_id: str) -> str:
        """Resolve record_id to a human-readable folder name for debug output."""
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT dedup_key, type FROM records WHERE id = %s", (record_id,)
            ).fetchone()
            if row:
                r = dict(row)
                if r.get("dedup_key"):
                    return r["dedup_key"]
                if r.get("type") == "ingest":
                    return "seed"
        return record_id

    def _debug_write(self, record_id: str, name: str, content: str) -> None:
        """Write a single debug file."""
        import os
        folder = self._debug_folder_name(record_id)
        record_dir = os.path.join(self._debug_dir, folder)
        os.makedirs(record_dir, exist_ok=True)
        with open(os.path.join(record_dir, name), "w") as fh:
            fh.write(content)

    def _debug_extraction(self, record_id: str, system: str, user: str, raw_response: str, parsed: dict | None) -> None:
        """Dump extraction LLM call if debug is active."""
        if not self._debug_dir:
            return
        self._debug_write(record_id, "extraction_system.md", system)
        self._debug_write(record_id, "extraction_user.md", user)
        self._debug_write(record_id, "extraction_response.txt", raw_response)
        if parsed:
            self._debug_write(record_id, "extraction_response.json", json.dumps(parsed, indent=2))

    def _debug_resolution(self, record_id: str, entity_name: str, system: str, user: str, raw_response: str, parsed: dict | None) -> None:
        """Dump resolution LLM call if debug is active."""
        if not self._debug_dir:
            return
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", entity_name)
        self._debug_write(record_id, f"resolution_{safe}_system.md", system)
        self._debug_write(record_id, f"resolution_{safe}_user.md", user)
        self._debug_write(record_id, f"resolution_{safe}_response.txt", raw_response)
        if parsed:
            self._debug_write(record_id, f"resolution_{safe}_response.json", json.dumps(parsed, indent=2))

    def _build_content(self, record: dict) -> str:
        """Return the record's content string for extraction.

        The content column is the LLM-ready formatted string, written by
        the expert's ingester at save time. For ingest (seed) records,
        the raw markdown is used directly.
        """
        return record.get("content") or record.get("raw") or "(no content)"

    def _build_source_context(self, record: dict, entity_name: str = "") -> str:
        """Build a context string from the record for the resolution judge.

        Uses the record's content (LLM-ready formatted string) and applies
        a sentence window around the entity mention so the resolution judge
        sees focused context rather than the full record.
        """
        text = record.get("content") or record.get("raw") or ""
        if not text:
            return "(no context)"
        if entity_name:
            return _sentence_window(text, entity_name)
        return text[:500]

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
        self._debug_extraction(record_id, system_prompt, user_message, raw_text, parsed)

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
            # Map candidate_number back to actual ID
            candidate_num = decision.get("candidate_number")
            # Fallback: try legacy candidate_id field
            candidate_id = decision.get("candidate_id", "")
            if candidate_num is not None and 1 <= candidate_num <= len(candidates):
                candidate_id = candidates[candidate_num - 1]["id"]

            if not candidate_id:
                log.write("indexer", "--", "warning",
                          f"Resolution: '{name}' matched but no valid candidate ID — creating new")
                return graph.create_entity(entity_type, name, metadata)

            log.write(
                "indexer", "--", "action",
                f"Resolution: '{name}' matched to {candidate_id} — {reasoning}",
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

        entity_name = entity.get("name", "unknown")
        parsed = self._parse_json_response(raw_text)
        self._debug_resolution(self._current_record_id, entity_name, self._resolution_prompt, user_message, raw_text, parsed)

        if parsed is None:
            log.write(
                "indexer", "--", "error",
                f"Resolution JSON parse failed for '{entity_name}': {raw_text[:200]}",
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
        """Embed record content into Qdrant.

        Metadata for the vector payload comes from the record's metadata
        JSONB (written by the expert's ingester), plus type and source.
        """
        record_id = record["id"]
        record_metadata = record.get("metadata") or {}
        metadata = {
            "type": record.get("type", ""),
            "source": record.get("source", ""),
            **{k: str(v) for k, v in record_metadata.items() if v},
        }

        try:
            vectorstore.add_record(record_id, content, metadata)
        except Exception as exc:
            log.write("indexer", "--", "error", f"Qdrant embed failed for {record_id}: {exc}")

    # --- New extraction agent flow ---

    def _build_extraction_prompt(self, record: dict) -> str:
        """Build the system prompt for the extraction agent."""
        agent_instructions = load_prompt("extraction_agent")
        base_prompt = compose_prompt(record)
        return agent_instructions + "\n\n" + base_prompt

    def _run_extraction_agent(self, record: dict, content: str) -> dict | None:
        """Run the extraction agent on a record. Returns extraction result or None."""
        from pearscarf.agents.base import BaseAgent
        from pearscarf.tools import ToolRegistry
        from pearscarf.indexing.extraction_tools import (
            FindEntityTool, SearchEntitiesTool, CheckAliasTool,
            GetEntityContextTool, SaveExtractionTool,
        )

        registry = ToolRegistry()
        save_tool = SaveExtractionTool()
        registry.register(FindEntityTool())
        registry.register(SearchEntitiesTool())
        registry.register(CheckAliasTool())
        registry.register(GetEntityContextTool())
        registry.register(save_tool)

        system_prompt = self._build_extraction_prompt(record)
        record_id = record["id"]
        record_type = record["type"]
        user_message = f"Record ({record_id}, {record_type}):\n\n{content}"

        agent = BaseAgent(
            tool_registry=registry,
            system_prompt=system_prompt,
            agent_name="extraction_agent",
        )

        error = None
        try:
            agent.run(user_message)
        except Exception as exc:
            error = str(exc)
            log.write("indexer", "--", "error", f"Extraction agent failed for {record_id}: {exc}")

        result = save_tool.result
        if result is not None:
            result["_tokens"] = {
                "input": agent.total_input_tokens,
                "output": agent.total_output_tokens,
            }

        self._debug_agent(record_id, system_prompt, user_message, agent, result, error)

        if error:
            return None
        if result is None:
            log.write("indexer", "--", "warning", f"Extraction agent didn't call save_extraction for {record_id}")
            return None

        return result

    def _debug_agent(self, record_id, system_prompt, user_message, agent, result, error):
        """Dump agent conversation to debug dir if active."""
        if not self._debug_dir:
            return
        import os
        folder = self._debug_folder_name(record_id)
        debug_path = os.path.join(self._debug_dir, folder)
        os.makedirs(debug_path, exist_ok=True)
        with open(os.path.join(debug_path, "agent_system.md"), "w") as fh:
            fh.write(system_prompt)
        with open(os.path.join(debug_path, "agent_user.md"), "w") as fh:
            fh.write(user_message)
        with open(os.path.join(debug_path, "agent_conversation.json"), "w") as fh:
            fh.write(json.dumps(agent._messages, indent=2, default=str))
        if result:
            with open(os.path.join(debug_path, "agent_result.json"), "w") as fh:
                fh.write(json.dumps(result, indent=2))
        if error:
            with open(os.path.join(debug_path, "agent_error.txt"), "w") as fh:
                fh.write(error)

    def _validate_extraction(self, record: dict, extraction: dict) -> list[str]:
        """Validate an extraction result. Returns list of errors (empty = valid)."""
        errors: list[str] = []
        content = self._build_content(record)

        entities = extraction.get("entities", [])
        facts = extraction.get("facts", [])
        entity_names = {e["name"].lower() for e in entities}

        for ent in entities:
            # Check resolved_to IDs exist
            resolved_to = ent.get("resolved_to", "")
            if resolved_to and resolved_to != "new":
                with graph.get_session() as session:
                    result = session.run(
                        "MATCH (n) WHERE elementId(n) = $eid RETURN n.name AS name",
                        eid=resolved_to,
                    )
                    if not result.single():
                        errors.append(f"Entity '{ent['name']}' resolved_to non-existent node: {resolved_to}")

        for fact in facts:
            # Validate edge label
            edge_label = fact.get("edge_label", "")
            if edge_label not in graph.FACT_CATEGORIES:
                errors.append(f"Invalid edge_label: {edge_label}")
                continue

            # Validate fact type
            fact_type = fact.get("fact_type", "")
            if fact_type and fact_type not in graph.FACT_CATEGORIES[edge_label]:
                errors.append(f"Invalid fact_type '{fact_type}' for {edge_label}")

            # Check entity references
            from_name = fact.get("from_entity", "").lower()
            if from_name and from_name not in entity_names:
                errors.append(f"Fact references unknown from_entity: {fact.get('from_entity')}")

            to_name = (fact.get("to_entity") or "").lower()
            if to_name and to_name not in entity_names:
                errors.append(f"Fact references unknown to_entity: {fact.get('to_entity')}")

            # Fact grounding — check text appears in source
            fact_text = fact.get("fact", "").lower()
            if fact_text and fact_text not in content.lower():
                # Allow partial match — at least 60% of words should appear
                fact_words = set(fact_text.split())
                content_lower = content.lower()
                found = sum(1 for w in fact_words if w in content_lower)
                if found / max(len(fact_words), 1) < 0.6:
                    errors.append(f"Fact may be hallucinated (low grounding): {fact.get('fact', '')[:80]}")

        return errors

    def _commit_extraction(self, record: dict, extraction: dict) -> dict[str, str]:
        """Write validated extraction to the graph. Returns entity_id_map."""
        record_id = record["id"]
        record_type = record["type"]
        entity_id_map: dict[str, str] = {}

        # Derive source_at from metadata
        metadata = record.get("metadata") or {}
        source_at = (
            str(metadata.get("received_at", ""))
            or str(metadata.get("linear_created_at", ""))
            or str(metadata.get("created_at", ""))
            or str(record.get("created_at", ""))
            or _now()
        )

        # Create/resolve entities
        for ent in extraction.get("entities", []):
            name = ent["name"]
            ent_type = ent.get("type", "")
            ent_metadata = ent.get("metadata", {})
            resolved_to = ent.get("resolved_to", "new")
            canonical_name = ent.get("canonical_name", "")

            if resolved_to == "new":
                node_id = graph.create_entity(ent_type, name, ent_metadata)
                entity_id_map[name] = node_id
            else:
                entity_id_map[name] = resolved_to
                # Create alias if name differs from canonical
                if canonical_name and canonical_name.lower() != name.lower():
                    graph.create_identified_as_edge(
                        resolved_to, name, record_id, record_type,
                        confidence="inferred",
                        reasoning=f"Extraction agent resolved '{name}' to '{canonical_name}'",
                    )

        # Write facts
        for fact in extraction.get("facts", []):
            edge_label = fact.get("edge_label", "")
            fact_type = fact.get("fact_type", "")
            fact_text = fact.get("fact", "")
            confidence = fact.get("confidence", "stated")
            from_name = fact.get("from_entity", "")
            to_name = fact.get("to_entity")
            valid_until = fact.get("valid_until")

            from_id = entity_id_map.get(from_name)
            if not from_id:
                continue

            to_id = None
            if to_name:
                to_id = entity_id_map.get(to_name)

            if to_id:
                self._write_fact_edge(
                    from_id, to_id, edge_label, fact_type, fact_text,
                    confidence, record_id, record_type, source_at, valid_until,
                )
            else:
                day_date = graph.utc_to_local_date(source_at)
                day_id = graph.get_or_create_day(day_date)
                self._write_fact_edge(
                    from_id, day_id, edge_label, fact_type, fact_text,
                    confidence, record_id, record_type, source_at, valid_until,
                )

        return entity_id_map

    # --- Main processing ---

    def _process_record(self, record: dict) -> None:
        """Process a single record: agent extracts + resolves → validate → commit → embed."""
        record_id = record["id"]
        record_type = record["type"]
        self._current_record_id = record_id
        self._current_record_type = record_type

        log.write("indexer", "--", "action", f"processing {record_id}")

        content = self._build_content(record)
        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        # Step 1: Run extraction agent
        extraction = self._run_extraction_agent(record, content)
        if not extraction:
            log.write("indexer", "--", "action", f"no extraction result for {record_id}")
            self._mark_indexed(record_id)
            return

        # Track token usage
        tokens = extraction.pop("_tokens", None)
        if tokens:
            self.token_usage[record_id] = tokens

        # Step 2: Validate
        errors = self._validate_extraction(record, extraction)
        if errors:
            for err in errors:
                log.write("indexer", "--", "warning", f"{record_id}: {err}")

        # Step 3: Commit to graph
        entity_id_map = self._commit_extraction(record, extraction)

        # Step 4: Embed in Qdrant
        self._embed_record(record, content)

        entity_count = len(entity_id_map)
        fact_count = len(extraction.get("facts", []))
        log.write(
            "indexer", "--", "action",
            f"indexed {record_id}: {entity_count} entities, {fact_count} facts",
        )

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
