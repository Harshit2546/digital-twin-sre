"""
Tests for System Topology Graph models and graph algorithms.
"""

import pytest
from indexer.models import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    SystemTopologyGraph,
)


def test_node_creation_and_registration():
    graph = SystemTopologyGraph()

    endpoint = Node(
        id="endpoint:POST /checkout",
        name="POST /checkout",
        node_type=NodeType.ENDPOINT,
        file_path="app.py",
        line_number=10,
    )
    function = Node(
        id="symbol:app.py#checkout",
        name="checkout",
        node_type=NodeType.SYMBOL,
        file_path="app.py",
        line_number=12,
    )

    graph.add_node(endpoint)
    graph.add_node(function)

    assert "endpoint:POST /checkout" in graph.nodes
    assert "symbol:app.py#checkout" in graph.nodes
    assert graph.nodes["endpoint:POST /checkout"].name == "POST /checkout"


def test_edge_addition_and_traversal():
    graph = SystemTopologyGraph()

    node_endpoint = Node(
        id="endpoint:POST /checkout",
        name="POST /checkout",
        node_type=NodeType.ENDPOINT,
    )
    node_func = Node(
        id="symbol:app.py#checkout",
        name="checkout",
        node_type=NodeType.SYMBOL,
    )
    node_env = Node(
        id="env:DB_URL",
        name="DB_URL",
        node_type=NodeType.ENV_VAR,
    )

    graph.add_node(node_endpoint)
    graph.add_node(node_func)
    graph.add_node(node_env)

    # endpoint -> handles_route -> func
    graph.add_edge(Edge(
        source_id=node_endpoint.id,
        target_id=node_func.id,
        edge_type=EdgeType.HANDLES_ROUTE,
    ))
    # func -> reads_env -> env
    graph.add_edge(Edge(
        source_id=node_func.id,
        target_id=node_env.id,
        edge_type=EdgeType.READS_ENV,
    ))

    # Test forward lookups
    outward = graph.get_outward(node_endpoint.id)
    assert len(outward) == 1
    assert outward[0].target_id == node_func.id

    # Test backward lookups
    inward = graph.get_inward(node_env.id)
    assert len(inward) == 1
    assert inward[0].source_id == node_func.id


def test_edge_fails_on_missing_nodes():
    graph = SystemTopologyGraph()
    graph.add_node(Node(id="A", name="A", node_type=NodeType.SYMBOL))

    with pytest.raises(KeyError, match="target node 'B' does not exist"):
        graph.add_edge(Edge(source_id="A", target_id="B", edge_type=EdgeType.CALLS))


def test_blast_radius():
    """
    Dependency chain:
    Endpoint (/checkout) -> Function (checkout) -> Service (OrderService) -> Env (DB_URL)

    If DB_URL breaks, blast radius should include:
    DB_URL, OrderService, checkout, and Endpoint (/checkout).
    """
    graph = SystemTopologyGraph()

    nodes = [
        Node(id="endpoint:checkout", name="checkout", node_type=NodeType.ENDPOINT),
        Node(id="symbol:checkout_func", name="checkout_func", node_type=NodeType.SYMBOL),
        Node(id="symbol:OrderService", name="OrderService", node_type=NodeType.SYMBOL),
        Node(id="env:DB_URL", name="DB_URL", node_type=NodeType.ENV_VAR),
    ]
    for n in nodes:
        graph.add_node(n)

    graph.add_edge(Edge("endpoint:checkout", "symbol:checkout_func", EdgeType.HANDLES_ROUTE))
    graph.add_edge(Edge("symbol:checkout_func", "symbol:OrderService", EdgeType.CALLS))
    graph.add_edge(Edge("symbol:OrderService", "env:DB_URL", EdgeType.READS_ENV))

    # Backward traversal from env:DB_URL
    impacted = graph.blast_radius("env:DB_URL", max_depth=5)

    assert "env:DB_URL" in impacted
    assert "symbol:OrderService" in impacted
    assert "symbol:checkout_func" in impacted
    assert "endpoint:checkout" in impacted
