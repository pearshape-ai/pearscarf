"""Integration coverage for the intent submission surface (1.36.0).

Covers the storage layer end-to-end against the test stack: submit,
status / parent / type setters, tree walk, cycle rejection, query
filters. The MCP layer is a thin wrapper; testing the storage CRUD
against a real Postgres validates both.

Requires the isolated test stack — `scripts/test-stack.sh up` and
`pytest --integration`.
"""

from __future__ import annotations

import pytest

from pearscarf.storage import intents
from pearscarf.storage.intents import IntentError

pytestmark = pytest.mark.integration


def test_submit_intent_creates_record_and_state(clean_db) -> None:
    iid = intents.submit_intent(
        body="Ship the launch demo.", intent_type="coordinator", set_by="hex"
    )
    assert iid.startswith("intent_")

    got = intents.get_intent(iid)
    assert got is not None
    assert got["status"] == "todo"
    assert got["intent_type"] == "coordinator"
    assert got["parent_record_id"] is None
    assert got["set_by"] == "hex"
    assert "Ship the launch demo." in got["body"]


def test_submit_intent_defaults_to_executor(clean_db) -> None:
    iid = intents.submit_intent(body="leaf task")
    assert intents.get_intent(iid)["intent_type"] == "executor"


def test_submit_intent_rejects_invalid_intent_type(clean_db) -> None:
    with pytest.raises(IntentError, match="intent_type must be one of"):
        intents.submit_intent(body="x", intent_type="milestone")


def test_submit_intent_rejects_missing_parent(clean_db) -> None:
    with pytest.raises(IntentError, match="parent intent"):
        intents.submit_intent(body="orphan child", parent_record_id="intent_nope")


def test_set_intent_status_updates_sidecar(clean_db) -> None:
    iid = intents.submit_intent(body="do the thing", set_by="hex")
    intents.set_intent_status(iid, "in_progress", set_by="hex")
    got = intents.get_intent(iid)
    assert got["status"] == "in_progress"
    intents.set_intent_status(iid, "done", set_by="hex")
    got = intents.get_intent(iid)
    assert got["status"] == "done"


def test_set_intent_status_rejects_invalid_value(clean_db) -> None:
    iid = intents.submit_intent(body="x", set_by="hex")
    with pytest.raises(IntentError, match="status must be one of"):
        intents.set_intent_status(iid, "bogus", set_by="hex")


def test_set_intent_status_unknown_intent_raises(clean_db) -> None:
    with pytest.raises(IntentError, match="no intent with id"):
        intents.set_intent_status("intent_nope", "done", set_by="hex")


def test_parent_child_tree_walk(clean_db) -> None:
    """Build a 3-level tree, walk via get_intent_tree, verify shape."""
    root = intents.submit_intent(body="launch demo", intent_type="coordinator")
    impl = intents.submit_intent(body="implement", parent_record_id=root, intent_type="coordinator")
    deploy = intents.submit_intent(body="deploy", parent_record_id=root, intent_type="executor")
    sub_impl = intents.submit_intent(
        body="design API", parent_record_id=impl, intent_type="executor"
    )

    tree = intents.get_intent_tree(root)
    assert tree is not None
    assert tree["id"] == root
    child_ids = {c["id"] for c in tree["children"]}
    assert child_ids == {impl, deploy}

    impl_subtree = next(c for c in tree["children"] if c["id"] == impl)
    assert [c["id"] for c in impl_subtree["children"]] == [sub_impl]
    deploy_subtree = next(c for c in tree["children"] if c["id"] == deploy)
    assert deploy_subtree["children"] == []


def test_get_intent_with_children_returns_direct_children_only(clean_db) -> None:
    root = intents.submit_intent(body="root")
    child = intents.submit_intent(body="child", parent_record_id=root)
    grandchild = intents.submit_intent(body="grandchild", parent_record_id=child)

    got = intents.get_intent(root, with_children=True)
    assert got is not None
    assert [c["id"] for c in got["children"]] == [child]
    # Grandchild is not in the direct-children list.
    assert grandchild not in [c["id"] for c in got["children"]]


def test_set_intent_parent_rejects_self(clean_db) -> None:
    iid = intents.submit_intent(body="x")
    with pytest.raises(IntentError, match="cannot be its own parent"):
        intents.set_intent_parent(iid, iid)


