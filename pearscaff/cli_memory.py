"""Memory inspection CLI commands — read-only tools for exploring the knowledge graph."""

from __future__ import annotations

import time

import click

from pearscaff import graph, vectorstore
from pearscaff.cli import cli


# ---------------------------------------------------------------------------
# Formatting helpers (used by both CLI and REPL)
# ---------------------------------------------------------------------------


def format_memory_list(memories: list[dict]) -> list[str]:
    """Format a list of memories for display."""
    if not memories:
        return ["No memories found."]
    lines = []
    for i, m in enumerate(memories, 1):
        if "name" in m:
            content = f"[{m.get('entity_type', m.get('type', '?'))}] {m['name']}"
            if m.get("metadata"):
                content += f"  {m['metadata']}"
        elif "attribute" in m:
            content = f"{m.get('entity_name', '?')}.{m['attribute']} = {m['value']}"
        else:
            content = str(m)

        mem_id = m.get("id", "")
        created = m.get("created_at", m.get("updated_at", ""))
        prefix = f"{mem_id}  " if mem_id else ""
        suffix = f"  ({created})" if created else ""
        lines.append(f"  {i}. {prefix}{content}{suffix}")
    return lines


def format_search_results(results: list[dict]) -> list[str]:
    """Format search results for display."""
    if not results:
        return ["No results found."]
    lines = []
    for i, r in enumerate(results, 1):
        if isinstance(r, dict):
            memory = r.get("text", r.get("content", str(r)))
            score = r.get("score", r.get("distance", ""))
            score_str = f" (score: {score:.3f})" if isinstance(score, float) else ""
            meta = r.get("metadata", {})
            meta_str = ""
            if meta:
                record_id = meta.get("record_id", "")
                if record_id:
                    meta_str = f"  [from: {record_id}]"
            lines.append(f"  {i}. {memory}{score_str}{meta_str}")
        else:
            lines.append(f"  {i}. {r}")
    return lines


def format_entity(entity_data: dict | None) -> list[str]:
    """Format entity lookup results."""
    if not entity_data:
        return ["Entity not found."]
    if "error" in entity_data:
        return [f"Error looking up entity: {entity_data['error']}"]

    lines = []
    name = entity_data.get("name", "?")
    etype = entity_data.get("type", "?")
    lines.append(f"  {name} ({etype})")

    metadata = entity_data.get("metadata", {})
    if metadata:
        for k, v in metadata.items():
            lines.append(f"    {k}: {v}")

    facts = entity_data.get("facts", [])
    if facts:
        lines.append("  Facts:")
        for f in facts:
            source = f" [from: {f['source_record']}]" if f.get("source_record") else ""
            lines.append(f"    {f['attribute']}: {f['value']}{source}")

    connections = entity_data.get("connections", [])
    if connections:
        lines.append("  Connections:")
        for c in connections:
            target = c.get("to_entity", "?")
            rel = c.get("relationship", "?")
            depth = c.get("depth")
            extra = f" (depth: {depth})" if depth is not None else ""
            lines.append(f"    --{rel}--> {target}{extra}")

    return lines


def format_graph_stats(stats: dict) -> list[str]:
    """Format graph stats for display."""
    if "error" in stats:
        return [f"Error: {stats['error']}"]

    lines = []
    lines.append(f"  Entities: {stats.get('total_entities', 0)}")
    lines.append(f"  Edges: {stats.get('total_edges', 0)}")
    lines.append(f"  Facts: {stats.get('total_facts', 0)}")

    entity_counts = stats.get("entity_counts", {})
    if entity_counts:
        lines.append("  Entity types:")
        for etype, count in entity_counts.items():
            lines.append(f"    {etype}: {count}")

    rel_counts = stats.get("rel_counts", {})
    if rel_counts:
        lines.append("  Relationship types:")
        for rel, count in rel_counts.items():
            lines.append(f"    {rel}: {count}")

    return lines


def format_record_memories(memories: list[dict]) -> list[str]:
    """Format memories linked to a source record."""
    if not memories:
        return ["No memories found for this record."]
    lines = []
    for i, m in enumerate(memories, 1):
        mem_type = m.get("type", "memory")
        if mem_type == "fact":
            lines.append(f"  {i}. [fact] {m.get('entity_name', '?')}.{m['attribute']} = {m['value']}")
        elif mem_type == "relationship":
            lines.append(f"  {i}. [rel] {m.get('from', '?')} --{m['relationship']}--> {m.get('to', '?')}")
        else:
            lines.append(f"  {i}. {m}")
    return lines


# ---------------------------------------------------------------------------
# Direct graph/DB query helpers
# ---------------------------------------------------------------------------


