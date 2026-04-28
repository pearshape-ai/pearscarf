"""Extraction — Consumer that extracts entities and facts from relevant records.

Polls `records WHERE classification='relevant' AND indexed=FALSE`. Per
record, spawns an `ExtractorAgent` (BaseAgent subclass) that uses graph-
context tools to resolve entities and output an `{entities, facts}`
structure, validates the output, commits to Neo4j, embeds the record
content in Qdrant, then enqueues for curation.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from pearscarf import log
from pearscarf.agents.base import BaseAgent
from pearscarf.consumer import Consumer
from pearscarf.knowledge import load as load_prompt
from pearscarf.knowledge import load_onboarding_block
from pearscarf.registry import compose_prompt
from pearscarf.storage import graph, vectorstore
from pearscarf.storage.db import _get_conn, init_db
from pearscarf.tools import BaseTool
from pearscarf.tracked_call import _record_id_var


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SaveExtractionTool(BaseTool):
    """The extractor agent calls this once at the end to commit its result.

    Extraction-specific — the structured output is interpreted by the
    `Extraction` consumer's validate + commit pipeline, not written
    directly to the graph by this tool.
    """

    name = "save_extraction"
    description = (
        "Save the final extraction result. Call this once at the end "
        "after you have identified all entities and extracted all facts. "
        "Every fact text MUST be cut directly from the record — never paraphrase."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Entity name as it appears in the record",
                        },
                        "type": {
                            "type": "string",
                            "description": "person, company, project, event",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "email, domain, role if known",
                        },
                        "resolved_to": {
                            "type": "string",
                            "description": "Node ID if matched to existing entity, or 'new' if new entity",
                        },
                        "canonical_name": {
                            "type": "string",
                            "description": "The canonical name of the matched entity, if resolved",
                        },
                    },
                    "required": ["name", "type", "resolved_to"],
                },
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edge_label": {
                            "type": "string",
                            "description": "AFFILIATED, ASSERTED, or TRANSITIONED",
                        },
                        "fact_type": {"type": "string"},
                        "fact": {
                            "type": "string",
                            "description": "Text cut directly from the record — never paraphrase",
                        },
                        "from_entity": {"type": "string", "description": "Name of the from entity"},
                        "to_entity": {
                            "type": "string",
                            "description": "Name of the to entity, or null",
                        },
                        "confidence": {"type": "string", "description": "stated or inferred"},
                        "valid_until": {
                            "type": "string",
                            "description": "ISO date if a deadline is stated, or null",
                        },
                    },
                    "required": ["edge_label", "fact_type", "fact", "from_entity", "confidence"],
                },
            },
        },
        "required": ["entities", "facts"],
    }

    def __init__(self) -> None:
        self._result: dict | None = None

    def execute(self, **kwargs: Any) -> str:
        self._result = {
            "entities": kwargs.get("entities", []),
            "facts": kwargs.get("facts", []),
        }
        return "Extraction saved."

    @property
    def result(self) -> dict | None:
        return self._result


class ExtractorAgent(BaseAgent):
    """LLM agent spawned per record by `Extraction` to extract entities + facts.

    Thin named subclass of `BaseAgent` — same run loop, fixed agent_name
    so the call site doesn't have to pass the magic string.
    """

    def __init__(
        self,
        tool_registry,
        system_prompt: str = "",
        on_tool_call=None,
        on_text=None,
        on_tool_result=None,
        max_turns: int | None = None,
    ) -> None:
        super().__init__(
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            agent_name="extractor_agent",
            on_tool_call=on_tool_call,
            on_text=on_text,
            on_tool_result=on_tool_result,
            max_turns=max_turns,
        )


class Extraction(Consumer):
    """Consumer that indexes relevant records into the knowledge graph."""

    name = "extraction"
    default_poll_interval = 5.0
    max_turns = 10

    def __init__(
        self,
        debug_dir: str | None = None,
        poll_interval: float | None = None,
    ) -> None:
        super().__init__(poll_interval=poll_interval)
        self._debug_dir = debug_dir
        self.token_usage: dict[str, dict[str, int]] = {}  # record_id → {input, output}
        self._pending: list[dict] = []

    # --- Consumer hooks ---

    def _setup(self) -> None:
        init_db()
        graph.ensure_constraints()

    def _next(self) -> dict | None:
        if self._pending:
            return self._pending.pop(0)

        from pearscarf.storage import store

        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT id, type, source, created_at, raw, content, "
                "metadata, human_context "
                "FROM records "
                "WHERE indexed = FALSE AND classification = %s "
                "ORDER BY created_at",
                (store.RELEVANT,),
            ).fetchall()

        if not rows:
            return None

        self._pending = [dict(r) for r in rows]
        log.write(
            self.name,
            "--",
            "action",
            f"found {len(rows)} unindexed record(s): " + ", ".join(r["id"] for r in rows),
        )
        return self._pending.pop(0)

    def _handle(self, record: dict) -> None:
        token = _record_id_var.set(record["id"])
        try:
            self._process_record(record)
        finally:
            _record_id_var.reset(token)

    # --- Debug output ---

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
        if not self._debug_dir:
            return
        folder = self._debug_folder_name(record_id)
        record_dir = os.path.join(self._debug_dir, folder)
        os.makedirs(record_dir, exist_ok=True)
        with open(os.path.join(record_dir, name), "w") as fh:
            fh.write(content)

    def _build_content(self, record: dict) -> str:
        """Return the record's content string for extraction.

        The content column is the LLM-ready formatted string, written by
        the expert's ingester at save time. For ingest (seed) records,
        the raw markdown is used directly.
        """
        return record.get("content") or record.get("raw") or "(no content)"

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
            from_id,
            edge_label,
            fact_type,
            to_id,
            record_id,
            fact_text,
        )
        if existing:
            graph.append_source_record(existing, record_id, confidence)
            log.write(
                self.name,
                "--",
                "action",
                f"dup merged: {record_id} already in edge {existing}",
            )
            return

        graph.create_fact_edge(
            from_id,
            to_id,
            edge_label,
            fact_type,
            fact_text,
            confidence,
            record_id,
            record_type,
            source_at=source_at,
            valid_until=valid_until,
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
            log.write(self.name, "--", "error", f"Qdrant embed failed for {record_id}: {exc}")

    # --- Extractor agent ---

    def _build_extraction_prompt(self, record: dict) -> str:
        """Build the system prompt for the extractor agent."""
        agent_instructions = load_prompt("extractor_agent")
        onboarding = load_onboarding_block()
        base_prompt = compose_prompt(record)
        return agent_instructions + "\n\n" + onboarding + base_prompt

    def _run_extractor_agent(self, record: dict, content: str) -> dict | None:
        """Run the extractor agent on a record. Returns extraction result or None."""
        from pearscarf.graph_access_tools import ResolveEntityTool
        from pearscarf.tools import ToolRegistry

        registry = ToolRegistry()
        save_tool = SaveExtractionTool()
        registry.register(ResolveEntityTool())
        registry.register(save_tool)

        system_prompt = self._build_extraction_prompt(record)
        record_id = record["id"]
        record_type = record["type"]
        user_message = f"Record ({record_id}, {record_type}):\n\n{content}"

        agent = ExtractorAgent(
            tool_registry=registry,
            system_prompt=system_prompt,
            max_turns=self.max_turns,
        )

        error = None
        try:
            agent.run(user_message)
        except Exception as exc:
            error = str(exc)
            log.write(self.name, "--", "error", f"Extractor agent failed for {record_id}: {exc}")

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
            log.write(
                self.name,
                "--",
                "warning",
                f"Extractor agent didn't call save_extraction for {record_id}",
            )
            return None

        return result

    def _debug_agent(self, record_id, system_prompt, user_message, agent, result, error):
        """Dump agent conversation to debug dir if active."""
        if not self._debug_dir:
            return
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
                        errors.append(
                            f"Entity '{ent['name']}' resolved_to non-existent node: {resolved_to}"
                        )

        for fact in facts:
            # Validate edge label
            edge_label = fact.get("edge_label", "")
            if edge_label not in graph.FACT_CATEGORIES:
                errors.append(f"Invalid edge_label: {edge_label}")
                continue

            # Anchored extensibility — novel fact_types are accepted, not rejected.
            # The canonical lists in graph.FACT_CATEGORIES (extended by deployment
            # vocab) are an anchor set. Anything outside is logged for curator review;
            # the fact still commits onto the edge.
            fact_type = fact.get("fact_type", "")
            if fact_type and fact_type not in graph.FACT_CATEGORIES[edge_label]:
                log.write(
                    self.name,
                    "--",
                    "novel_fact_type",
                    f"{record.get('id', '?')}: proposed '{fact_type}' under {edge_label}",
                )

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
                    errors.append(
                        f"Fact may be hallucinated (low grounding): {fact.get('fact', '')[:80]}"
                    )

        return errors

    def _commit_entities(self, record: dict, extraction: dict) -> dict[str, str]:
        """Commit entities from a regular record. Returns entity_id_map."""
        record_id = record["id"]
        record_type = record["type"]
        entity_id_map: dict[str, str] = {}

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
                if canonical_name and canonical_name.lower() != name.lower():
                    graph.create_identified_as_edge(
                        resolved_to,
                        name,
                        record_id,
                        record_type,
                        confidence="inferred",
                        reasoning=f"Extractor agent resolved '{name}' to '{canonical_name}'",
                    )

        return entity_id_map

    def _commit_seed(self, record: dict, extraction: dict) -> dict[str, str]:
        """Commit entities + aliases from a seed record. Returns entity_id_map."""
        record_id = record["id"]
        record_type = record["type"]
        entity_id_map: dict[str, str] = {}

        # First pass: create canonical entities
        for ent in extraction.get("entities", []):
            name = ent["name"]
            canonical_name = ent.get("canonical_name", "")
            if canonical_name and canonical_name.lower() != name.lower():
                continue  # alias — handled in second pass
            node_id = graph.create_entity(
                ent.get("type", ""),
                name,
                ent.get("metadata", {}),
            )
            entity_id_map[name] = node_id

        # Second pass: create alias edges
        for ent in extraction.get("entities", []):
            name = ent["name"]
            canonical_name = ent.get("canonical_name", "")
            if not canonical_name or canonical_name.lower() == name.lower():
                continue  # not an alias
            canonical_id = entity_id_map.get(canonical_name)
            if canonical_id:
                entity_id_map[name] = canonical_id
                graph.create_identified_as_edge(
                    canonical_id,
                    name,
                    record_id,
                    record_type,
                    confidence="stated",
                    reasoning=f"Seed alias: '{name}' for '{canonical_name}'",
                )

        return entity_id_map

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

        # Seed records have their own commit path (entities + aliases in one go)
        if record_type == "ingest":
            entity_id_map = self._commit_seed(record, extraction)
        else:
            entity_id_map = self._commit_entities(record, extraction)

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
                    from_id,
                    to_id,
                    edge_label,
                    fact_type,
                    fact_text,
                    confidence,
                    record_id,
                    record_type,
                    source_at,
                    valid_until,
                )
            else:
                day_date = graph.utc_to_local_date(source_at)
                day_id = graph.get_or_create_day(day_date)
                self._write_fact_edge(
                    from_id,
                    day_id,
                    edge_label,
                    fact_type,
                    fact_text,
                    confidence,
                    record_id,
                    record_type,
                    source_at,
                    valid_until,
                )

        return entity_id_map

    # --- Main processing ---

    def _process_record(self, record: dict) -> None:
        """Process a single record: agent extracts + resolves → validate → commit → embed."""
        record_id = record["id"]
        record_type = record["type"]
        self._current_record_id = record_id
        self._current_record_type = record_type

        log.write(self.name, "--", "action", f"processing {record_id}")

        content = self._build_content(record)
        if record.get("human_context"):
            content += f"\n\nAdditional context from human:\n{record['human_context']}"

        # Step 1: Run extractor agent
        extraction = self._run_extractor_agent(record, content)
        if not extraction:
            log.write(self.name, "--", "action", f"no extraction result for {record_id}")
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
                log.write(self.name, "--", "warning", f"{record_id}: {err}")

        # Step 3: Commit to graph
        entity_id_map = self._commit_extraction(record, extraction)

        # Step 4: Embed in Qdrant
        self._embed_record(record, content)

        entity_count = len(entity_id_map)
        fact_count = len(extraction.get("facts", []))
        log.write(
            self.name,
            "--",
            "action",
            f"indexed {record_id}: {entity_count} entities, {fact_count} facts",
        )

        self._mark_indexed(record_id)
        try:
            from pearscarf.storage.store import enqueue_for_curation

            enqueue_for_curation(record_id)
        except Exception as exc:
            log.write(
                self.name,
                "--",
                "warning",
                f"failed to enqueue {record_id} for curation: {exc}",
            )

    def _mark_indexed(self, record_id: str) -> None:
        with _get_conn() as conn:
            conn.execute("UPDATE records SET indexed = TRUE WHERE id = %s", (record_id,))
            conn.commit()
