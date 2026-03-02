"""Indexer — background agent that processes records into the knowledge graph.

Polls for unindexed records, extracts entities/relationships/facts via LLM,
resolves against existing graph, and writes results.
"""

from __future__ import annotations

import json
import threading
import traceback

import anthropic

from pearscaff import graph, log
from pearscaff.config import ANTHROPIC_API_KEY, MODEL
from pearscaff.db import _get_conn, init_db


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
    """Background agent that indexes records into the knowledge graph."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _build_entity_types_block(self) -> str:
        """Build the entity types section of the extraction prompt."""
        types = graph.list_entity_types()
        lines = []
        for et in types:
            fields = ", ".join(et["extract_fields"])
            lines.append(f"- {et['name']}: {et['description']} Fields: {fields}")
        return "\n".join(lines)

    def _build_content(self, record: dict) -> str:
        """Build the record content string for the extraction prompt."""
        conn = _get_conn()
        record_type = record["type"]

        if record_type == "email":
            row = conn.execute(
                "SELECT sender, recipient, subject, body, received_at "
                "FROM emails WHERE record_id = ?",
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

    def _extract(self, record: dict) -> dict:
        """Call LLM to extract entities, relationships, and facts."""
        entity_types_block = self._build_entity_types_block()
        content = self._build_content(record)

        prompt = EXTRACTION_TEMPLATE.format(
            record_type=record["type"],
            entity_types_block=entity_types_block,
            record_id=record["id"],
            content=content,
        )

        response = self._client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        # Parse JSON — strip any markdown fences
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        return json.loads(text)

    def _resolve_entity(self, extracted: dict) -> str:
        """Find existing entity or create a new one. Returns entity ID."""
        entity_type = extracted["type"]
        name = extracted["name"]
        metadata = extracted.get("metadata", {})

        # Try metadata match (email for persons, domain for companies)
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
        """Full pipeline: extract, resolve, write graph, mark indexed."""
        record_id = record["id"]

        log.write("indexer", "--", "action", f"processing {record_id}")

        try:
            result = self._extract(record)
        except json.JSONDecodeError as exc:
            log.write("indexer", "--", "error", f"JSON parse error for {record_id}: {exc}")
            self._mark_indexed(record_id)
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

        # Resolve entities — map name → entity_id
        name_to_id: dict[str, str] = {}
        for ent in entities:
            try:
                eid = self._resolve_entity(ent)
                name_to_id[ent["name"]] = eid
                log.write(
                    "indexer", "--", "action",
                    f"entity '{ent['name']}' → {eid}",
                )
            except Exception as exc:
                log.write("indexer", "--", "error", f"entity resolve failed: {exc}")

        # Create edges
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

        # Upsert facts
        facts_written = 0
        for fact in facts:
            entity_id = name_to_id.get(fact.get("entity"))
            if entity_id:
                try:
                    graph.upsert_fact(
                        entity_id, fact["attribute"], fact["value"], record_id
                    )
                    facts_written += 1
                except Exception as exc:
                    log.write("indexer", "--", "error", f"fact upsert failed: {exc}")

        log.write(
            "indexer", "--", "action",
            f"wrote {edges_created} edges, {facts_written} facts for {record_id}",
        )

        self._mark_indexed(record_id)
        log.write("indexer", "--", "action", f"marked {record_id} as indexed")

    def _mark_indexed(self, record_id: str) -> None:
        conn = _get_conn()
        conn.execute(
            "UPDATE records SET indexed = 1 WHERE id = ?", (record_id,)
        )
        conn.commit()

    def _loop(self) -> None:
        init_db()
        while not self._stop.is_set():
            try:
                conn = _get_conn()
                rows = conn.execute(
                    "SELECT id, type, source, created_at, raw FROM records "
                    "WHERE indexed = 0 ORDER BY created_at"
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
