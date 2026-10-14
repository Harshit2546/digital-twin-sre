#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

import config
from runtime.twin import DigitalTwin
from agent.brain import AutonomousSREAgent

console = Console()

def main():
    parser = argparse.ArgumentParser(description="Autonomous Digital Twin SRE Agent Runner")
    parser.add_argument("incident", help="Name of incident (e.g. incident_01_config_error)")
    parser.add_argument("--mock", action="store_true", help="Run with deterministic reference solver (offline)")
    parser.add_argument("--model", default=config.MODEL_NAME, help="Model name (e.g. gemini-2.5-pro, gemini-2.5-flash)")
    parser.add_argument("--keep-twin", action="store_true", help="Do not tear down twin after completion")
    parser.add_argument("--api-port", type=int, default=config.DEFAULT_API_PORT, help="Host port for API (0 = auto-allocate free ephemeral port)")
    parser.add_argument("--payments-port", type=int, default=config.DEFAULT_PAYMENTS_PORT, help="Host port for payments (0 = auto-allocate free ephemeral port)")
    parser.add_argument("--db-port", type=int, default=config.DEFAULT_DB_PORT, help="Host port for DB (0 = auto-allocate free ephemeral port)")
    args = parser.parse_args()

    incident_path = config.BENCHMARK_DIR / "incidents" / args.incident
    if not incident_path.exists():
        console.print(f"[bold red]Incident '{args.incident}' not found in {config.BENCHMARK_DIR / 'incidents'}[/bold red]")
        sys.exit(1)

    twin = DigitalTwin(
        incident_name=args.incident,
        benchmark_dir=str(config.BENCHMARK_DIR),
        api_port=args.api_port,
        payments_port=args.payments_port,
        db_port=args.db_port,
        twins_base_dir=str(config.TWIN_BASE_DIR)
    )

    agent = AutonomousSREAgent(twin=twin, model_name=args.model)

    try:
        result = agent.solve(mock_mode=args.mock)
        
        console.print("\n" + "=" * 60)
        status_str = "[bold green]RESOLVED (100% PASS)[/bold green]" if result["resolved"] else "[bold red]FAILED[/bold red]"
        console.print(f"Incident: [bold]{args.incident}[/bold] -> {status_str}")
        console.print(f"Duration: {result['duration_seconds']}s | Turns: {result['iterations']}")
        console.print("=" * 60)

        if result["pr_markdown"]:
            console.print(Panel(result["pr_markdown"], title="Verified Pull Request Generated"))
            
            # Save PR to disk
            pr_out = Path(f"pr_{args.incident}.md")
            pr_out.write_text(result["pr_markdown"])
            console.print(f"[dim]Pull Request artifact saved to: {pr_out.resolve()}[/dim]")

        sys.exit(0 if result["resolved"] else 1)

    finally:
        if not args.keep_twin:
            twin.cleanup()
        else:
            console.print(f"[yellow]Twin kept running at: {twin.shopfront_dir}[/yellow]")

if __name__ == "__main__":
    main()
