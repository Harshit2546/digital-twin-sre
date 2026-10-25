#!/usr/bin/env python3
import sys
import json
import httpx
import argparse
import time
import asyncio

async def fetch(client, req, args):
    method = req.get("method", "GET")
    path = req.get("path")
    body = req.get("body")
    headers = req.get("headers", {})
    try:
        if method == "GET":
            resp = await client.get(path, headers=headers, timeout=2.0)
        else:
            resp = await client.request(method, path, json=body, headers=headers, timeout=2.0)
        return {"status": resp.status_code, "body": resp.text}
    except Exception as e:
        return {"status": 500, "body": str(e)}

async def main_async(args, requests):
    try:
        async with httpx.AsyncClient(base_url=args.base_url) as client:
            await client.post("/metrics/reset")
    except Exception:
        pass

    responses = []
    async with httpx.AsyncClient(base_url=args.base_url) as client:
        if args.concurrency == 1:
            for req in requests:
                responses.append(await fetch(client, req, args))
        else:
            sem = asyncio.Semaphore(args.concurrency)
            async def bounded_fetch(req):
                async with sem:
                    return await fetch(client, req, args)
            tasks = [bounded_fetch(req) for req in requests]
            responses = await asyncio.gather(*tasks)
            
    try:
        async with httpx.AsyncClient(base_url=args.base_url) as client:
            metrics = (await client.get("/metrics")).json()
    except Exception as e:
        metrics = {"error_count": len([r for r in responses if r["status"] >= 500]), "request_count": len(requests), "p95_latency": 0}

    print(json.dumps({
        "metrics": metrics,
        "responses": responses
    }, indent=2))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("traffic_file")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()

    requests = []
    with open(args.traffic_file) as f:
        for line in f:
            if line.strip():
                requests.append(json.loads(line))
                
    asyncio.run(main_async(args, requests))

if __name__ == "__main__":
    main()
