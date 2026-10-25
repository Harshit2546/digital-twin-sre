# Autonomous Incident Response Benchmark

This is an evaluation environment for testing an autonomous incident-response agent. It provides a small "production" toy system (a shopfront with an API, background worker, database, and payments stub) along with 12 deterministic incident scenarios that can be injected, evaluated, and graded.

## Layout

- `shopfront/`: The baseline "production" system codebase. Includes `docker-compose.yml`, `api/`, `worker/`, `db/`, `payments/`, and `config/`.
- `incidents/`: Contains 12 incident scenarios. Each incident folder contains:
  - `inject.patch`: A git patch applied to the baseline to create the broken state.
  - `fix.patch`: The reference fix patch.
  - `incident.md`: The alert/ticket presented to the agent.
  - `traffic.jsonl`: The recorded sequence of requests that triggers the failure.
  - `checks.json`: Success criteria for grading the fix (error rates, latencies, golden responses).
  - `meta.json`: Metadata such as difficulty, category, and root cause summary.
- `tools/`: Helper scripts for running the benchmark.
  - `inject.sh <incident>`: Resets the baseline, applies the incident patch, and restarts the environment.
  - `replay.py <traffic.jsonl> --base-url URL`: Replays the traffic sequence against the API and reports metrics.
  - `grade.py <incident>`: Replays traffic and checks the responses against `checks.json`, returning exit code 0 if ALL criteria pass.
  - `verify_benchmark.py`: Verifies the benchmark's correctness by testing the baseline, injected, and fixed states for all incidents.

## How to run an incident manually

1. Inject the incident to break the environment:
   ```bash
   ./tools/inject.sh incident_01_config_error
   ```
2. The agent should read `incidents/incident_01_config_error/incident.md` and attempt to fix the system by modifying the code in `shopfront/` and restarting services if necessary.
3. Grade the agent's fix:
   ```bash
   cd tools/
   ./grade.py incident_01_config_error
   ```

## Grading Metrics Definitions

- **Error Rate (`max_error_rate`)**: The proportion of HTTP requests in the replay traffic that result in a 5xx HTTP status code. 
- **P95 Latency (`max_p95_latency`)**: The 95th percentile of response times for all requests in the traffic replay. Used to catch slow queries or inefficient code.
- **Golden Checks (`golden_checks`)**: Deterministic assertions on specific requests in the traffic. Maps the 0-indexed request number to an expected HTTP status code or JSON response body fields. Ensures that an agent doesn't "fix" an incident by blindly returning 200 OK or breaking functionality.

## Verifying the Benchmark

To verify that all incidents are correctly structured and deterministic:
```bash
./tools/verify_benchmark.py
```
This script will iterate through all 12 incidents and confirm that the baseline passes, the injected state fails, and the fixed state passes the grading checks.