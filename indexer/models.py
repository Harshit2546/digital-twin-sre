"""
indexer/models.py

In-memory System Topology Graph models representing code symbols, environment
variables, configuration settings, ORM entities, and database tables.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class NodeType(str, Enum):
    """Categorizes the nature of a graph node."""
    ENDPOINT = "endpoint"              # e.g., 'POST /api/orders'
    SYMBOL = "symbol"                  # Function, method, or class
    ENTITY = "entity"                  # ORM Model (e.g. Order class)
    DATABASE_TABLE = "database_table"  # Physical DB table (e.g. 'orders')
    ENV_VAR = "env_var"                # Environment variable (e.g. 'DATABASE_URL')
    CONFIG_KEY = "config_key"          # YAML/JSON config property (e.g. 'server.port')
    EXTERNAL_SERVICE = "external_svc"  # Third-party / Infra (e.g. 'redis', 'stripe')
    PACKAGE = "package"                # Third-party library dependency


class EdgeType(str, Enum):
    """Semantic relationship connecting two graph nodes."""
    HANDLES_ROUTE = "handles_route"    # Endpoint -> Controller Method
    CALLS = "calls"                    # Method A -> Method B
    INJECTS = "injects"                # Class A -> Class B via Dependency Injection
    MANAGES_ENTITY = "manages_entity"  # Repository -> ORM Entity (via generic type)
    MAPS_TO_TABLE = "maps_to_table"    # ORM Entity -> Physical Database Table
    READS_ENV = "reads_env"            # Method / Config -> Environment Variable
    READS_CONFIG = "reads_config"      # Method -> Configuration Key
    CALLS_EXTERNAL = "calls_external"  # Method -> Redis / Third-party HTTP API
    DEPENDS_ON = "depends_on"          # General dependency edge


@dataclass(slots=True)
class Edge:
    """Represents a directed semantic relationship between two nodes."""
    source_id: str
    target_id: str
    edge_type: EdgeType
    confidence: float = 1.0  # 1.0 = exact AST parse; 0.8 = convention; 0.5 = heuristic
    metadata: Dict[str, Any] = field(default_factory=dict)  # line_no, method, snippet


@dataclass(slots=True)
class Node:
    """Represents an atomic element in the system topology."""
    id: str                            # Canonical ID: e.g., 'symbol:orders.py#OrderService'
    name: str                          # Human-readable name: 'OrderService'
    node_type: NodeType
    file_path: Optional[str] = None    # Relative file path in workspace
    line_number: Optional[int] = None  # Definition line number (1-based)
    docstring: Optional[str] = None    # Summary or description
    metadata: Dict[str, Any] = field(default_factory=dict)  # Framework-specific attrs


@dataclass
class SystemTopologyGraph:
    """
    In-memory dual-hashmap graph holding the full system context.
    Provides O(1) lookups and high-speed graph traversals.
    """
    nodes: Dict[str, Node] = field(default_factory=dict)
    adjacency: Dict[str, List[Edge]] = field(default_factory=dict)         # source -> outgoing
    reverse_adjacency: Dict[str, List[Edge]] = field(default_factory=dict) # target -> incoming

    def add_node(self, node: Node) -> None:
        """Register a node in the graph if not already present."""
        if node.id not in self.nodes:
            self.nodes[node.id] = node
            self.adjacency[node.id] = []
            self.reverse_adjacency[node.id] = []

    def add_edge(self, edge: Edge) -> None:
        """Register a directed edge, ensuring endpoints exist in adjacency tables."""
        if edge.source_id not in self.nodes:
            raise KeyError(f"Cannot add edge: source node '{edge.source_id}' does not exist in graph.")
        if edge.target_id not in self.nodes:
            raise KeyError(f"Cannot add edge: target node '{edge.target_id}' does not exist in graph.")
        self.adjacency[edge.source_id].append(edge)
        self.reverse_adjacency[edge.target_id].append(edge)

    def get_outward(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[Edge]:
        """Get all outgoing edges from node_id, optionally filtered by edge_type."""
        edges = self.adjacency.get(node_id, [])
        if edge_type is None:
            return edges
        return [e for e in edges if e.edge_type == edge_type]

    def get_inward(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[Edge]:
        """Get all incoming edges to node_id, optionally filtered by edge_type."""
        edges = self.reverse_adjacency.get(node_id, [])
        if edge_type is None:
            return edges
        return [e for e in edges if e.edge_type == edge_type]

    def blast_radius(self, start_node_id: str, max_depth: int = 4) -> Set[str]:
        """
        Traverse backward (incoming edges) to find all services, endpoints,
        and symbols that depend on start_node_id.
        """
        visited: Set[str] = set()
        queue: List[tuple[str, int]] = [(start_node_id, 0)]

        while queue:
            current_id, depth = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)

            # Inward edges tell us: 'Who depends on current_id?'
            for edge in self.get_inward(current_id):
                if edge.source_id not in visited:
                    queue.append((edge.source_id, depth + 1))

        return visited
