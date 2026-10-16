Sample inputs for the 8ball API
================================
1. Start the server (from the 8ball folder):
     .venv\Scripts\python.exe -m eightball serve --port 8765
2. Send a sample (from the 8ball folder, in a second terminal):
     .venv\Scripts\python.exe sample_input\run_sample.py sample_input\sample_plan_769.json
   It prints the hubs, cable length and the independent checker's verdict, and saves the full result next to the input.

Files
  sample_plan_769.json   a 2-hub flat that solves in about 2 s (ResPlan test plan 769, centre nodes)
  sample_plan_224.json   a bigger 2-hub flat, a few seconds
  example_set_aside_plan_3236.json   one of the ~8% of plans with no legal split under our rules: the exact solver
                                     says so in meta.warnings and returns the greedy answer, which the checker marks invalid
  make_sample.py         makes a new sample from any ResPlan plan id:  .venv\Scripts\python.exe sample_input\make_sample.py <id>

Input format (body of POST /api/solve)
  "plan":   the floor plan, one WKT text per layer (living, bedroom, kitchen, storage, bathroom, balcony, door, window,
            wall, front_door, inner, ...) in drawing units, plus "id", "area" (m2, stated) and "wall_depth".
  "nodes":  one point per eligible room: {"node_id": "N1", "room_id": "living_0", "point": [x, y]}, same units.
            Leave "nodes" out to use practice nodes ("nodes_mode": "center" or "random").
  "solver": "exact" (default) or "greedy".
Room ids are "{type}_{k}", numbered in order of position (see io/resplan.room_parts).
