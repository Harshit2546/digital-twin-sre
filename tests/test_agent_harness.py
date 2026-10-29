"""
Tests for SREAgentHarness observability, trajectory logging, and 3-tier testing.
"""

import json
from pathlib import Path
import pytest
from agent.harness import IncidentTrajectory, SREAgentHarness
from agent.tools import AgentTools
from indexer.models import SystemTopologyGraph


def test_trajectory_serialization():
    trajectory = IncidentTrajectory(
        incident_id="test-001",
        model="deepseek/deepseek-chat",
        resolved=True,
        total_turns=2,
        total_tokens={"prompt": 500, "completion": 80},
        total_duration_sec=3.2,
        error_rate_before=1.0,
        error_rate_after=0.0,
        timeline=[],
        verification_summary={"passed": True},
    )

    json_str = trajectory.to_json()
    data = json.loads(json_str)

    assert data["incident_id"] == "test-001"
    assert data["resolved"] is True
    assert data["error_rate_before"] == 1.0
    assert data["error_rate_after"] == 0.0


def test_verify_all_tiers(tmp_path: Path):
    tools = AgentTools(workspace_root=tmp_path)
    harness = SREAgentHarness(tools=tools, trajectory_dir=tmp_path / "artifacts")

    # In an empty tmp_path without tests, tier 2 will fail or pass depending on pytest returncode
    res = harness.verify_all_tiers()
    assert "tier1_incident_probe" in res
    assert "tier2_regression_suite" in res
    assert "tier3_reproduction_test" in res
    assert isinstance(res["passed"], bool)


def test_harness_run_incident_mock_mode(tmp_path: Path):
    """
    Tests the full observable execution loop in mock_mode (deterministic, offline).
    Verifies that turns, tool calls, arguments, outputs, and trajectory are recorded.
    """
    graph = SystemTopologyGraph()
    tools = AgentTools(workspace_root=tmp_path, graph=graph)
    traj_dir = tmp_path / "artifacts"
    harness = SREAgentHarness(tools=tools, trajectory_dir=traj_dir, max_turns=3)

    trajectory = harness.run_incident(
        incident_id="incident-mock-99",
        incident_description="Synthetic outage on payment gateway",
        error_rate_before=0.85,
        mock_mode=True,
    )

    # Assertions on trajectory metrics
    assert trajectory.incident_id == "incident-mock-99"
    assert trajectory.total_turns > 0
    assert len(trajectory.timeline) > 0

    # Inspect first turn trace
    turn1 = trajectory.timeline[0]
    assert turn1.turn_index == 1
    assert len(turn1.tool_calls) == 1
    assert turn1.tool_calls[0].tool_name == "check_env_drift"

    # Check file output on disk
    saved_file = traj_dir / "trajectory_incident-mock-99.json"
    assert saved_file.exists()
    disk_data = json.loads(saved_file.read_text())
    assert disk_data["incident_id"] == "incident-mock-99"
    assert len(disk_data["timeline"]) == len(trajectory.timeline)
