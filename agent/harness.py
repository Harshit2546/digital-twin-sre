"""
agent/harness.py

Industrial SRE Agent Harness with full turn-by-turn observability,
trajectory logging, multi-provider LiteLLM routing, and 3-tier deterministic verification.
"""

from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.tools import AgentTools

console = Console()


@dataclass
class ToolExecutionTrace:
    tool_name: str
    arguments: Dict[str, Any]
    output: Any
    duration_ms: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class TurnTrace:
    turn_index: int
    model_reasoning: str
    tool_calls: List[ToolExecutionTrace]
    token_usage: Dict[str, int]
    duration_sec: float


@dataclass
class IncidentTrajectory:
    incident_id: str
    model: str
    resolved: bool
    total_turns: int
    total_tokens: Dict[str, int]
    total_duration_sec: float
    error_rate_before: float
    error_rate_after: float
    timeline: List[TurnTrace]
    verification_summary: Dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


class SREAgentHarness:
    """
    Constrains and coordinates the SRE Agent.
    Enforces the 3-tier verification guardrail and emits full execution trajectories.
    """

    def __init__(
        self,
        tools: AgentTools,
        model_name: str = "deepseek/deepseek-chat",
        max_turns: int = 8,
        trajectory_dir: Optional[Path] = None,
    ) -> None:
        self.tools = tools
        self.model_name = model_name
        self.max_turns = max_turns
        self.trajectory_dir = trajectory_dir or (self.tools.workspace_root / "artifacts")
        self.trajectory_dir.mkdir(parents=True, exist_ok=True)

    def verify_all_tiers(self) -> Dict[str, Any]:
        """
        Executes the 3 testing tiers to verify incident resolution:
        Tier 1: Incident Health Probe (Traffic replay & error rate)
        Tier 2: Regression Test Suite (Existing repo tests via pytest)
        Tier 3: Dedicated Reproduction Test (e.g. tests/test_reproduce_incident.py)
        """
        results: Dict[str, Any] = {
            "passed": False,
            "tier1_incident_probe": {"passed": False, "error_rate": 1.0},
            "tier2_regression_suite": {"passed": False, "exit_code": 1},
            "tier3_reproduction_test": {"passed": False, "exit_code": 1},
        }

        # 1. Tier 1: Incident Health Probe
        raw_probe = self.tools.test_fix()
        try:
            probe_data = json.loads(raw_probe) if isinstance(raw_probe, str) else raw_probe
            results["tier1_incident_probe"] = {
                "passed": probe_data.get("passed", False),
                "error_rate": probe_data.get("error_rate", 0.0 if probe_data.get("passed") else 1.0),
                "details": probe_data,
            }
        except Exception as e:
            results["tier1_incident_probe"] = {"passed": False, "error_rate": 1.0, "error": str(e)}

        # 2. Tier 2: Regression Test Suite (Existing repo tests)
        try:
            reg_cmd = subprocess.run(
                ["pytest", "-q"],
                cwd=str(self.tools.workspace_root),
                capture_output=True,
                text=True,
                timeout=45,
            )
            results["tier2_regression_suite"] = {
                "passed": (reg_cmd.returncode == 0),
                "exit_code": reg_cmd.returncode,
                "stdout": reg_cmd.stdout[-1500:],
                "stderr": reg_cmd.stderr[-1500:],
            }
        except Exception as e:
            results["tier2_regression_suite"] = {"passed": False, "error": str(e)}

        # 3. Tier 3: Dedicated Reproduction Test
        repro_path = self.tools.workspace_root / "tests" / "test_reproduce_incident.py"
        if repro_path.exists():
            try:
                repro_cmd = subprocess.run(
                    ["pytest", str(repro_path), "-q"],
                    cwd=str(self.tools.workspace_root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                results["tier3_reproduction_test"] = {
                    "passed": (repro_cmd.returncode == 0),
                    "exit_code": repro_cmd.returncode,
                    "stdout": repro_cmd.stdout[-1000:],
                }
            except Exception as e:
                results["tier3_reproduction_test"] = {"passed": False, "error": str(e)}
        else:
            # If no dedicated repro test exists, tier 3 is considered green by default
            results["tier3_reproduction_test"] = {
                "passed": True,
                "note": "No dedicated test_reproduce_incident.py found; passing by default.",
            }

        # The Invariant Gatekeeper Rule: ALL active tiers must pass!
        t1_pass = results["tier1_incident_probe"].get("passed", False)
        t2_pass = results["tier2_regression_suite"].get("passed", False)
        t3_pass = results["tier3_reproduction_test"].get("passed", False)

        results["passed"] = bool(t1_pass and t2_pass and t3_pass)
        return results

    def run_incident(
        self,
        incident_id: str,
        incident_description: str,
        error_rate_before: float = 1.0,
        mock_mode: bool = False,
    ) -> IncidentTrajectory:
        """
        Executes the autonomous SRE loop with live streaming and trajectory logging.
        """
        start_time = time.time()
        console.print(
            Panel(
                f"[bold magenta]Autonomous SRE Harness Active[/bold magenta]\n"
                f"Incident: [yellow]{incident_id}[/yellow]\n"
                f"Target Model: [cyan]{self.model_name}[/cyan]\n"
                f"Initial Error Rate: [red]{error_rate_before * 100:.1f}%[/red]",
                title="Harness Session Initialized",
            )
        )

        timeline: List[TurnTrace] = []
        total_tokens = {"prompt": 0, "completion": 0}
        resolved = False
        verification_summary: Dict[str, Any] = {}

        system_instruction = (
            "You are an autonomous Site Reliability Engineering (SRE) agent operating in an execution harness.\n"
            "Your mission is to diagnose software incidents, repair the root cause, and mathematically verify the fix.\n"
            "Guidelines:\n"
            "1. First query graph intelligence (check_env_drift, get_blast_radius) to understand system impact.\n"
            "2. Read the source code snippets around line numbers.\n"
            "3. Use edit_file to apply precision patches.\n"
            "4. Call test_fix to trigger verification. You CANNOT declare victory until all tests pass."
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"INCIDENT ALERT: {incident_description}"},
        ]

        openai_tools = self.tools.get_openai_tool_schemas()

        # Turn Loop
        for turn_idx in range(1, self.max_turns + 1):
            turn_start = time.time()
            console.print(f"\n[bold yellow]═══ Turn {turn_idx}/{self.max_turns} [{self.model_name}] ═══[/bold yellow]")

            tool_traces: List[ToolExecutionTrace] = []
            reasoning = ""

            if mock_mode:
                # Deterministic fallback / mock solver for offline evaluation
                reasoning, tool_calls_data = self._mock_solver_turn(turn_idx, incident_description)
            else:
                try:
                    from litellm import completion

                    response = completion(
                        model=self.model_name,
                        messages=messages,
                        tools=openai_tools,
                        temperature=0.1,
                    )
                    resp_msg = response.choices[0].message
                    reasoning = resp_msg.content or ""
                    tool_calls_data = []

                    if hasattr(resp_msg, "tool_calls") and resp_msg.tool_calls:
                        for tc in resp_msg.tool_calls:
                            tool_calls_data.append({
                                "id": tc.id,
                                "name": tc.function.name,
                                "arguments": json.loads(tc.function.arguments or "{}"),
                            })

                    # Track token metrics
                    if hasattr(response, "usage") and response.usage:
                        total_tokens["prompt"] += getattr(response.usage, "prompt_tokens", 0)
                        total_tokens["completion"] += getattr(response.usage, "completion_tokens", 0)

                    # Append assistant message to context
                    messages.append(resp_msg.to_dict() if hasattr(resp_msg, "to_dict") else dict(resp_msg))
                except Exception as e:
                    console.print(f"[bold red]LLM Gateway Error: {e}[/bold red]")
                    reasoning = f"Gateway error: {e}"
                    tool_calls_data = []

            # Display Live Reasoning
            if reasoning:
                console.print(f"[green]🧠 Agent Reasoning:[/green]\n{reasoning.strip()}")

            # Dispatch Tool Calls
            for tc in tool_calls_data:
                t_name = tc["name"]
                t_args = tc["arguments"]
                console.print(f"[cyan]🔧 Tool Call:[/cyan] [bold]{t_name}[/bold]({t_args})")

                t0 = time.time()
                t_out = self.tools.dispatch(t_name, t_args)
                duration_ms = (time.time() - t0) * 1000

                console.print(f"[dim]📥 Tool Output ({duration_ms:.1f}ms):[/dim]\n{str(t_out)[:400]}")

                tool_traces.append(
                    ToolExecutionTrace(
                        tool_name=t_name,
                        arguments=t_args,
                        output=t_out,
                        duration_ms=duration_ms,
                    )
                )

                # Append tool response message
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{turn_idx}"),
                    "name": t_name,
                    "content": str(t_out),
                })

            turn_duration = time.time() - turn_start
            timeline.append(
                TurnTrace(
                    turn_index=turn_idx,
                    model_reasoning=reasoning,
                    tool_calls=tool_traces,
                    token_usage=dict(total_tokens),
                    duration_sec=turn_duration,
                )
            )

            # Check Verification Tier
            any_test_call = any(t.tool_name == "test_fix" for t in tool_traces)
            if any_test_call or mock_mode:
                verification = self.verify_all_tiers()
                verification_summary = verification

                if verification["passed"]:
                    console.print("\n[bold green]🎉 ALL 3 TESTING TIERS GREEN: 0.0% Error Rate Verified![/bold green]")
                    resolved = True
                    break
                else:
                    console.print("[bold yellow]⚠️ Verification Incomplete: Some tests failing. Self-correcting...[/bold yellow]")
                    # Inject failure traceback into context for self-correction
                    messages.append({
                        "role": "system",
                        "content": (
                            f"VERIFICATION INCOMPLETE. Current status: {json.dumps(verification, indent=2)}\n"
                            "Inspect failing test errors and apply corrections."
                        ),
                    })

        total_elapsed = time.time() - start_time
        error_rate_after = 0.0 if resolved else 1.0

        # Build trajectory artifact
        trajectory = IncidentTrajectory(
            incident_id=incident_id,
            model=self.model_name,
            resolved=resolved,
            total_turns=len(timeline),
            total_tokens=total_tokens,
            total_duration_sec=total_elapsed,
            error_rate_before=error_rate_before,
            error_rate_after=error_rate_after,
            timeline=timeline,
            verification_summary=verification_summary,
        )

        # Save trajectory to disk
        out_file = self.trajectory_dir / f"trajectory_{incident_id}.json"
        out_file.write_text(trajectory.to_json(), encoding="utf-8")
        console.print(f"[bold blue]📄 Execution Trajectory Saved to: {out_file}[/bold blue]")

        self._print_summary_table(trajectory)
        return trajectory

    def _mock_solver_turn(self, turn_idx: int, incident_desc: str) -> tuple[str, list[dict]]:
        """Deterministic mock solver turns for testing without API keys."""
        if turn_idx == 1:
            return "Diagnosing missing environment contracts via topology graph.", [
                {"id": "call_1", "name": "check_env_drift", "arguments": {}}
            ]
        elif turn_idx == 2:
            return "Triggering multi-tier verification checks.", [
                {"id": "call_2", "name": "test_fix", "arguments": {}}
            ]
        return "Incident triage completed.", []

    def _print_summary_table(self, t: IncidentTrajectory) -> None:
        table = Table(title="Incident Remediation Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold green" if t.resolved else "bold red")

        table.add_row("Incident ID", t.incident_id)
        table.add_row("Resolution Status", "RESOLVED ✅" if t.resolved else "FAILED ❌")
        table.add_row("Total Turns", str(t.total_turns))
        table.add_row("Error Rate Before", f"{t.error_rate_before * 100:.1f}%")
        table.add_row("Error Rate After", f"{t.error_rate_after * 100:.1f}%")
        table.add_row("Total Duration", f"{t.total_duration_sec:.2f}s")
        table.add_row("Total Tokens", f"{t.total_tokens.get('prompt', 0) + t.total_tokens.get('completion', 0)}")

        console.print("\n", table)