def test_set_intent_parent_rejects_cycle(clean_db) -> None:
    a = intents.submit_intent(body="a")
    b = intents.submit_intent(body="b", parent_record_id=a)
    c = intents.submit_intent(body="c", parent_record_id=b)

    # Trying to re-parent `a` under `c` would form a cycle a → b → c → a.
    with pytest.raises(IntentError, match="cycle"):
        intents.set_intent_parent(a, c)


def test_set_intent_parent_clears_to_top_level(clean_db) -> None:
    root = intents.submit_intent(body="root")
    child = intents.submit_intent(body="child", parent_record_id=root)

    intents.set_intent_parent(child, None)
    got = intents.get_intent(child)
    assert got["parent_record_id"] is None


def test_query_intents_filters_by_status(clean_db) -> None:
    a = intents.submit_intent(body="a")
    b = intents.submit_intent(body="b")
    intents.submit_intent(body="c")
    intents.set_intent_status(a, "in_progress")
    intents.set_intent_status(b, "in_progress")

    in_progress = intents.query_intents(status="in_progress")
    assert {i["id"] for i in in_progress} == {a, b}

    todo = intents.query_intents(status="todo")
    assert len(todo) == 1


def test_query_intents_filters_by_parent(clean_db) -> None:
    root = intents.submit_intent(body="root")
    c1 = intents.submit_intent(body="c1", parent_record_id=root)
    c2 = intents.submit_intent(body="c2", parent_record_id=root)
    intents.submit_intent(body="orphan")

    children = intents.query_intents(parent_record_id=root)
    assert {i["id"] for i in children} == {c1, c2}


def test_query_intents_filters_by_intent_type(clean_db) -> None:
    coord = intents.submit_intent(body="coord", intent_type="coordinator")
    exe1 = intents.submit_intent(body="exe1")  # default executor
    exe2 = intents.submit_intent(body="exe2", intent_type="executor")

    coords = intents.query_intents(intent_type="coordinator")
    assert {i["id"] for i in coords} == {coord}
    execs = intents.query_intents(intent_type="executor")
    assert {i["id"] for i in execs} == {exe1, exe2}


# --- 1.39.1: runtime + runtime_config envelope ---


def test_submit_intent_defaults_runtime_to_claude(clean_db) -> None:
    iid = intents.submit_intent(body="x")
    got = intents.get_intent(iid)
    assert got["runtime"] == "claude"
    assert got["runtime_config"] == {}


def test_submit_intent_stores_runtime_config(clean_db) -> None:
    cfg = {"chrome_required": True, "mcp_servers": ["pearscarf-dogfood"], "model": "sonnet"}
    iid = intents.submit_intent(body="x", runtime="claude", runtime_config=cfg)
    got = intents.get_intent(iid)
    assert got["runtime"] == "claude"
    assert got["runtime_config"] == cfg


def test_submit_intent_accepts_non_claude_runtime(clean_db) -> None:
    iid = intents.submit_intent(body="x", runtime="codex", runtime_config={"foo": "bar"})
    got = intents.get_intent(iid)
    assert got["runtime"] == "codex"
    assert got["runtime_config"] == {"foo": "bar"}


def test_submit_intent_rejects_empty_runtime(clean_db) -> None:
    with pytest.raises(IntentError, match="runtime must be a non-empty string"):
        intents.submit_intent(body="x", runtime="")


def test_submit_intent_rejects_non_dict_runtime_config(clean_db) -> None:
    with pytest.raises(IntentError, match="runtime_config must be a dict"):
        intents.submit_intent(body="x", runtime_config=["not", "a", "dict"])


def test_query_intents_filters_by_runtime(clean_db) -> None:
    c1 = intents.submit_intent(body="c1", runtime="claude")
    c2 = intents.submit_intent(body="c2")  # default claude
    cx = intents.submit_intent(body="cx", runtime="codex")

    claudes = intents.query_intents(runtime="claude")
    assert {i["id"] for i in claudes} == {c1, c2}
    codexes = intents.query_intents(runtime="codex")
    assert {i["id"] for i in codexes} == {cx}


def test_submit_intent_rejects_cancelled_parent(clean_db) -> None:
    """Adding a child to a cancelled intent is almost always a bug."""
    parent = intents.submit_intent(body="parent")
    intents.set_intent_status(parent, "cancelled")
    with pytest.raises(IntentError, match="cancelled"):
        intents.submit_intent(body="child", parent_record_id=parent)


