"""
indexer/env_reader.py

Parses environment files (.env, .env.example) and docker-compose.yml to extract
services, dependencies, and environment variable contracts into the SystemTopologyGraph.
Enforces zero-trust unconditional value masking to prevent secret leakage.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from indexer.models import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    SystemTopologyGraph,
)


class LineLoader(yaml.SafeLoader):
    """
    A PyYAML SafeLoader that preserves 1-based source line numbers
    for mapping keys under an internal '__lines__' dictionary.
    """
    pass


def _construct_mapping_with_lines(loader: yaml.Loader, node: yaml.Node) -> Dict[str, Any]:
    loader.flatten_mapping(node)
    mapping: Dict[str, Any] = {}
    lines: Dict[str, int] = {}

    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        value = loader.construct_object(value_node)
        mapping[key] = value
        if isinstance(key, str):
            lines[key] = key_node.start_mark.line + 1

    mapping["__lines__"] = lines
    return mapping


LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_with_lines,
)


def extract_env_entry(line: str, line_no: int, file_path: str) -> Optional[Node]:
    """
    Parses a single line from an environment file.
    Unconditionally masks the value to ensure zero-trust security.
    """
    clean_line = line.strip()
    if not clean_line or clean_line.startswith("#"):
        return None

    # Handle 'export KEY=VAL'
    if clean_line.startswith("export "):
        clean_line = clean_line[len("export "):].strip()

    if "=" not in clean_line:
        return None

    key, raw_val = clean_line.split("=", 1)
    key = key.strip()
    if not key:
        return None

    has_value = len(raw_val.strip()) > 0

    return Node(
        id=f"env:{key}",
        name=key,
        node_type=NodeType.ENV_VAR,
        file_path=file_path,
        line_number=line_no,
        metadata={
            "has_default": has_value,
            "value": "[MASKED]",
        },
    )


def parse_env_file(file_path: Path, workspace_root: Path) -> List[Node]:
    """
    Parses an .env or .env.example file line-by-line.
    """
    nodes: List[Node] = []
    rel_path = str(file_path.relative_to(workspace_root))

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, start=1):
                node = extract_env_entry(line, line_no, rel_path)
                if node:
                    nodes.append(node)
    except Exception:
        return []

    return nodes


def parse_docker_compose(file_path: Path, workspace_root: Path) -> Tuple[List[Node], List[Edge]]:
    """
    Parses a docker-compose file to extract:
    - Service nodes
    - Service -> Service dependency edges (depends_on)
    - Service -> Env variable edges (environment)
    """
    rel_path = str(file_path.relative_to(workspace_root))

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.load(f, Loader=LineLoader)
    except Exception:
        return [], []

    if not isinstance(data, dict) or "services" not in data:
        return [], []

    nodes: List[Node] = []
    edges: List[Edge] = []

    services_dict = data.get("services", {})
    services_lines = services_dict.get("__lines__", {}) if isinstance(services_dict, dict) else {}

    for service_name, service_conf in services_dict.items():
        if service_name == "__lines__" or not isinstance(service_conf, dict):
            continue

        line_no = services_lines.get(service_name, 1)
        svc_id = f"external_svc:{service_name}"

        # 1. Register the Service Node
        nodes.append(
            Node(
                id=svc_id,
                name=service_name,
                node_type=NodeType.EXTERNAL_SERVICE,
                file_path=rel_path,
                line_number=line_no,
                metadata={"ports": service_conf.get("ports", [])},
            )
        )

        # 2. Extract dependencies (depends_on)
        deps = service_conf.get("depends_on", [])
        dep_list: List[str] = deps if isinstance(deps, list) else list(deps.keys())
        for dep in dep_list:
            if isinstance(dep, str) and dep != "__lines__":
                edges.append(
                    Edge(
                        source_id=svc_id,
                        target_id=f"external_svc:{dep}",
                        edge_type=EdgeType.DEPENDS_ON,
                        metadata={"file_path": rel_path, "line_number": line_no},
                    )
                )

        # 3. Extract environment variables (list or dictionary format)
        env_conf = service_conf.get("environment", [])
        if isinstance(env_conf, list):
            for item in env_conf:
                item_str = str(item)
                var_name = item_str.split("=", 1)[0].strip() if "=" in item_str else item_str.strip()
                if var_name:
                    env_id = f"env:{var_name}"
                    nodes.append(
                        Node(
                            id=env_id,
                            name=var_name,
                            node_type=NodeType.ENV_VAR,
                            file_path=rel_path,
                            line_number=line_no,
                            metadata={"value": "[MASKED]"},
                        )
                    )
                    edges.append(
                        Edge(
                            source_id=svc_id,
                            target_id=env_id,
                            edge_type=EdgeType.READS_ENV,
                            metadata={"file_path": rel_path, "line_number": line_no},
                        )
                    )
        elif isinstance(env_conf, dict):
            for var_name in env_conf.keys():
                if var_name == "__lines__":
                    continue
                env_id = f"env:{var_name}"
                nodes.append(
                    Node(
                        id=env_id,
                        name=var_name,
                        node_type=NodeType.ENV_VAR,
                        file_path=rel_path,
                        line_number=line_no,
                        metadata={"value": "[MASKED]"},
                    )
                )
                edges.append(
                    Edge(
                        source_id=svc_id,
                        target_id=env_id,
                        edge_type=EdgeType.READS_ENV,
                        metadata={"file_path": rel_path, "line_number": line_no},
                    )
                )

    return nodes, edges


def index_environment(workspace_root: Path, graph: SystemTopologyGraph) -> None:
    """
    Discovers all environment files and compose definitions in the workspace
    and registers their nodes and edges into the graph.
    """
    # 1. Discover .env files (preferring templates / examples first)
    env_patterns = [".env.example", ".env.template", ".env.sample", ".env"]
    for pattern in env_patterns:
        for file_path in workspace_root.rglob(pattern):
            # Skip virtualenvs or git directories
            if any(part.startswith(".") and part not in env_patterns for part in file_path.parts):
                continue
            if "site-packages" in file_path.parts or "node_modules" in file_path.parts:
                continue

            nodes = parse_env_file(file_path, workspace_root)
            for node in nodes:
                graph.add_node(node)

    # 2. Discover docker-compose files
    compose_patterns = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
    for pattern in compose_patterns:
        for file_path in workspace_root.rglob(pattern):
            if "node_modules" in file_path.parts or ".git" in file_path.parts:
                continue

            nodes, edges = parse_docker_compose(file_path, workspace_root)
            for node in nodes:
                graph.add_node(node)
            for edge in edges:
                # Ensure target exists (e.g. if a service depends_on a service defined elsewhere)
                if edge.target_id not in graph.nodes:
                    # Register stub target node
                    target_name = edge.target_id.split(":", 1)[1]
                    graph.add_node(
                        Node(
                            id=edge.target_id,
                            name=target_name,
                            node_type=NodeType.EXTERNAL_SERVICE,
                        )
                    )
                graph.add_edge(edge)
