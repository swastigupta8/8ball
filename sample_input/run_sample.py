"""Send a sample input file to the running server (POST /api/solve) and print what comes back.

Usage:  .venv/Scripts/python.exe sample_input/run_sample.py sample_input/sample_plan_<id>.json
Needs the server running:  .venv/Scripts/python.exe -m eightball serve --port 8765
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

src = Path(sys.argv[1])
req = urllib.request.Request("http://127.0.0.1:8765/api/solve", data=src.read_bytes(),
                             headers={"Content-Type": "application/json"})
t = time.time()
res = json.load(urllib.request.urlopen(req, timeout=180))
a, chk = res["answer"], res["check"]
print(f"solved in {time.time() - t:.1f} s by the {a['meta']['solver']} solver")
print(f"hubs {a['metrics']['H']}  cable {a['metrics']['L']:.2f} m  crossings {a['metrics']['X']}  "
      f"overlap {a['metrics']['O']:.2f} m  bends {a['metrics']['B']}  J {a['metrics']['J']:.2f}")
print("independent checker:", "VALID" if chk["valid"] else f"INVALID ({len(chk['violations'])} violations)")
for h in a["hubs"]:
    print(f"  {h['hub_id']}: rooms {', '.join(h['room_ids'])}  order {' -> '.join(h['sequence'])}")
out = src.with_name(src.stem.replace("sample_plan", "result") + ".json")
out.write_text(json.dumps(res, indent=1), encoding="utf-8")
print("full result saved to", out)
