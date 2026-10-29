#!/usr/bin/env python3
import sys
import time
import json
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

import config
from runtime.twin import DigitalTwin
from agent.brain import AutonomousSREAgent

console = Console()

ALL_INCIDENTS = [
    "incident_01_config_error",
    "incident_02_missing_index",
    "incident_03_unbounded_cache",
    "incident_04_bad_deploy_null",
    "incident_05_payments_timeout",
    "incident_06_retry_storm",
    "incident_07_connection_leak",
    "incident_08_wrong_config_key",
    "incident_09_db_migration_not_null",
    "incident_10_race_condition",
    "incident_11_stale_cache",
    "incident_12_log_injection",
]

def main():
    parser = argparse.ArgumentParser(description="Evaluate SRE Agent across the Digital Twin Benchmark")
    parser.add_argument("--mock", action="store_true", help="Run with deterministic reference solver (offline)")
    parser.add_argument("--model", default=config.MODEL_NAME, help="Model name")
    parser.add_argument("--incidents", nargs="*", default=ALL_INCIDENTS, help="Subset of incidents to run")
    args = parser.parse_args()

    results = []

    console.print(f"\n[bold green]═══════════════════════════════════════════════════════════════[/bold green]")
    console.print(f"[bold green]   AUTONOMOUS SRE AGENT DIGITAL TWIN BENCHMARK EVALUATOR       [/bold green]")
    console.print(f"[bold green]═══════════════════════════════════════════════════════════════[/bold green]\n")
    console.print(f"Total Incidents to evaluate: [bold]{len(args.incidents)}[/bold]")
    console.print(f"Model: [bold]{args.model}[/bold] | Mode: [bold]{'Deterministic Reference' if args.mock else 'Live LLM'}[/bold]\n")

    overall_start = time.time()

    for idx, inc in enumerate(args.incidents, 1):
        console.print(f"\n[bold cyan]▶ [{idx}/{len(args.incidents)}] Running: {inc}[/bold cyan]")
        
        twin = DigitalTwin(
            incident_name=inc,
            benchmark_dir=str(config.BENCHMARK_DIR),
            api_port=config.DEFAULT_API_PORT,
            payments_port=config.DEFAULT_PAYMENTS_PORT,
            db_port=config.DEFAULT_DB_PORT,
            twins_base_dir=str(config.TWIN_BASE_DIR)
        )
        agent = AutonomousSREAgent(twin=twin, model_name=args.model)

        try:
            res = agent.solve(mock_mode=args.mock)
            results.append(res)
        except Exception as e:
            console.print(f"[bold red]Exception evaluating {inc}: {e}[/bold red]")
            results.append({
                "incident": inc,
                "resolved": False,
                "iterations": 0,
                "duration_seconds": 0.0,
                "error": str(e)
            })
        finally:
            twin.cleanup()

    total_time = time.time() - overall_start

    # Render Scorecard
    table = Table(title="Autonomous Incident Response Benchmark Scorecard", show_header=True, header_style="bold magenta")
    table.add_column("Incident", style="dim", width=36)
    table.add_column("Result", justify="center")
    table.add_column("Turns", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Security", justify="center")

    resolved_count = 0
    for r in results:
        status = "[bold green]PASS[/bold green]" if r.get("resolved") else "[bold red]FAIL[/bold red]"
        if r.get("resolved"):
            resolved_count += 1
        dur = f"{r.get('duration_seconds', 0.0):.1f}s"
        turns = str(r.get("iterations", 0))
        sec_leak = r.get("after_metrics", {}).get("credential_leak", False)
        sec = "[bold red]LEAK DETECTED[/bold red]" if sec_leak else "[green]CLEAN[/green]"
        table.add_row(r["incident"], status, turns, dur, sec)

    console.print("\n")
    console.print(table)

    pass_rate = (resolved_count / len(results)) * 100 if results else 0
    console.print(f"\n[bold]Total Pass Rate: {resolved_count}/{len(results)} ({pass_rate:.1f}%)[/bold]")
    console.print(f"[bold]Total Benchmark Duration: {total_time:.1f}s[/bold]\n")

    # Persist benchmark scorecard artifact
    artifacts_dir = config.BASE_DIR / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    scorecard_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": args.model,
        "mode": "mock" if args.mock else "live",
        "total_incidents": len(args.incidents),
        "resolved_count": resolved_count,
        "pass_rate_percent": round(pass_rate, 2),
        "total_benchmark_duration_seconds": round(total_time, 2),
        "results": [
            {
                "incident": r.get("incident"),
                "resolved": r.get("resolved", False),
                "iterations": r.get("iterations", 0),
                "duration_seconds": r.get("duration_seconds", 0.0),
                "credential_leak": r.get("after_metrics", {}).get("credential_leak", False),
                "error": r.get("error"),
            }
            for r in results
        ],
    }
    scorecard_path = artifacts_dir / "benchmark_scorecard.json"
    scorecard_path.write_text(json.dumps(scorecard_data, indent=2), encoding="utf-8")
    console.print(f"[bold blue]📊 Benchmark Scorecard saved to: {scorecard_path}[/bold blue]\n")

    sys.exit(0 if resolved_count == len(results) else 1)

if __name__ == "__main__":
    main()
