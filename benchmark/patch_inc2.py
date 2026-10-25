import json
with open("incidents/incident_02_missing_index/checks.json", "r") as f:
    c = json.load(f)
c["max_p95_latency"] = 0.02
with open("incidents/incident_02_missing_index/checks.json", "w") as f:
    json.dump(c, f, indent=2)

with open("scratch/generate_incidents2.py", "r") as f:
    c = f.read()
c = c.replace('"max_p95_latency": 0.3', '"max_p95_latency": 0.02')
with open("scratch/generate_incidents2.py", "w") as f:
    f.write(c)
