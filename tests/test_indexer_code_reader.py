"""
Tests for Tree-sitter code reader and Python AST extractor.
"""

from pathlib import Path
import pytest
from indexer.code_reader import index_code
from indexer.env_reader import index_environment
from indexer.extractors.python_extractor import PythonExtractor
from indexer.models import EdgeType, NodeType, SystemTopologyGraph


def test_python_extractor_routes_and_env(tmp_path: Path):
    app_file = tmp_path / "app.py"
    app_file.write_text(
        "import os\n"
        "\n"
        "@app.get('/orders')\n"
        "def get_orders():\n"
        "    port = os.getenv('DB_PORT')\n"
        "    secret = os.environ['JWT_SECRET']\n"
        "    return []\n"
    )

    graph = SystemTopologyGraph()
    extractor = PythonExtractor()
    extractor.extract(app_file, app_file.read_bytes(), tmp_path, graph)

    # 1. Endpoint node
    assert "endpoint:GET /orders" in graph.nodes
    endpoint = graph.nodes["endpoint:GET /orders"]
    assert endpoint.line_number == 3

    # 2. Function node
    assert "symbol:app.py#get_orders" in graph.nodes
    func_node = graph.nodes["symbol:app.py#get_orders"]
    assert func_node.line_number == 4

    # 3. Route edge
    route_edges = graph.get_outward(endpoint.id, EdgeType.HANDLES_ROUTE)
    assert len(route_edges) == 1
    assert route_edges[0].target_id == func_node.id

    # 4. Env edges
    env_edges = graph.get_outward(func_node.id, EdgeType.READS_ENV)
    assert len(env_edges) == 2
    env_targets = {e.target_id for e in env_edges}
    assert "env:DB_PORT" in env_targets
    assert "env:JWT_SECRET" in env_targets


def test_python_extractor_orm_and_calls(tmp_path: Path):
    models_file = tmp_path / "models.py"
    models_file.write_text(
        "class Order(Base):\n"
        "    __tablename__ = 'orders'\n"
        "\n"
        "def validate_order():\n"
        "    pass\n"
        "\n"
        "def process_order():\n"
        "    validate_order()\n"
    )

    graph = SystemTopologyGraph()
    extractor = PythonExtractor()
    extractor.extract(models_file, models_file.read_bytes(), tmp_path, graph)

    # ORM Entity and Table
    assert "entity:models.py#Order" in graph.nodes
    assert "database_table:orders" in graph.nodes
    orm_edges = graph.get_outward("entity:models.py#Order", EdgeType.MAPS_TO_TABLE)
    assert len(orm_edges) == 1
    assert orm_edges[0].target_id == "database_table:orders"

    # Function call
    assert "symbol:models.py#validate_order" in graph.nodes
    assert "symbol:models.py#process_order" in graph.nodes
    call_edges = graph.get_outward("symbol:models.py#process_order", EdgeType.CALLS)
    assert len(call_edges) == 1
    assert call_edges[0].target_id == "symbol:models.py#validate_order"


def test_end_to_end_topology_and_blast_radius(tmp_path: Path):
    """
    Test full integration of environment + code indexing:
    docker-compose.yml defines DB_HOST
    app.py has route /checkout -> checkout() -> reads DB_HOST
    Blast radius of DB_HOST should include checkout() and /checkout!
    """
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  web:\n"
        "    environment:\n"
        "      DB_HOST: db\n"
    )
    (tmp_path / "main.py").write_text(
        "import os\n"
        "\n"
        "@app.post('/checkout')\n"
        "def checkout():\n"
        "    host = os.getenv('DB_HOST')\n"
        "    return {'ok': True}\n"
    )

    graph = SystemTopologyGraph()
    index_environment(tmp_path, graph)
    index_code(tmp_path, graph)

    assert "env:DB_HOST" in graph.nodes
    assert "external_svc:web" in graph.nodes
    assert "endpoint:POST /checkout" in graph.nodes
    assert "symbol:main.py#checkout" in graph.nodes

    # Test blast radius from env:DB_HOST
    impact = graph.blast_radius("env:DB_HOST", max_depth=5)
    assert "env:DB_HOST" in impact
    assert "symbol:main.py#checkout" in impact
    assert "endpoint:POST /checkout" in impact
    assert "external_svc:web" in impact