def test_set_intent_parent_rejects_cancelled_parent(clean_db) -> None:
    """Re-parenting under a cancelled intent is also rejected."""
    a = intents.submit_intent(body="a")
    b = intents.submit_intent(body="b")
    intents.set_intent_status(b, "cancelled")
    with pytest.raises(IntentError, match="cancelled"):
        intents.set_intent_parent(a, b)


# --- 1.36.1: owner / owner_role / depends_on ---


def test_submit_intent_stores_owner_and_role(clean_db) -> None:
    iid = intents.submit_intent(body="x", owner="hex", owner_role="head-eng")
    got = intents.get_intent(iid)
    assert got["owner"] == "hex"
    assert got["owner_role"] == "head-eng"


def test_submit_intent_stores_depends_on(clean_db) -> None:
    a = intents.submit_intent(body="a")
    b = intents.submit_intent(body="b")
    c = intents.submit_intent(body="c", depends_on=[a, b])
    got = intents.get_intent(c)
    assert sorted(got["depends_on"]) == sorted([a, b])


def test_submit_intent_rejects_missing_dependency(clean_db) -> None:
    with pytest.raises(IntentError, match="dependency intents not found"):
        intents.submit_intent(body="x", depends_on=["intent_nope"])


def test_submit_intent_default_depends_on_is_empty(clean_db) -> None:
    iid = intents.submit_intent(body="x")
    got = intents.get_intent(iid)
    assert got["depends_on"] == []


def test_set_intent_owner_updates_sidecar(clean_db) -> None:
    iid = intents.submit_intent(body="x")
    intents.set_intent_owner(iid, "hex", set_by="operator")
    assert intents.get_intent(iid)["owner"] == "hex"
    intents.set_intent_owner(iid, None, set_by="operator")
    assert intents.get_intent(iid)["owner"] is None


def test_set_intent_owner_role_updates_sidecar(clean_db) -> None:
    iid = intents.submit_intent(body="x")
    intents.set_intent_owner_role(iid, "head-eng", set_by="operator")
    assert intents.get_intent(iid)["owner_role"] == "head-eng"


def test_set_intent_dependencies_replaces_list(clean_db) -> None:
    a = intents.submit_intent(body="a")
    b = intents.submit_intent(body="b")
    target = intents.submit_intent(body="target")

    intents.set_intent_dependencies(target, [a], set_by="operator")
    assert intents.get_intent(target)["depends_on"] == [a]

    intents.set_intent_dependencies(target, [a, b], set_by="operator")
    assert sorted(intents.get_intent(target)["depends_on"]) == sorted([a, b])

    intents.set_intent_dependencies(target, [], set_by="operator")
    assert intents.get_intent(target)["depends_on"] == []


def test_set_intent_dependencies_rejects_cycle(clean_db) -> None:
    """a → b → c → a would cycle on dispatch."""
    a = intents.submit_intent(body="a")
    b = intents.submit_intent(body="b")
    c = intents.submit_intent(body="c")
    intents.set_intent_dependencies(b, [a])
    intents.set_intent_dependencies(c, [b])
    with pytest.raises(IntentError, match="cycle"):
        intents.set_intent_dependencies(a, [c])


def test_set_intent_dependencies_rejects_missing(clean_db) -> None:
    a = intents.submit_intent(body="a")
    with pytest.raises(IntentError, match="dependency intents not found"):
        intents.set_intent_dependencies(a, ["intent_nope"])


def test_query_intents_filters_by_owner(clean_db) -> None:
    a = intents.submit_intent(body="a", owner="hex")
    b = intents.submit_intent(body="b", owner="anton")
    c = intents.submit_intent(body="c", owner="hex")

    hex_intents = intents.query_intents(owner="hex")
    assert {i["id"] for i in hex_intents} == {a, c}
    anton_intents = intents.query_intents(owner="anton")
    assert {i["id"] for i in anton_intents} == {b}


def test_query_intents_filters_by_owner_role(clean_db) -> None:
    e1 = intents.submit_intent(body="x", owner_role="head-eng")
    intents.submit_intent(body="y", owner_role="sre")
    e2 = intents.submit_intent(body="z", owner_role="head-eng")

    eng = intents.query_intents(owner_role="head-eng")
    assert {i["id"] for i in eng} == {e1, e2}
