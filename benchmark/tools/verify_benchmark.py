#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import urllib.request

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def wait_for_api():
    for _ in range(30):
        try:
            r = urllib.request.urlopen("http://localhost:8000/health", timeout=1)
            if r.getcode() == 200: return
        except Exception:
            pass
        time.sleep(1)

def restart(setup_cmd):
    run_cmd(setup_cmd)
    run_cmd("cd ../shopfront && docker compose down -v && docker compose up --build -d")
    wait_for_api()

def apply_cheat(cheat_type):
    with open("../shopfront/api/main.py", "r") as f: c = f.read()
    if cheat_type == "disable":
        c = c.replace("return prod", "raise HTTPException(status_code=404, detail='Not found')")
        c = c.replace('return {"order_id": order_id, "status": "COMPLETED"}', 'raise HTTPException(status_code=404, detail="Not found")')
    elif cheat_type == "hardcode_200":
        c = c.replace("return prod", "return {'id': 1, 'name': 'fake', 'price': 100, 'inventory': 10}")
        c = c.replace('return {"order_id": order_id, "status": "COMPLETED"}', 'return {"order_id": 1, "status": "COMPLETED"}')
    with open("../shopfront/api/main.py", "w") as f: f.write(c)

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    incidents = sorted([d for d in os.listdir("../incidents") if d.startswith("incident_")])
    if not incidents: sys.exit(1)
         
    failed = False
    for inc in incidents:
         print(f"\n=== Verifying {inc} ===")
         # Baseline
         restart(f"cd ../shopfront && git reset --hard baseline && git clean -fd")
         if run_cmd(f"./grade.py {inc}").returncode != 0:
              print(f"| Baseline | FAIL (Expected PASS) |"); failed = True
         else:
              print(f"| Baseline | PASS |")
              
         # Injected
         restart(f"./inject.sh {inc}")
         if run_cmd(f"./grade.py {inc}").returncode == 0:
              print(f"| Injected | PASS (Expected FAIL) |"); failed = True
         else:
              print(f"| Injected | FAIL |")
              
         # Fixed
         restart(f"cd ../shopfront && patch -p1 < ../incidents/{inc}/fix.patch")
         if run_cmd(f"./grade.py {inc}").returncode != 0:
              print(f"| Fixed    | FAIL (Expected PASS) |"); failed = True
         else:
              print(f"| Fixed    | PASS |")
              
         # Cheats
         for cheat in ["disable", "hardcode_200", "delete_check"]:
              run_cmd(f"./inject.sh {inc}")
              if cheat == "delete_check":
                   run_cmd(f"mv ../incidents/{inc}/checks.json ../incidents/{inc}/checks.json.bak")
                   run_cmd(f"echo '{{}}' > ../incidents/{inc}/checks.json")
                   restart("true")
              else:
                   apply_cheat(cheat)
                   restart("true")
                   
              r = run_cmd(f"./grade.py {inc}")
              
              if cheat == "delete_check":
                   run_cmd(f"mv ../incidents/{inc}/checks.json.bak ../incidents/{inc}/checks.json")
                   
              if r.returncode == 0:
                   print(f"| Cheat:{cheat.ljust(12)} | PASS (Expected FAIL) |"); failed = True
              else:
                   print(f"| Cheat:{cheat.ljust(12)} | FAIL |")
              
    if failed:
        sys.exit(1)
    else:
        print("\nALL PASSED")

if __name__ == "__main__":
    main()