def _get_all(limit: int = 10) -> list[dict]:
    """List recent records from Qdrant."""
    try:
        client = vectorstore._get_client()
        results, _ = client.scroll(
            collection_name=vectorstore.COLLECTION_NAME,
            limit=limit,
        )
        items = []
        for point in results:
            payload = point.payload or {}
            items.append({
                "id": payload.get("record_id", ""),
                "name": payload.get("subject", payload.get("content", "")[:60]),
                "entity_type": payload.get("type", "record"),
                "metadata": payload.get("sender", ""),
                "created_at": "",
            })
        return items
    except Exception:
        return []


def _search(query: str, limit: int = 10) -> list[dict]:
    """Search records via Qdrant semantic search."""
    try:
        results = vectorstore.query(query, n_results=limit)
        return [
            {
                "text": r.get("content", ""),
                "score": r.get("score", 0.0),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ]
    except Exception:
        return []


def _get_entity(name: str) -> dict | None:
    """Look up entity by name via Neo4j."""
    results = graph.search_entities(name, limit=1)
    if not results:
        return None

    entity = results[0]
    eid = entity["id"]

    # Get full details
    full = graph.get_entity(eid)
    if not full:
        return entity

    # Add facts
    facts = graph.get_entity_facts(eid)
    full["facts"] = [
        {
            "attribute": "claim",
            "value": f.get("claim", ""),
            "source_record": f.get("source_record", ""),
        }
        for f in facts
    ]

    # Add connections (1 hop)
    traversal = graph.traverse_graph(eid, max_depth=1)
    full["connections"] = [
        {
            "to_entity": e.get("name", "?"),
            "relationship": next(
                (edge["relationship"] for edge in traversal["edges"]
                 if edge["to"] == e["id"] or edge["from"] == e["id"]),
                "?",
            ),
        }
        for e in traversal.get("entities", [])
    ]

    return full


def _graph_stats() -> dict:
    """Get entity/edge/fact counts from Neo4j."""
    try:
        return graph.graph_stats()
    except Exception as e:
        return {"error": str(e)}


def _get_memories_for_record(record_id: str) -> list[dict]:
    """Get facts and edges sourced from a specific record."""
    try:
        return graph.get_nodes_by_source_record(record_id)
    except Exception as e:
        return [{"type": "error", "message": str(e)}]


# ---------------------------------------------------------------------------
# CLI command group
# ---------------------------------------------------------------------------


@cli.group()
def memory():
    """Inspect the knowledge graph."""


def _get_memory_id(m: dict) -> str:
    """Extract a stable identifier from a memory dict for deduplication."""
    if "id" in m:
        return str(m["id"])
    content = m.get("name", m.get("attribute", str(m)))
    return f"_hash_{hash(content)}"


@memory.command("list")
@click.option("--limit", default=10, help="Max items to show.")
@click.option("-f", "--follow", is_flag=True, help="Watch for new memories in real-time.")
@click.option("--interval", default=2.0, help="Poll interval in seconds (with --follow).")
def memory_list(limit: int, follow: bool, interval: float) -> None:
    """List stored memories."""
    results = _get_all(limit=limit)
    for line in format_memory_list(results):
        click.echo(line)

    if not follow:
        return

    seen = {_get_memory_id(m) for m in results}
    click.echo(click.style("\n  — following (Ctrl+C to stop) —", fg="yellow"))

    try:
        while True:
            time.sleep(interval)
            results = _get_all(limit=limit)
            new = [m for m in results if _get_memory_id(m) not in seen]
            for m in new:
                seen.add(_get_memory_id(m))
                for line in format_memory_list([m]):
                    ts = click.style(time.strftime("%H:%M:%S"), fg="blue")
                    click.echo(f"  {ts} {line.strip()}")
    except KeyboardInterrupt:
        click.echo("\n  stopped.")


@memory.command("search")
@click.argument("query")
@click.option("--limit", default=10, help="Max results.")
def memory_search(query: str, limit: int) -> None:
    """Search memories by query."""
    results = _search(query, limit=limit)
    for line in format_search_results(results):
        click.echo(line)


@memory.command("entity")
@click.argument("name")
def memory_entity(name: str) -> None:
    """Look up an entity and its connections."""
    entity = _get_entity(name)
    for line in format_entity(entity):
        click.echo(line)


@memory.command("graph")
def memory_graph() -> None:
    """Show graph overview and stats."""
    stats = _graph_stats()
    for line in format_graph_stats(stats):
        click.echo(line)


@memory.command("record")
@click.argument("record_id")
def memory_record(record_id: str) -> None:
    """Show memories extracted from a specific record."""
    results = _get_memories_for_record(record_id)
    for line in format_record_memories(results):
        click.echo(line)
