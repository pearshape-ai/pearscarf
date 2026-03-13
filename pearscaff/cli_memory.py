"""Memory inspection CLI commands — read-only tools for exploring the knowledge graph."""

from __future__ import annotations

import time

import click

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
    """List entities and recent facts from the knowledge graph."""
    from pearscaff.db import _get_conn, init_db

    init_db()
    with _get_conn() as conn:
        # Get entities
        entities = conn.execute(
            "SELECT id, type as entity_type, name, metadata, created_at "
            "FROM entities ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()

        results = []
        for e in entities:
            d = dict(e)
            d["metadata"] = d["metadata"] if d["metadata"] else {}
            results.append(d)

        # If fewer entities than limit, fill with recent facts
        remaining = limit - len(results)
        if remaining > 0:
            facts = conn.execute(
                "SELECT f.id, f.attribute, f.value, f.updated_at, e.name as entity_name "
                "FROM facts f JOIN entities e ON f.entity_id = e.id "
                "ORDER BY f.updated_at DESC LIMIT %s",
                (remaining,),
            ).fetchall()
            for f in facts:
                results.append(dict(f))

    return results


def _search(query: str, limit: int = 10) -> list[dict]:
    """Search entities + vector store."""
    from pearscaff import graph, vectorstore

    results = []

    # Entity search
    entities = graph.search_entities(query, limit=limit)
    for e in entities:
        results.append({
            "text": f"[{e['type']}] {e['name']}",
            "metadata": e.get("metadata", {}),
        })

    # Vector search
    remaining = limit - len(results)
    if remaining > 0:
        vec_results = vectorstore.query(query, n_results=remaining)
        for r in vec_results:
            subject = r["metadata"].get("subject", "")
            sender = r["metadata"].get("sender", "")
            text = f"'{subject}' from {sender}" if subject else (r["content"][:150] if r["content"] else r["id"])
            results.append({
                "text": text,
                "distance": r["distance"],
                "metadata": r["metadata"],
            })

    return results


def _get_entity(name: str) -> dict | None:
    """Look up entity by name — search, get facts, traverse."""
    from pearscaff import graph

    # Search by name across all types
    entities = graph.search_entities(name, limit=1)
    if not entities:
        return None

    entity = entities[0]
    entity_id = entity["id"]

    # Get facts
    facts = graph.get_entity_facts(entity_id)

    # Traverse for connections
    traversal = graph.traverse_graph(entity_id, max_depth=2)

    return {
        "name": entity["name"],
        "type": entity["type"],
        "metadata": entity.get("metadata", {}),
        "facts": facts,
        "connections": traversal.get("edges", []),
    }


def _graph_stats() -> dict:
    """Get entity/edge/fact counts from Postgres."""
    from pearscaff.db import _get_conn, init_db

    init_db()
    with _get_conn() as conn:
        total_entities = conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]
        total_edges = conn.execute("SELECT COUNT(*) as c FROM edges").fetchone()["c"]
        total_facts = conn.execute("SELECT COUNT(*) as c FROM facts").fetchone()["c"]

        # Entity type breakdown
        type_rows = conn.execute(
            "SELECT type, COUNT(*) as c FROM entities GROUP BY type ORDER BY c DESC"
        ).fetchall()
        entity_counts = {r["type"]: r["c"] for r in type_rows}

        # Relationship type breakdown
        rel_rows = conn.execute(
            "SELECT relationship, COUNT(*) as c FROM edges GROUP BY relationship ORDER BY c DESC"
        ).fetchall()
        rel_counts = {r["relationship"]: r["c"] for r in rel_rows}

    return {
        "total_entities": total_entities,
        "total_edges": total_edges,
        "total_facts": total_facts,
        "entity_counts": entity_counts,
        "rel_counts": rel_counts,
    }


def _get_memories_for_record(record_id: str) -> list[dict]:
    """Get facts and edges sourced from a specific record."""
    from pearscaff.db import _get_conn, init_db

    init_db()
    with _get_conn() as conn:
        results = []

        # Facts from this record
        facts = conn.execute(
            "SELECT f.attribute, f.value, e.name as entity_name "
            "FROM facts f JOIN entities e ON f.entity_id = e.id "
            "WHERE f.source_record = %s",
            (record_id,),
        ).fetchall()
        for f in facts:
            d = dict(f)
            d["type"] = "fact"
            results.append(d)

        # Edges from this record
        edges = conn.execute(
            'SELECT e1.name as "from", e2.name as "to", ed.relationship '
            "FROM edges ed "
            "JOIN entities e1 ON ed.from_entity = e1.id "
            "JOIN entities e2 ON ed.to_entity = e2.id "
            "WHERE ed.source_record = %s",
            (record_id,),
        ).fetchall()
        for e in edges:
            d = dict(e)
            d["type"] = "relationship"
            results.append(d)

    return results


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
