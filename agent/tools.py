import json
from typing import Dict, Any, Callable, List
from runtime.twin import DigitalTwin

class AgentTools:
    """Binds DigitalTwin runtime capabilities to callable LLM tool functions."""

    def __init__(self, twin: DigitalTwin):
        self.twin = twin

    def list_files(self, directory: str = ".") -> str:
        """
        List files and folders in the repository relative to shopfront/.
        
        Args:
            directory: Directory to list, default '.' is root of shopfront.
        """
        items = self.twin.list_dir(directory)
        return json.dumps(items)

    def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        """
        Read line-numbered contents of a file in the twin codebase.
        
        Args:
            path: Relative path to file (e.g. 'api/main.py', 'config/app.yaml', 'db/1-init.sql').
            start_line: 1-indexed starting line number.
            end_line: 1-indexed ending line number.
        """
        return self.twin.read_file(path, start_line, end_line)

    def edit_file(self, path: str, old_str: str, new_str: str) -> str:
        """
        Replace an exact unique code snippet in a file with new code.
        
        Args:
            path: Relative path to file (e.g. 'api/main.py', 'config/app.yaml').
            old_str: Exact string to replace (must match uniquely in the file).
            new_str: New replacement string.
        """
        return self.twin.edit_file(path, old_str, new_str)

    def write_file(self, path: str, content: str) -> str:
        """
        Create or completely overwrite a file in the twin codebase.
        
        Args:
            path: Relative path to file.
            content: Complete new text content.
        """
        return self.twin.write_file(path, content)

    def view_logs(self, service: str = "api", lines: int = 50) -> str:
        """
        Retrieve recent structured JSON log entries for a service.
        
        Args:
            service: Service name ('api' or 'worker').
            lines: Number of recent log lines to retrieve (default 50).
        """
        return self.twin.view_logs(service, lines)

    def restart_service(self, service: str = "api") -> str:
        """
        Restart a single service container after code or configuration edits.
        
        Args:
            service: Container name to restart ('api', 'worker', or 'payments-stub').
        """
        return self.twin.restart_service(service)

    def rebuild_and_restart(self) -> str:
        """
        Rebuild and restart all containers. Use when modifying database schemas (db/*.sql) or Dockerfiles.
        """
        return self.twin.rebuild_and_restart()

    def run_command(self, command: str) -> str:
        """
        Run a sandboxed shell command in the twin workspace (e.g., 'git diff', 'psql').
        
        Args:
            command: Shell command string to execute.
        """
        return self.twin.run_command(command)

    def test_fix(self) -> str:
        """
        Replay production traffic and verify fix against error rates, p95 latencies, and golden checks.
        Returns JSON string with test outcome.
        """
        res = self.twin.test_fix()
        return json.dumps(res, indent=2)

    def get_tool_functions(self) -> List[Callable]:
        """Returns the list of callables for google-genai function calling."""
        return [
            self.list_files,
            self.read_file,
            self.edit_file,
            self.write_file,
            self.view_logs,
            self.restart_service,
            self.rebuild_and_restart,
            self.run_command,
            self.test_fix
        ]

    def dispatch(self, name: str, args: Dict[str, Any]) -> Any:
        """Dispatches an incoming function call by name."""
        mapping = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "edit_file": self.edit_file,
            "write_file": self.write_file,
            "view_logs": self.view_logs,
            "restart_service": self.restart_service,
            "rebuild_and_restart": self.rebuild_and_restart,
            "run_command": self.run_command,
            "test_fix": self.test_fix
        }
        fn = mapping.get(name)
        if not fn:
            return f"Error: Tool '{name}' not found."
        try:
            return fn(**args)
        except Exception as e:
            return f"Error executing tool '{name}': {e}"
