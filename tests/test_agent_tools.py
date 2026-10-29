"""
Tests for AgentTools provider-agnostic tools and graph integrations.
"""

import json
from pathlib import Path
import pytest
from agent.tools import AgentTools
from indexer.models import Edge, EdgeType, Node, NodeType, SystemTopologyGraph


def test_openai_tool_schemas():
    tools = AgentTools()
    schemas = tools.get_openai_tool_schemas()

    assert len(schemas) >= 7
    names = {s["function"]["name"] for s in schemas}
    assert "check_env_drift" in names
    assert "get_blast_radius" in names
    assert "read_file" in names
    assert "edit_file" in names
    assert "test_fix" in names


def test_check_env_drift():
    graph = SystemTopologyGraph()

    # Define a code function reading an env variable that is not in any template
    func_node = Node(id="symbol:app.py#checkout", name="checkout", node_type=NodeType.SYMBOL)
    env_node = Node(id="env:REDIS_PORT", name="REDIS_PORT", node_type=NodeType.ENV_VAR, metadata={"has_default": False})

    graph.add_node(func_node)
    graph.add_node(env_node)
    graph.add_edge(Edge(source_id="symbol:app.py#checkout", target_id="env:REDIS_PORT", edge_type=EdgeType.READS_ENV))

    tools = AgentTools(graph=graph)
    res_str = tools.check_env_drift()
    res = json.loads(res_str)

    assert res["status"] == "drift_detected"
    assert res["missing_count"] == 1
    assert res["missing_variables"][0]["variable"] == "REDIS_PORT"


def test_get_blast_radius():
    graph = SystemTopologyGraph()

    nodes = [
        Node(id="endpoint:POST /pay", name="POST /pay", node_type=NodeType.ENDPOINT),
        Node(id="symbol:pay", name="pay", node_type=NodeType.SYMBOL),
        Node(id="env:STRIPE_KEY", name="STRIPE_KEY", node_type=NodeType.ENV_VAR),
    ]
    for n in nodes:
        graph.add_node(n)

    graph.add_edge(Edge("endpoint:POST /pay", "symbol:pay", EdgeType.HANDLES_ROUTE))
    graph.add_edge(Edge("symbol:pay", "env:STRIPE_KEY", EdgeType.READS_ENV))

    tools = AgentTools(graph=graph)
    res_str = tools.get_blast_radius("env:STRIPE_KEY")
    res = json.loads(res_str)

    assert res["impact_count"] == 3
    ids = {e["id"] for e in res["impacted_entities"]}
    assert "env:STRIPE_KEY" in ids
    assert "symbol:pay" in ids
    assert "endpoint:POST /pay" in ids


def test_read_and_edit_file(tmp_path: Path):
    test_file = tmp_path / "service.py"
    test_file.write_text("port = 8000\nhost = '0.0.0.0'\n")

    tools = AgentTools(workspace_root=tmp_path)

    # 1. Read
    content = tools.read_file("service.py", 1, 2)
    assert "port = 8000" in content

    # 2. Edit success
    edit_res = tools.edit_file("service.py", "port = 8000", "port = 9000")
    assert "Success" in edit_res
    assert test_file.read_text() == "port = 9000\nhost = '0.0.0.0'\n"

    # 3. Edit failure (target not found)
    fail_res = tools.edit_file("service.py", "missing_string", "new_val")
    assert "Error: old_str not found" in fail_res


def test_dispatch():
    graph = SystemTopologyGraph()
    graph.add_node(Node(id="env:PORT", name="PORT", node_type=NodeType.ENV_VAR))

    tools = AgentTools(graph=graph)

    # Dispatch query_graph
    out = tools.dispatch("query_graph", {"node_type": "env_var", "name": "PORT"})
    data = json.loads(out)
    assert data["match_count"] == 1
    assert data["matches"][0]["name"] == "PORT"
