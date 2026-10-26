"""
System Topology Graph Indexer module.
Parses code AST, environment variables, configuration files, and dependencies
into an in-memory queryable topology graph.
"""

from indexer.code_reader import index_code
from indexer.env_reader import index_environment
from indexer.models import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    SystemTopologyGraph,
)

__all__ = [
    "NodeType",
    "EdgeType",
    "Node",
    "Edge",
    "SystemTopologyGraph",
    "index_environment",
    "index_code",
]
