#!/usr/bin/env python3
import sys
import json
import subprocess
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("incident")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    traffic_file = f"../incidents/{args.incident}/traffic.jsonl"
    checks_file = f"../incidents/{args.incident}/checks.json"
    
    with open(checks_file) as f:
        checks = json.load(f)

    # Replay with concurrency to prevent timeouts
    result = subprocess.run([
        sys.executable,
        "./replay.py",
        traffic_file,
        "--base-url",
        args.base_url,
        "--concurrency",
        str(args.concurrency)
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print("Replay failed")
        print(result.stderr)
        sys.exit(1)
        
    data = json.loads(result.stdout)
    metrics = data["metrics"]
    responses = data["responses"]
    
    error_rate = metrics["error_count"] / max(1, metrics["request_count"])
    passed = True
    
    if "max_error_rate" in checks:
        if error_rate > checks["max_error_rate"]:
            print(f"FAILED: Error rate {error_rate} > {checks['max_error_rate']}")
            passed = False
            
    if "max_p95_latency" in checks:
        if metrics["p95_latency"] > checks["max_p95_latency"]:
            print(f"FAILED: p95 latency {metrics['p95_latency']} > {checks['max_p95_latency']}")
            passed = False
            
    if "golden_checks" in checks:
        for idx, expected in checks["golden_checks"].items():
            idx = int(idx)
            if idx >= len(responses):
                print(f"FAILED: Missing response for check {idx}")
                passed = False
                continue
                
            actual = responses[idx]
            if "status" in expected and actual["status"] != expected["status"]:
                 print(f"FAILED: check {idx} status {actual['status']} != {expected['status']}")
                 passed = False
            if "body" in expected:
                 try:
                     actual_body = json.loads(actual["body"])
                     for k, v in expected["body"].items():
                          if actual_body.get(k) != v:
                               print(f"FAILED: check {idx} body[{k}] {actual_body.get(k)} != {v}")
                               passed = False
                 except Exception:
                     print(f"FAILED: check {idx} body is not json or missing keys. {actual['body']}")
                     passed = False

    if passed:
        print("PASS")
        sys.exit(0)
    else:
        print("FAIL")
        sys.exit(1)

if __name__ == "__main__":
    main()
