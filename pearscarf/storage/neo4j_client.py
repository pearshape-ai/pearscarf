"""Neo4j connection management.

Lazy-initializes a driver from config. Use get_session() for queries.
"""

from __future__ import annotations

from contextlib import contextmanager

from neo4j import GraphDatabase, NotificationDisabledClassification

from pearscarf.config import NEO4J_PASSWORD, NEO4J_URL, NEO4J_USER

_driver = None


def get_driver():
    """Lazy-init and return the Neo4j driver.

    `UNRECOGNIZED`-classification notifications are disabled at the server
    level — pearscarf legitimately queries every canonical entity-type
    label on each call to `graph_stats()` etc., and on a freshly-wiped
    graph most of those labels have no nodes yet. The driver would
    otherwise log one WARNING per missing label per call.
    """
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            NEO4J_URL,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            notifications_disabled_classifications=[
                NotificationDisabledClassification.UNRECOGNIZED,
            ],
        )
    return _driver


@contextmanager
def get_session():
    """Yield a Neo4j session. Use as context manager."""
    driver = get_driver()
    with driver.session() as session:
        yield session


def close():
    """Shut down the Neo4j driver."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
