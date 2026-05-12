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
    iid = intents.submit_intent(body="Ship the launch demo.", intent_type="milestone", set_by="hex")
    assert iid.startswith("intent_")

    got = intents.get_intent(iid)
    assert got is not None
    assert got["status"] == "todo"
    assert got["intent_type"] == "milestone"
    assert got["parent_record_id"] is None
    assert got["set_by"] == "hex"
    assert "Ship the launch demo." in got["body"]


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
    root = intents.submit_intent(body="launch demo", intent_type="milestone")
    impl = intents.submit_intent(body="implement", parent_record_id=root, intent_type="task")
    deploy = intents.submit_intent(body="deploy", parent_record_id=root, intent_type="task")
    sub_impl = intents.submit_intent(body="design API", parent_record_id=impl, intent_type="task")

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


def test_set_intent_type_clears_with_none(clean_db) -> None:
    iid = intents.submit_intent(body="x", intent_type="task")
    intents.set_intent_type(iid, None)
    got = intents.get_intent(iid)
    assert got["intent_type"] is None


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
