Original test floor plan (made from scratch, not from ResPlan)
================================================================

File to upload:  floor_plan_input.json

How to use
  1. The server must be running (http://127.0.0.1:8765).
  2. In the viewer press "Upload plan" and choose floor_plan_input.json.
  3. When it has solved, use the Download box on the right ("Answer (JSON)") and save the file.
  4. Give the downloaded answer file to Claude to check.

The flat (14 m x 10 m, 20 drawing units per metre, plan id 777001)
  - 6 rooms that need a node: living room 34.6 m2, kitchen 17.8 m2, storage 9.4 m2 and three bedrooms
    (19.4, 18.9 and 21.6 m2). Total 121.6 m2, so at least 2 hubs.
  - 1 bathroom (no node), 1 balcony outside the walls, a front door, 10 windows.
  - Kitchen and living room are joined by an open 3 m gap (no door).
  - Storage is a dead end: one door, from the kitchen.
  - Bedroom 3 and the bathroom open onto the kitchen; bedrooms 1 and 2 onto the living room.
  - Bedroom 1 also has a door to the balcony, which is outside the cable area.
  - The six nodes are placed off-centre, at least 1.1 m from the walls.
