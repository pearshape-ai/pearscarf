"""Neo4j connection management.

Lazy-initializes a driver from config. Use get_session() for queries.
"""

from __future__ import annotations

from contextlib import contextmanager

from neo4j import GraphDatabase

from pearscaff.config import NEO4J_PASSWORD, NEO4J_URL, NEO4J_USER

_driver = None


def get_driver():
    """Lazy-init and return the Neo4j driver."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))
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
