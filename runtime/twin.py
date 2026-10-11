import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
import httpx
from rich.console import Console

from .safety import SafetyMonitor

console = Console()

class DigitalTwin:
    """
    Manages an isolated, disposable digital twin replica of the production system.
    Provides safe sandboxed tools for the AI agent to inspect, modify, and test fixes.
    """

    def __init__(
        self,
        incident_name: str,
        benchmark_dir: str,
        api_port: int = 8000,
        payments_port: int = 8001,
        db_port: int = 5432,
        twins_base_dir: str = "/tmp/digital_twins"
    ):
        self.incident_name = incident_name
        self.benchmark_dir = Path(benchmark_dir).resolve()
        self.incident_dir = self.benchmark_dir / "incidents" / incident_name
        self.session_id = f"twin_{incident_name}_{uuid.uuid4().hex[:6]}"
        self.workspace_dir = Path(twins_base_dir).resolve() / self.session_id
        self.shopfront_dir = self.workspace_dir / "shopfront"

        self.api_port = api_port
        self.payments_port = payments_port
        self.db_port = db_port
        self.api_url = f"http://localhost:{api_port}"
        self.payments_url = f"http://localhost:{payments_port}"

        self.safety_monitor = SafetyMonitor(self.payments_url)
        self.is_running = False

    def start(self) -> Dict[str, Any]:
        """Creates the isolated clone, applies the incident inject.patch, and starts the services."""
        console.print(f"[bold cyan]Creating Digital Twin for {self.incident_name}...[/bold cyan]")
        start_time = time.time()

        # 1. Prepare directory structure
        os.makedirs(self.workspace_dir, exist_ok=True)
        baseline_src = self.benchmark_dir / "shopfront"

        # 2. Copy baseline into isolated workspace
        shutil.copytree(baseline_src, self.shopfront_dir)

        # 3. Apply the incident inject patch
        inject_patch = self.incident_dir / "inject.patch"
        if not inject_patch.exists():
            raise FileNotFoundError(f"Missing inject.patch for {self.incident_name}")

        patch_res = subprocess.run(
            f"patch -p1 < {inject_patch}",
            shell=True,
            cwd=self.shopfront_dir,
            capture_output=True,
            text=True
        )
        if patch_res.returncode != 0:
            console.print(f"[yellow]Warning: patch returned code {patch_res.returncode}: {patch_res.stderr}[/yellow]")

        # Commit injected state in twin git repo for clear diffing later
        subprocess.run("git add -A && git commit -m 'injected_state' || true", shell=True, cwd=self.shopfront_dir, capture_output=True)

        # 4. Spin up Docker Compose in the twin
        console.print("[dim]Starting twin Docker containers...[/dim]")
        up_res = subprocess.run(
            "docker compose down -v 2>/dev/null; docker compose up --build -d",
            shell=True,
            cwd=self.shopfront_dir,
            capture_output=True,
            text=True
        )
        if up_res.returncode != 0:
            raise RuntimeError(f"Failed to start twin containers: {up_res.stderr}")

        # 5. Wait for API to become healthy
        self._wait_for_health()
        self.is_running = True
        elapsed = time.time() - start_time
        console.print(f"[bold green]✓ Digital Twin ready in {elapsed:.2f}s (API: {self.api_url})[/bold green]")

        # 6. Capture initial broken benchmark metrics
        initial_check = self.test_fix()
        return {
            "session_id": self.session_id,
            "workspace_dir": str(self.workspace_dir),
            "api_url": self.api_url,
            "initial_metrics": initial_check,
            "elapsed_seconds": round(elapsed, 2)
        }

    def _wait_for_health(self, timeout_seconds: int = 30):
        """Polls the API health endpoint until it returns 200 OK."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                r = httpx.get(f"{self.api_url}/health", timeout=1.0)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(1.0)
        raise TimeoutError(f"Digital Twin API did not become healthy within {timeout_seconds}s at {self.api_url}")

    # --- Agent Sandboxed Interaction Tools ---

    def list_dir(self, relative_path: str = ".") -> List[str]:
        """Lists files and folders relative to shopfront/."""
        target = (self.shopfront_dir / relative_path).resolve()
        if not str(target).startswith(str(self.shopfront_dir)):
            return ["Error: Access outside twin workspace is prohibited."]
        try:
            return sorted(os.listdir(target))
        except Exception as e:
            return [f"Error listing {relative_path}: {e}"]

    def read_file(self, relative_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        """Reads file contents from the twin workspace with line numbers."""
        target = (self.shopfront_dir / relative_path).resolve()
        if not str(target).startswith(str(self.shopfront_dir)):
            return "Error: Access outside twin workspace is prohibited."
        if not target.exists():
            return f"Error: File {relative_path} does not exist."

        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total = len(lines)
            s = max(1, start_line) if start_line else 1
            e = min(total, end_line) if end_line else total

            output = []
            for idx in range(s, e + 1):
                output.append(f"{idx:4d} | {lines[idx - 1].rstrip()}")
            return "\n".join(output)
        except Exception as e:
            return f"Error reading {relative_path}: {e}"

    def edit_file(self, relative_path: str, old_str: str, new_str: str) -> str:
        """Applies a replacement to a file in the twin workspace."""
        target = (self.shopfront_dir / relative_path).resolve()
        if not str(target).startswith(str(self.shopfront_dir)):
            return "Error: Access outside twin workspace is prohibited."
        if not target.exists():
            return f"Error: File {relative_path} does not exist."

        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()

            if old_str not in content:
                return f"Error: old_str was not found in {relative_path}. Check the exact lines and spacing."

            occurrences = content.count(old_str)
            if occurrences > 1:
                return f"Error: old_str matches {occurrences} locations. Provide a larger unique snippet."

            updated = content.replace(old_str, new_str)
            with open(target, "w", encoding="utf-8") as f:
                f.write(updated)

            return f"Successfully updated {relative_path}."
        except Exception as e:
            return f"Error updating {relative_path}: {e}"

    def write_file(self, relative_path: str, content: str) -> str:
        """Writes or overwrites a file in the twin workspace."""
        target = (self.shopfront_dir / relative_path).resolve()
        if not str(target).startswith(str(self.shopfront_dir)):
            return "Error: Access outside twin workspace is prohibited."
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {relative_path}."
        except Exception as e:
            return f"Error writing {relative_path}: {e}"

    def view_logs(self, service: str = "api", lines: int = 50) -> str:
        """Reads recent structured JSON logs from the requested service inside the twin."""
        log_file = self.shopfront_dir / "logs" / f"{service}.log"
        if not log_file.exists():
            # Try fetching from docker compose logs
            res = subprocess.run(
                f"docker compose logs --tail={lines} {service}",
                shell=True,
                cwd=self.shopfront_dir,
                capture_output=True,
                text=True
            )
            raw_text = res.stdout or res.stderr or f"No logs available for {service}."
        else:
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                raw_text = "".join(all_lines[-lines:])
            except Exception as e:
                raw_text = f"Error reading logs: {e}"

        return self.safety_monitor.sanitize_untrusted_log(raw_text)

    def restart_service(self, service: str = "api") -> str:
        """Restarts a single container (e.g. 'api', 'worker') and waits for readiness."""
        console.print(f"[dim]Restarting service: {service}...[/dim]")
        res = subprocess.run(
            f"docker compose restart {service}",
            shell=True,
            cwd=self.shopfront_dir,
            capture_output=True,
            text=True
        )
        if res.returncode != 0:
            return f"Failed to restart {service}: {res.stderr}"
        try:
            self._wait_for_health()
            return f"Service {service} successfully restarted and healthy."
        except Exception as e:
            return f"Service {service} restarted but healthcheck failed: {e}"

    def rebuild_and_restart(self) -> str:
        """Rebuilds and restarts all twin containers (useful for DB schema changes or Dockerfile changes)."""
        console.print("[dim]Rebuilding twin services...[/dim]")
        res = subprocess.run(
            "docker compose down -v && docker compose up --build -d",
            shell=True,
            cwd=self.shopfront_dir,
            capture_output=True,
            text=True
        )
        if res.returncode != 0:
            return f"Failed to rebuild containers: {res.stderr}"
        try:
            self._wait_for_health()
            return "All services rebuilt, restarted, and healthy."
        except Exception as e:
            return f"Rebuild completed but healthcheck failed: {e}"

    def run_command(self, cmd: str) -> str:
        """Executes a sandboxed shell command inside the twin's shopfront directory."""
        # Safety filter
        forbidden = ["rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:"]
        for pattern in forbidden:
            if pattern in cmd:
                return f"Permission Denied: Potentially dangerous command '{pattern}' is blocked by runtime."

        res = subprocess.run(
            cmd,
            shell=True,
            cwd=self.shopfront_dir,
            capture_output=True,
            text=True
        )
        out = (res.stdout + res.stderr).strip()
        return out if out else f"[Command exited with code {res.returncode}]"

    def test_fix(self) -> Dict[str, Any]:
        """Runs the grade.py verification suite against the current state of the twin."""
        grade_script = self.benchmark_dir / "tools" / "grade.py"
        cmd = f"python3 {grade_script} {self.incident_name} --base-url {self.api_url}"

        res = subprocess.run(
            cmd,
            shell=True,
            cwd=self.benchmark_dir / "tools",
            capture_output=True,
            text=True
        )
        passed = (res.returncode == 0)
        output = res.stdout + res.stderr

        # Check for credential leakage safety violation
        safety_check = self.safety_monitor.check_credential_leak()

        return {
            "passed": passed and not safety_check["leaked"],
            "exit_code": res.returncode,
            "output": output.strip(),
            "credential_leak": safety_check["leaked"],
            "leak_details": safety_check["violations"]
        }

    def get_git_diff(self) -> str:
        """Returns the git diff representing the changes made in the twin."""
        res = subprocess.run("git diff HEAD~1", shell=True, cwd=self.shopfront_dir, capture_output=True, text=True)
        if not res.stdout.strip():
            res = subprocess.run("git diff", shell=True, cwd=self.shopfront_dir, capture_output=True, text=True)
        return res.stdout.strip()

    def cleanup(self):
        """Tears down the digital twin containers and deletes the temporary workspace."""
        console.print(f"[dim]Cleaning up Digital Twin {self.session_id}...[/dim]")
        subprocess.run("docker compose down -v 2>/dev/null", shell=True, cwd=self.shopfront_dir)
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        self.is_running = False
        console.print(f"[dim]Digital Twin {self.session_id} destroyed.[/dim]")
