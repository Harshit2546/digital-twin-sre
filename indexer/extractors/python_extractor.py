"""
indexer/extractors/python_extractor.py

Extracts Python AST symbols, routes, calls, environment reads, and ORM entities
using Tree-sitter.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Set
import tree_sitter
import tree_sitter_python

from indexer.extractors.base import BaseLanguageExtractor
from indexer.models import (
    Edge,
    EdgeType,
    Node,
    NodeType,
    SystemTopologyGraph,
)


class PythonExtractor(BaseLanguageExtractor):
    """
    Tree-sitter based extractor for Python source files.
    """

    def __init__(self) -> None:
        self.language = tree_sitter.Language(tree_sitter_python.language())
        self.parser = tree_sitter.Parser(self.language)

        # Pre-compile Tree-sitter queries for performance
        self._func_query = tree_sitter.Query(
            self.language,
            "(function_definition name: (identifier) @func_name)",
        )

        self._route_query = tree_sitter.Query(
            self.language,
            """
            (decorated_definition
              (decorator
                (call
                  function: (attribute attribute: (identifier) @http_method)
                  arguments: (argument_list (string) @route_path)))
              definition: (function_definition
                name: (identifier) @func_name))
            """,
        )

        self._env_query = tree_sitter.Query(
            self.language,
            """
            (call
              function: (attribute attribute: (identifier) @attr)
              arguments: (argument_list (string) @var_name))
            (subscript
              value: (attribute attribute: (identifier) @attr)
              subscript: (string) @var_name)
            """,
        )

        self._orm_table_query = tree_sitter.Query(
            self.language,
            """
            (class_definition
              name: (identifier) @class_name
              body: (block
                (expression_statement
                  (assignment
                    left: (identifier) @attr_name
                    right: (string) @table_name))))
            """,
        )

        self._call_query = tree_sitter.Query(
            self.language,
            "(call function: (identifier) @called_func)",
        )

    def _find_enclosing_function(self, node: tree_sitter.Node) -> Optional[str]:
        """Walks up the AST to find the nearest enclosing function name."""
        curr = node.parent
        while curr:
            if curr.type == "function_definition":
                name_child = curr.child_by_field_name("name")
                if name_child and name_child.text:
                    return name_child.text.decode("utf-8")
            curr = curr.parent
        return None

    def extract(
        self,
        file_path: Path,
        code_bytes: bytes,
        workspace_root: Path,
        graph: SystemTopologyGraph,
    ) -> None:
        rel_path = str(file_path.relative_to(workspace_root))
        tree = self.parser.parse(code_bytes)
        root = tree.root_node

        # Set of discovered functions in this file for symbol resolution
        defined_functions: Set[str] = set()

        # 1. Extract Functions
        cursor = tree_sitter.QueryCursor(self._func_query)
        for _, captures in cursor.matches(root):
            for node in captures.get("func_name", []):
                func_name = node.text.decode("utf-8")
                defined_functions.add(func_name)
                func_id = f"symbol:{rel_path}#{func_name}"
                line_no = node.start_point[0] + 1

                graph.add_node(
                    Node(
                        id=func_id,
                        name=func_name,
                        node_type=NodeType.SYMBOL,
                        file_path=rel_path,
                        line_number=line_no,
                    )
                )

        # 2. Extract Decorated Routes (FastAPI, Flask, Starlette)
        cursor = tree_sitter.QueryCursor(self._route_query)
        for _, captures in cursor.matches(root):
            method_nodes = captures.get("http_method", [])
            route_nodes = captures.get("route_path", [])
            func_nodes = captures.get("func_name", [])

            if method_nodes and route_nodes and func_nodes:
                method = method_nodes[0].text.decode("utf-8").upper()
                route = route_nodes[0].text.decode("utf-8").strip("'\"")
                func_name = func_nodes[0].text.decode("utf-8")
                line_no = method_nodes[0].start_point[0] + 1

                endpoint_id = f"endpoint:{method} {route}"
                endpoint_node = Node(
                    id=endpoint_id,
                    name=f"{method} {route}",
                    node_type=NodeType.ENDPOINT,
                    file_path=rel_path,
                    line_number=line_no,
                )
                graph.add_node(endpoint_node)

                func_id = f"symbol:{rel_path}#{func_name}"
                if func_id in graph.nodes:
                    graph.add_edge(
                        Edge(
                            source_id=endpoint_id,
                            target_id=func_id,
                            edge_type=EdgeType.HANDLES_ROUTE,
                            confidence=1.0,
                            metadata={"file_path": rel_path, "line_number": line_no},
                        )
                    )

        # 3. Extract Environment Variable Reads (os.getenv, os.environ)
        cursor = tree_sitter.QueryCursor(self._env_query)
        for _, captures in cursor.matches(root):
            attr_nodes = captures.get("attr", [])
            var_nodes = captures.get("var_name", [])

            if attr_nodes and var_nodes:
                attr_name = attr_nodes[0].text.decode("utf-8")
                # Check if it's getenv or environ
                if attr_name in ("getenv", "environ", "get"):
                    raw_var = var_nodes[0].text.decode("utf-8").strip("'\"")
                    if raw_var:
                        env_id = f"env:{raw_var}"
                        # Ensure env node exists
                        if env_id not in graph.nodes:
                            graph.add_node(
                                Node(
                                    id=env_id,
                                    name=raw_var,
                                    node_type=NodeType.ENV_VAR,
                                    metadata={"value": "[MASKED]"},
                                )
                            )

                        # Find enclosing function
                        enclosing_func = self._find_enclosing_function(var_nodes[0])
                        line_no = var_nodes[0].start_point[0] + 1

                        source_id = (
                            f"symbol:{rel_path}#{enclosing_func}"
                            if enclosing_func
                            else f"symbol:{rel_path}#module"
                        )
                        if source_id not in graph.nodes:
                            graph.add_node(
                                Node(
                                    id=source_id,
                                    name=enclosing_func or "module",
                                    node_type=NodeType.SYMBOL,
                                    file_path=rel_path,
                                    line_number=line_no,
                                )
                            )

                        graph.add_edge(
                            Edge(
                                source_id=source_id,
                                target_id=env_id,
                                edge_type=EdgeType.READS_ENV,
                                confidence=1.0,
                                metadata={"file_path": rel_path, "line_number": line_no},
                            )
                        )

        # 4. Extract ORM Table Mappings (SQLAlchemy __tablename__)
        cursor = tree_sitter.QueryCursor(self._orm_table_query)
        for _, captures in cursor.matches(root):
            cls_nodes = captures.get("class_name", [])
            attr_nodes = captures.get("attr_name", [])
            tbl_nodes = captures.get("table_name", [])

            if cls_nodes and attr_nodes and tbl_nodes:
                attr_name = attr_nodes[0].text.decode("utf-8")
                if attr_name == "__tablename__":
                    class_name = cls_nodes[0].text.decode("utf-8")
                    table_name = tbl_nodes[0].text.decode("utf-8").strip("'\"")
                    line_no = cls_nodes[0].start_point[0] + 1

                    entity_id = f"entity:{rel_path}#{class_name}"
                    table_id = f"database_table:{table_name}"

                    graph.add_node(
                        Node(
                            id=entity_id,
                            name=class_name,
                            node_type=NodeType.ENTITY,
                            file_path=rel_path,
                            line_number=line_no,
                        )
                    )
                    graph.add_node(
                        Node(
                            id=table_id,
                            name=table_name,
                            node_type=NodeType.DATABASE_TABLE,
                        )
                    )
                    graph.add_edge(
                        Edge(
                            source_id=entity_id,
                            target_id=table_id,
                            edge_type=EdgeType.MAPS_TO_TABLE,
                            confidence=1.0,
                            metadata={"file_path": rel_path, "line_number": line_no},
                        )
                    )

        # 5. Extract Intra-file Function Calls
        cursor = tree_sitter.QueryCursor(self._call_query)
        for _, captures in cursor.matches(root):
            for call_node in captures.get("called_func", []):
                called_name = call_node.text.decode("utf-8")
                if called_name in defined_functions:
                    enclosing_func = self._find_enclosing_function(call_node)
                    if enclosing_func and enclosing_func != called_name:
                        caller_id = f"symbol:{rel_path}#{enclosing_func}"
                        callee_id = f"symbol:{rel_path}#{called_name}"
                        line_no = call_node.start_point[0] + 1

                        if caller_id in graph.nodes and callee_id in graph.nodes:
                            graph.add_edge(
                                Edge(
                                    source_id=caller_id,
                                    target_id=callee_id,
                                    edge_type=EdgeType.CALLS,
                                    confidence=1.0,
                                    metadata={"file_path": rel_path, "line_number": line_no},
                                )
                            )
