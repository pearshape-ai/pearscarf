"""Memory inspection CLI commands — read-only tools for exploring the memory layer."""

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
        if "memory" in m:
            content = m["memory"]
        elif "name" in m:
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
            memory = r.get("memory", r.get("text", r.get("content", str(r))))
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
    labels = ", ".join(entity_data.get("labels", []))
    lines.append(f"  {name} ({labels})")

    props = entity_data.get("properties", {})
    if props:
        for k, v in props.items():
            if k != "name":
                lines.append(f"    {k}: {v}")

    facts = entity_data.get("facts", [])
    if facts:
        lines.append("  Facts:")
        for f in facts:
            source = f" [from: {f['source']}]" if f.get("source") else ""
            lines.append(f"    {f['attribute']}: {f['value']}{source}")

    connections = entity_data.get("connections", [])
    if connections:
        lines.append("  Connections:")
        for c in connections:
            target = c.get("target", c.get("target_name", "?"))
            rel = c.get("rel", c.get("relationship", "?"))
            extra = ""
            if c.get("target_labels"):
                extra = f" ({', '.join(c['target_labels'])})"
            elif c.get("depth") is not None:
                extra = f" (depth: {c['depth']})"
            lines.append(f"    --{rel}--> {target}{extra}")

    return lines


def format_graph_stats(stats: dict) -> list[str]:
    """Format graph stats for display."""
    if "error" in stats:
        return [f"Error: {stats['error']}"]

    lines = []
    lines.append(f"  Nodes: {stats.get('total_nodes', 0)}")
    lines.append(f"  Relationships: {stats.get('total_relationships', 0)}")
    if stats.get("total_facts"):
        lines.append(f"  Facts: {stats['total_facts']}")

    node_counts = stats.get("node_counts", {})
    if node_counts:
        lines.append("  Node types:")
        for label, count in node_counts.items():
            lines.append(f"    {label}: {count}")

    rel_counts = stats.get("rel_counts", {})
    if rel_counts:
        lines.append("  Relationship types:")
        for rel, count in rel_counts.items():
            lines.append(f"    {rel}: {count}")

    most_connected = stats.get("most_connected", [])
    if most_connected:
        lines.append("  Most connected:")
        for node in most_connected:
            labels = ", ".join(node.get("labels", []))
            lines.append(f"    {node['name']} ({labels}) — {node['degree']} connections")

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
        elif "memory" in m:
            lines.append(f"  {i}. {m['memory']}")
        else:
            lines.append(f"  {i}. {m}")
    return lines


# ---------------------------------------------------------------------------
# CLI command group
# ---------------------------------------------------------------------------


@cli.group()
def memory():
    """Inspect the memory layer."""


def _get_memory_id(m: dict) -> str:
    """Extract a stable identifier from a memory dict for deduplication."""
    if "id" in m:
        return str(m["id"])
    # Fallback: hash the content
    content = m.get("memory", m.get("name", m.get("attribute", str(m))))
    return f"_hash_{hash(content)}"


@memory.command("list")
@click.option("--limit", default=10, help="Max items to show.")
@click.option("-f", "--follow", is_flag=True, help="Watch for new memories in real-time.")
@click.option("--interval", default=2.0, help="Poll interval in seconds (with --follow).")
def memory_list(limit: int, follow: bool, interval: float) -> None:
    """List stored memories."""
    from pearscaff.memory import get_memory_backend

    backend = get_memory_backend()
    results = backend.get_all(limit=limit)
    for line in format_memory_list(results):
        click.echo(line)

    if not follow:
        return

    # Track what we've already shown
    seen = {_get_memory_id(m) for m in results}
    click.echo(click.style("\n  — following (Ctrl+C to stop) —", fg="yellow"))

    try:
        while True:
            time.sleep(interval)
            results = backend.get_all(limit=limit)
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
    from pearscaff.memory import get_memory_backend

    backend = get_memory_backend()
    results = backend.search(query, limit=limit)
    for line in format_search_results(results):
        click.echo(line)


@memory.command("entity")
@click.argument("name")
def memory_entity(name: str) -> None:
    """Look up an entity and its connections."""
    from pearscaff.memory import get_memory_backend

    backend = get_memory_backend()
    entity = backend.get_entity(name)
    for line in format_entity(entity):
        click.echo(line)


@memory.command("graph")
def memory_graph() -> None:
    """Show graph overview and stats."""
    from pearscaff.memory import get_memory_backend

    backend = get_memory_backend()
    stats = backend.graph_stats()
    for line in format_graph_stats(stats):
        click.echo(line)


@memory.command("record")
@click.argument("record_id")
def memory_record(record_id: str) -> None:
    """Show memories extracted from a specific record."""
    from pearscaff.memory import get_memory_backend

    backend = get_memory_backend()
    results = backend.get_memories_for_record(record_id)
    for line in format_record_memories(results):
        click.echo(line)
