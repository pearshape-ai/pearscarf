"""Indexer — background agent that processes records into the knowledge graph.

Polls for unindexed records and runs LLM extraction → entity resolution →
graph population → Qdrant embedding.
"""

from __future__ import annotations

import json
import threading
import traceback

import anthropic

from pearscaff import graph, log, store
from pearscaff.config import ANTHROPIC_API_KEY, MODEL
from pearscaff.db import _get_conn, init_db
from pearscaff.tracing import trace_span

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_TEMPLATE = """\
Given this {record_type} record, extract all entities, relationships, and facts.
Respond in JSON only, no other text.

Entity types to extract:
{entity_types_block}

Record ({record_id}):
{content}

Respond with exactly this JSON structure:
{{
  "entities": [
    {{"type": "person", "name": "Full Name", "metadata": {{"email": "...", "role": "..."}}}}
  ],
  "relationships": [
    {{"from": "Entity Name", "to": "Entity Name", "type": "relationship_type"}}
  ],
  "facts": [
    {{"entity": "Entity Name", "attribute": "attribute_name", "value": "value"}}
  ]
}}

If no entities, relationships, or facts can be extracted, return empty arrays.\
"""


class Indexer:
    """Background agent that indexes records via LLM extraction."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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

        # Fallback: use raw content from records table
        return record.get("raw") or "(no content)"

    def _build_entity_types_block(self) -> str:
        types = graph.list_entity_types()
        lines = []
        for et in types:
            fields = ", ".join(et["extract_fields"])
            lines.append(f"- {et['name']}: {et['description']} Fields: {fields}")
        return "\n".join(lines)

    def _extract(self, record_type: str, record_id: str, content: str) -> dict:
        """LLM extraction of entities, relationships, and facts."""
        entity_types_block = self._build_entity_types_block()
        prompt = EXTRACTION_TEMPLATE.format(
            record_type=record_type,
            entity_types_block=entity_types_block,
            record_id=record_id,
            content=content,
        )
        with trace_span(
            "indexer.extract",
            run_type="llm",
            metadata={"record_id": record_id, "record_type": record_type},
            inputs={"model": MODEL, "prompt_length": len(prompt)},
        ) as span:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            if span:
                span.end(outputs={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                })
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        return json.loads(text)

    def _resolve_entity(self, extracted: dict) -> str:
        entity_type = extracted["type"]
        name = extracted["name"]
        metadata = extracted.get("metadata", {})

        metadata_match = None
        if entity_type == "person" and metadata.get("email"):
            metadata_match = metadata["email"]
        elif entity_type == "company" and metadata.get("domain"):
            metadata_match = metadata["domain"]

        existing = graph.find_entity(entity_type, name, metadata_match)
        if existing:
            return existing["id"]

        return graph.create_entity(entity_type, name, metadata)

    def _process_record(self, record: dict) -> None:
        """Extract, resolve, and index a single record."""
        record_id = record["id"]
        record_type = record["type"]

        log.write("indexer", "--", "action", f"processing {record_id}")

        with trace_span(
            "indexer.process_record",
            run_type="chain",
            metadata={"record_id": record_id, "record_type": record_type},
        ):
            content = self._build_content(record)

            # Append human context if available
            human_context = record.get("human_context")
            if human_context:
                content += f"\n\nAdditional context from human:\n{human_context}"

            # Step 1: LLM extraction
            try:
                result = self._extract(record_type, record_id, content)
            except json.JSONDecodeError as exc:
                log.write("indexer", "--", "error", f"JSON parse error for {record_id}: {exc}")
                return
            except Exception as exc:
                log.write("indexer", "--", "error", f"extraction failed for {record_id}: {exc}")
                return

            entities = result.get("entities", [])
            relationships = result.get("relationships", [])
            facts = result.get("facts", [])

            log.write(
                "indexer", "--", "result",
                f"extracted {len(entities)} entities, "
                f"{len(relationships)} relationships, {len(facts)} facts",
            )

            # Step 2: Resolve entities
            name_to_id: dict[str, str] = {}
            for ent in entities:
                try:
                    eid = self._resolve_entity(ent)
                    name_to_id[ent["name"]] = eid
                    log.write("indexer", "--", "action", f"entity '{ent['name']}' -> {eid}")
                except Exception as exc:
                    log.write("indexer", "--", "error", f"entity resolve failed: {exc}")

            # Step 3: Create edges
            edges_created = 0
            for rel in relationships:
                from_id = name_to_id.get(rel.get("from"))
                to_id = name_to_id.get(rel.get("to"))
                if from_id and to_id:
                    try:
                        graph.create_edge(from_id, to_id, rel["type"], record_id)
                        edges_created += 1
                    except Exception as exc:
                        log.write("indexer", "--", "error", f"edge create failed: {exc}")

            # Step 4: Upsert facts
            facts_written = 0
            for fact in facts:
                entity_id = name_to_id.get(fact.get("entity"))
                if entity_id:
                    try:
                        graph.upsert_fact(entity_id, fact["attribute"], fact["value"], record_id)
                        facts_written += 1
                    except Exception as exc:
                        log.write("indexer", "--", "error", f"fact upsert failed: {exc}")

            log.write(
                "indexer", "--", "action",
                f"wrote {edges_created} edges, {facts_written} facts for {record_id}",
            )

            # Step 5: Embed in Qdrant
            try:
                metadata = {
                    "type": record_type,
                    "source": record["source"],
                    "created_at": record["created_at"],
                }
                if record_type == "email":
                    email = store.get_email(record_id)
                    if email:
                        metadata["sender"] = email.get("sender", "")
                        metadata["subject"] = email.get("subject", "")
                from pearscaff import vectorstore
                vectorstore.add_record(record_id, content, metadata)
                log.write("indexer", "--", "action", f"embedded {record_id} in Qdrant")
            except Exception as exc:
                log.write("indexer", "--", "error", f"embedding failed for {record_id}: {exc}")

            self._mark_indexed(record_id)
            log.write("indexer", "--", "action", f"indexed {record_id}")

    def _mark_indexed(self, record_id: str) -> None:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE records SET indexed = TRUE WHERE id = %s", (record_id,)
            )
            conn.commit()

    def _loop(self) -> None:
        init_db()
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
