"""
agent/tools.py

Unified, provider-agnostic toolset for the Autonomous SRE Agent.
Combines pre-indexed System Topology Graph intelligence with workspace file surgery,
command execution, and verification testing.
Exposes standard OpenAI-compatible tool schemas for use with any LLM provider
(Claude, DeepSeek, GPT-4o, Gemini, Ollama).
"""

from __future__ import annotations
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

from indexer.models import EdgeType, NodeType, SystemTopologyGraph


class AgentTools:
    """
    Binds System Topology Graph intelligence and workspace execution
    to callable LLM tool functions.
    """

    def __init__(
        self,
        twin: Optional[Any] = None,
        workspace_root: Optional[Path] = None,
        graph: Optional[SystemTopologyGraph] = None,
    ) -> None:
        self.twin = twin
        self.workspace_root = (
            Path(workspace_root)
            if workspace_root
            else (twin.workspace_dir if twin else Path("."))
        ).resolve()
        self.graph = graph or SystemTopologyGraph()
        self.touched_files: set[str] = set()

    # =========================================================================
    # 1. Graph Intelligence Tools (The "Brain")
    # =========================================================================

    def check_env_drift(self) -> str:
        """
        Scans the pre-indexed graph for environment variables that are read
        by source code, but are not provided in any .env template or docker-compose file.
        """
        if not self.graph.nodes:
            return json.dumps({"error": "Topology graph is empty. Please index workspace first."})

        missing_vars: List[Dict[str, Any]] = []

        for node_id, node in self.graph.nodes.items():
            if node.node_type == NodeType.ENV_VAR:
                # Inward edges with READS_ENV tell us who consumes this variable
                readers = self.graph.get_inward(node_id, EdgeType.READS_ENV)
                has_default = node.metadata.get("has_default", False)

                # Check if defined by a docker compose service
                defined_in_compose = any(
                    self.graph.nodes[e.source_id].node_type == NodeType.EXTERNAL_SERVICE
                    for e in readers
                    if e.source_id in self.graph.nodes
                )

                # Find source code symbols reading this variable
                code_readers = [
                    e.source_id
                    for e in readers
                    if e.source_id in self.graph.nodes
                    and self.graph.nodes[e.source_id].node_type == NodeType.SYMBOL
                ]

                # If code reads it, but neither .env template nor compose provides it:
                if code_readers and not has_default and not defined_in_compose:
                    missing_vars.append({
                        "variable": node.name,
                        "used_by_symbols": code_readers,
                        "file_path": node.file_path,
                        "line_number": node.line_number,
                    })

        return json.dumps({
            "status": "drift_detected" if missing_vars else "clean",
            "missing_count": len(missing_vars),
            "missing_variables": missing_vars,
        }, indent=2)

    def get_blast_radius(self, node_id: str, max_depth: int = 4) -> str:
        """
        Calculates all endpoints, services, and functions affected if a given node
        breaks or changes, using backward traversal over reverse-adjacency edges.
        """
        if node_id not in self.graph.nodes:
            return json.dumps({"error": f"Node '{node_id}' not found in topology graph."})

        impacted_ids = self.graph.blast_radius(node_id, max_depth=max_depth)
        impacted_nodes = []

        for nid in impacted_ids:
            if nid in self.graph.nodes:
                n = self.graph.nodes[nid]
                impacted_nodes.append({
                    "id": n.id,
                    "name": n.name,
                    "node_type": n.node_type.value,
                    "file_path": n.file_path,
                    "line_number": n.line_number,
                })

        return json.dumps({
            "target_node": node_id,
            "impact_count": len(impacted_nodes),
            "impacted_entities": impacted_nodes,
        }, indent=2)

    def query_graph(self, node_type: str = "", name: str = "") -> str:
        """
        Searches the graph for nodes matching an optional node_type
        (e.g. 'endpoint', 'symbol', 'env_var', 'database_table') or name substring.
        """
        matches = []
        for n in self.graph.nodes.values():
            if node_type and n.node_type.value != node_type.lower():
                continue
            if name and name.lower() not in n.name.lower():
                continue
            matches.append({
                "id": n.id,
                "name": n.name,
                "node_type": n.node_type.value,
                "file_path": n.file_path,
                "line_number": n.line_number,
            })

        return json.dumps({"match_count": len(matches), "matches": matches[:50]}, indent=2)

    # =========================================================================
    # 2. Workspace File Surgery Tools (The "Hands")
    # =========================================================================

    def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        """
        Reads line-numbered contents of a file in the workspace safely.
        """
        if self.twin and hasattr(self.twin, "read_file"):
            return self.twin.read_file(path, start_line, end_line)

        target = (self.workspace_root / path).resolve()
        if not target.is_relative_to(self.workspace_root):
            return f"Error: Path '{path}' is outside workspace."
        if not target.exists():
            return f"Error: File '{path}' not found."

        try:
            lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            numbered = [f"{i+1:4d} | {lines[i]}" for i in range(start_idx, end_idx)]
            return "\n".join(numbered)
        except Exception as e:
            return f"Error reading file '{path}': {e}"

    def edit_file(self, path: str, old_str: str, new_str: str) -> str:
        """
        Replaces an exact unique snippet in a file with new code.
        Fails safely if old_str appears 0 times or more than once.
        """
        if self.twin and hasattr(self.twin, "edit_file"):
            return self.twin.edit_file(path, old_str, new_str)

        target = (self.workspace_root / path).resolve()
        if not target.is_relative_to(self.workspace_root):
            return f"Error: Path '{path}' is outside workspace."
        if not target.exists():
            return f"Error: File '{path}' not found."

        try:
            content = target.read_text(encoding="utf-8")
            count = content.count(old_str)
            if count == 0:
                return f"Error: old_str not found in '{path}'. Make sure whitespace and formatting match exactly."
            if count > 1:
                return f"Error: old_str matches {count} times in '{path}'. Provide more surrounding context lines."

            updated = content.replace(old_str, new_str, 1)
            target.write_text(updated, encoding="utf-8")
            self.touched_files.add(str(path))
            return f"Success: Successfully patched '{path}'."
        except Exception as e:
            return f"Error editing file '{path}': {e}"

    def write_file(self, path: str, content: str) -> str:
        """
        Creates or overwrites a file in the workspace.
        """
        if self.twin and hasattr(self.twin, "write_file"):
            return self.twin.write_file(path, content)

        target = (self.workspace_root / path).resolve()
        if not target.is_relative_to(self.workspace_root):
            return f"Error: Path '{path}' is outside workspace."

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.touched_files.add(str(path))
            return f"Success: File '{path}' written successfully."
        except Exception as e:
            return f"Error writing file '{path}': {e}"

    # =========================================================================
    # 3. Execution & Verification Tools (The "Eyes")
    # =========================================================================

    def test_fix(self) -> str:
        """
        Runs the test suite or replays synthetic traffic to verify resolution.
        Returns a structured JSON result with error rate and status.
        """
        if self.twin and hasattr(self.twin, "test_fix"):
            res = self.twin.test_fix()
            return json.dumps(res, indent=2)

        # Fallback: run local pytest in workspace
        try:
            cmd = ["pytest", "-q"]
            res = subprocess.run(
                cmd,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            passed = res.returncode == 0
            return json.dumps({
                "passed": passed,
                "exit_code": res.returncode,
                "stdout": res.stdout[-2000:],
                "stderr": res.stderr[-2000:],
            }, indent=2)
        except Exception as e:
            return json.dumps({"passed": False, "error": str(e)})

    def run_command(self, command: str) -> str:
        """
        Runs a sandboxed terminal command in the workspace.
        """
        if self.twin and hasattr(self.twin, "run_command"):
            return self.twin.run_command(command)

        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=45,
            )
            output = res.stdout if res.stdout else res.stderr
            return output[-3000:] if output else "(No output)"
        except Exception as e:
            return f"Error executing command: {e}"

    # =========================================================================
    # 4. Service Lifecycle (Twin Specific)
    # =========================================================================

    def view_logs(self, service: str = "api", lines: int = 50) -> str:
        if self.twin and hasattr(self.twin, "view_logs"):
            return self.twin.view_logs(service, lines)
        return "Logs unavailable outside active Docker twin."

    def restart_service(self, service: str = "api") -> str:
        if self.twin and hasattr(self.twin, "restart_service"):
            return self.twin.restart_service(service)
        return "Service restart unavailable outside active Docker twin."

    def rebuild_and_restart(self) -> str:
        if self.twin and hasattr(self.twin, "rebuild_and_restart"):
            return self.twin.rebuild_and_restart()
        return "Rebuild unavailable outside active Docker twin."

    # =========================================================================
    # 5. Universal OpenAI-Compatible Tool Schemas
    # =========================================================================

    def get_openai_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Returns standard OpenAI-compatible tool specifications.
        Supported natively by Claude, DeepSeek, GPT-4o, Gemini, and Ollama.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "check_env_drift",
                    "description": "Scans the pre-indexed graph for environment variables read in code but missing from configs or .env.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_blast_radius",
                    "description": "Calculates all endpoints, services, and symbols affected if a given node breaks or changes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "Canonical node ID, e.g. 'env:DB_PORT' or 'symbol:app.py#checkout'",
                            },
                            "max_depth": {
                                "type": "integer",
                                "description": "Maximum graph traversal depth (default 4).",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_graph",
                    "description": "Finds nodes in the system graph matching node_type ('endpoint', 'symbol', 'env_var', 'database_table') or name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_type": {"type": "string", "description": "Optional node type filter."},
                            "name": {"type": "string", "description": "Optional name substring to search."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Reads line-numbered contents of a file in the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path."},
                            "start_line": {"type": "integer", "description": "1-indexed start line."},
                            "end_line": {"type": "integer", "description": "1-indexed end line."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Replaces an exact unique snippet in a file with new code.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path."},
                            "old_str": {"type": "string", "description": "Exact text to replace."},
                            "new_str": {"type": "string", "description": "New replacement text."},
                        },
                        "required": ["path", "old_str", "new_str"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Creates or completely overwrites a file with content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path."},
                            "content": {"type": "string", "description": "New text content."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "test_fix",
                    "description": "Runs the verification test suite to check whether the outage or bug is resolved.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Executes a sandboxed terminal command in the workspace (e.g. 'git status').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Shell command to run."},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "view_logs",
                    "description": "Reads recent structured JSON logs from the requested service inside the twin (e.g. 'api', 'worker').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {"type": "string", "description": "Service name ('api' or 'worker'). Default is 'api'."},
                            "lines": {"type": "integer", "description": "Number of log lines to retrieve (default 50)."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "restart_service",
                    "description": "Restarts a single service container (e.g. 'api', 'worker') to reload updated code or config.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {"type": "string", "description": "Service name to restart (default 'api')."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rebuild_and_restart",
                    "description": "Rebuilds and restarts all twin containers (necessary when changing database schemas in db/ or Dockerfiles).",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    # =========================================================================
    # 6. Dispatcher
    # =========================================================================

    def dispatch(self, name: str, args: Dict[str, Any]) -> str:
        """
        Dispatches incoming tool call by name to the corresponding method.
        """
        mapping = {
            "check_env_drift": self.check_env_drift,
            "get_blast_radius": self.get_blast_radius,
            "query_graph": self.query_graph,
            "read_file": self.read_file,
            "edit_file": self.edit_file,
            "write_file": self.write_file,
            "test_fix": self.test_fix,
            "run_command": self.run_command,
            "view_logs": self.view_logs,
            "restart_service": self.restart_service,
            "rebuild_and_restart": self.rebuild_and_restart,
        }
        fn = mapping.get(name)
        if not fn:
            return json.dumps({"error": f"Tool '{name}' not found."})

        try:
            return str(fn(**args))
        except Exception as e:
            return json.dumps({"error": f"Error executing tool '{name}': {e}"})
