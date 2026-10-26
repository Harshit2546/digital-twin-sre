"""
Tests for environment and docker-compose indexer.
"""

from pathlib import Path
import pytest
from indexer.env_reader import (
    extract_env_entry,
    index_environment,
    parse_docker_compose,
    parse_env_file,
)
from indexer.models import EdgeType, NodeType, SystemTopologyGraph


def test_extract_env_entry_unconditional_masking():
    # Regular variable
    node = extract_env_entry("PORT=8080", 1, ".env")
    assert node is not None
    assert node.id == "env:PORT"
    assert node.metadata["value"] == "[MASKED]"
    assert node.metadata["has_default"] is True

    # Secret variable
    secret_node = extract_env_entry("SUPER_SECRET_KEY=12345", 2, ".env")
    assert secret_node is not None
    assert secret_node.id == "env:SUPER_SECRET_KEY"
    assert secret_node.metadata["value"] == "[MASKED]"

    # Comments and empty lines
    assert extract_env_entry("# this is a comment", 3, ".env") is None
    assert extract_env_entry("   ", 4, ".env") is None

    # Export syntax
    export_node = extract_env_entry("export DB_HOST=localhost", 5, ".env")
    assert export_node is not None
    assert export_node.id == "env:DB_HOST"


def test_parse_env_file(tmp_path: Path):
    env_file = tmp_path / ".env.example"
    env_file.write_text(
        "# Configuration\n"
        "DATABASE_URL=postgres://user:pass@localhost:5432/db\n"
        "REDIS_PORT=6379\n"
        "EMPTY_VAR=\n"
    )

    nodes = parse_env_file(env_file, tmp_path)
    assert len(nodes) == 3

    ids = {n.id for n in nodes}
    assert "env:DATABASE_URL" in ids
    assert "env:REDIS_PORT" in ids
    assert "env:EMPTY_VAR" in ids

    # Line numbers
    db_node = next(n for n in nodes if n.id == "env:DATABASE_URL")
    assert db_node.line_number == 2
    assert db_node.metadata["has_default"] is True

    empty_node = next(n for n in nodes if n.id == "env:EMPTY_VAR")
    assert empty_node.line_number == 4
    assert empty_node.metadata["has_default"] is False


def test_parse_docker_compose(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        "version: '3.8'\n"
        "services:\n"
        "  web:\n"
        "    image: my-app\n"
        "    ports:\n"
        "      - '8080:8080'\n"
        "    depends_on:\n"
        "      - db\n"
        "      - redis\n"
        "    environment:\n"
        "      - DB_HOST=db\n"
        "      - DB_PORT=5432\n"
        "  db:\n"
        "    image: postgres:15\n"
        "  redis:\n"
        "    image: redis:7\n"
    )

    nodes, edges = parse_docker_compose(compose_file, tmp_path)

    # 3 services + 2 env vars
    svc_nodes = [n for n in nodes if n.node_type == NodeType.EXTERNAL_SERVICE]
    env_nodes = [n for n in nodes if n.node_type == NodeType.ENV_VAR]

    assert len(svc_nodes) == 3
    assert len(env_nodes) == 2

    # Edges
    depends_edges = [e for e in edges if e.edge_type == EdgeType.DEPENDS_ON]
    reads_env_edges = [e for e in edges if e.edge_type == EdgeType.READS_ENV]

    assert len(depends_edges) == 2
    assert {e.target_id for e in depends_edges} == {"external_svc:db", "external_svc:redis"}
    assert len(reads_env_edges) == 2


def test_index_environment_integration(tmp_path: Path):
    # Setup workspace with .env and docker-compose
    (tmp_path / ".env.example").write_text("API_KEY=dummy\n")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  api:\n"
        "    environment:\n"
        "      API_KEY: dummy\n"
    )

    graph = SystemTopologyGraph()
    index_environment(tmp_path, graph)

    assert "env:API_KEY" in graph.nodes
    assert "external_svc:api" in graph.nodes
    assert len(graph.get_outward("external_svc:api", EdgeType.READS_ENV)) == 1
