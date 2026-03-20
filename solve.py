#!/usr/bin/env python3
"""Astar Island solver for NM i AI 2026."""

import json
import math
import sys
import time
import requests
from collections import Counter, defaultdict

# ── Config ──────────────────────────────────────────────────────────────
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhOGMxN2M1OC1lYzg0LTQ0MjQtYjMxNy1iYjgzY2UxY2IwNTUiLCJlbWFpbCI6ImhlbnJpazE5OTAwQGdtYWlsLmNvbSIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzc0NjM2NDA2fQ.FmG-dX5M2v3PXBOfIneuWpouAwVnD-PU0cMwHdwsoAY"
BASE = "https://api.ainm.no/astar-island"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

GRID_TO_CLASS = {11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 10: 0}
NUM_CLASSES = 6
H, W = 40, 40
VP_SIZE = 15


def api_get(path):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path, data):
    r = requests.post(f"{BASE}{path}", headers=HEADERS, json=data, timeout=30)
    r.raise_for_status()
    return r.json()


def min_dist_to_settlement(x, y, settlements):
    return min(abs(x - s["x"]) + abs(y - s["y"]) for s in settlements) if settlements else 99


def is_coastal(x, y, grid):
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        nx, ny = x+dx, y+dy
        if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
            return True
    return False


def compute_dynamic_value(seed_state):
    grid = seed_state["grid"]
    settlements = seed_state["settlements"]
    value = [[0.0]*W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            terrain = grid[y][x]
            if terrain in (10, 5):
                continue
            d = min_dist_to_settlement(x, y, settlements)
            if d == 0:
                value[y][x] = 5.0
            elif d <= 2:
                value[y][x] = 3.0
            elif d <= 4:
                value[y][x] = 1.5
            elif d <= 6:
                value[y][x] = 0.5
            if is_coastal(x, y, grid) and d <= 3:
                value[y][x] *= 1.5
    return value


def find_best_viewports(seed_state, num_queries):
    value = compute_dynamic_value(seed_state)
    viewports = []
    coverage = [[0]*W for _ in range(H)]

    for _ in range(num_queries):
        best_score = -1
        best_pos = None
        for vy in range(0, H - VP_SIZE + 1, 2):
            for vx in range(0, W - VP_SIZE + 1, 2):
                score = 0.0
                for dy in range(VP_SIZE):
                    for dx in range(VP_SIZE):
                        v = value[vy+dy][vx+dx]
                        c = coverage[vy+dy][vx+dx]
                        score += v / (1 + c)
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)
        if best_pos is None:
            break
        viewports.append(best_pos)
        vx, vy = best_pos
        for dy in range(VP_SIZE):
            for dx in range(VP_SIZE):
                coverage[vy+dy][vx+dx] += 1
    return viewports


def allocate_queries(initial_states, total_budget=50):
    complexities = [len(s["settlements"]) for s in initial_states]
    total_c = sum(complexities)
    allocations = [max(6, round(total_budget * c / total_c)) for c in complexities]
    while sum(allocations) > total_budget:
        idx = allocations.index(max(allocations))
        allocations[idx] -= 1
    while sum(allocations) < total_budget:
        idx = allocations.index(min(allocations))
        allocations[idx] += 1
    return allocations


def run_simulations(round_id, initial_states, allocations):
    all_observations = []
    for seed_idx, (state, n_queries) in enumerate(zip(initial_states, allocations)):
        observations = defaultdict(list)
        viewports = find_best_viewports(state, n_queries)
        print(f"  Seed {seed_idx}: {n_queries} queries, {len(set(viewports))} unique viewports")

        for qi, (vx, vy) in enumerate(viewports):
            print(f"    Query {qi+1}/{n_queries}: viewport ({vx},{vy})", end=" ")
            try:
                result = api_post("/simulate", {
                    "round_id": round_id,
                    "seed_index": seed_idx,
                    "viewport_x": vx,
                    "viewport_y": vy,
                    "viewport_width": VP_SIZE,
                    "viewport_height": VP_SIZE,
                })
            except Exception as e:
                print(f"ERROR: {e}")
                continue

            grid_data = result.get("grid", [])
            actual_vx = result.get("viewport_x", vx)
            actual_vy = result.get("viewport_y", vy)

            for dy, row in enumerate(grid_data):
                for dx, cell_code in enumerate(row):
                    cx, cy = actual_vx + dx, actual_vy + dy
                    if 0 <= cx < W and 0 <= cy < H:
                        cls = GRID_TO_CLASS.get(cell_code, 0)
                        observations[(cx, cy)].append(cls)

            n_cells = sum(len(row) for row in grid_data)
            print(f"-> {n_cells} cells")

        all_observations.append(observations)
    return all_observations


def dynamic_prior(x, y, grid, settlements):
    terrain = grid[y][x]
    if terrain == 5:
        return [0.004, 0.004, 0.004, 0.004, 0.004, 0.98]
    if terrain == 10:
        return [0.98, 0.004, 0.004, 0.004, 0.004, 0.004]

    d = min_dist_to_settlement(x, y, settlements)
    coastal = is_coastal(x, y, grid)

    p_settle = max(0.02, 0.5 * math.exp(-0.5 * d))
    p_port = 0.25 * p_settle if coastal else 0.005
    p_settle -= p_port
    p_ruin = 0.12 * p_settle
    if terrain == 4:
        p_forest = max(0.3, 0.85 * math.exp(-0.3 * max(0, 5 - d)))
    else:
        p_forest = 0.03 + 0.08 * (d > 3)
    p_mountain = 0.005
    p_empty = 1.0 - p_settle - p_port - p_ruin - p_forest - p_mountain

    probs = [p_empty, p_settle, p_port, p_ruin, p_forest, p_mountain]
    probs = [max(p, 0.01) for p in probs]
    total = sum(probs)
    return [p / total for p in probs]


def build_predictions(initial_states, all_observations):
    all_predictions = []
    for seed_idx, (state, observations) in enumerate(zip(initial_states, all_observations)):
        grid = state["grid"]
        settlements = state["settlements"]
        predictions = [[[0.0]*NUM_CLASSES for _ in range(W)] for _ in range(H)]

        for y in range(H):
            for x in range(W):
                terrain = grid[y][x]
                obs = observations.get((x, y), [])

                if terrain == 10:
                    pred = [0.98, 0.004, 0.004, 0.004, 0.004, 0.004]
                elif terrain == 5:
                    pred = [0.004, 0.004, 0.004, 0.004, 0.004, 0.98]
                elif len(obs) > 0:
                    prior = dynamic_prior(x, y, grid, settlements)
                    prior_weight = 1.0
                    counts = [0]*NUM_CLASSES
                    for o in obs:
                        counts[o] += 1
                    N = len(obs)
                    pred = [(counts[c] + prior_weight * prior[c]) / (N + prior_weight) for c in range(NUM_CLASSES)]
                else:
                    pred = dynamic_prior(x, y, grid, settlements)

                pred = [max(p, 0.01) for p in pred]
                total = sum(pred)
                pred = [p / total for p in pred]
                predictions[y][x] = pred

        all_predictions.append(predictions)
        print(f"  Seed {seed_idx}: predictions built ({sum(1 for k,v in observations.items() if len(v)>0)} observed cells)")
    return all_predictions


def submit_predictions(round_id, all_predictions):
    results = []
    for seed_idx, preds in enumerate(all_predictions):
        try:
            result = api_post("/submit", {
                "round_id": round_id,
                "seed_index": seed_idx,
                "prediction": preds,
            })
            print(f"  Seed {seed_idx}: {result}")
            results.append(result)
        except requests.exceptions.HTTPError as e:
            print(f"  Seed {seed_idx} ERROR: {e}")
            print(f"    Response: {e.response.text}")
            results.append(None)
    return results


def main():
    print("=== Astar Island Solver ===\n")

    print("[1] Fetching rounds...")
    rounds = api_get("/rounds")
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        print("No active round!")
        sys.exit(1)
    round_info = active[0]
    round_id = round_info["id"]
    print(f"  Active: round #{round_info['round_number']} (closes {round_info['closes_at']})")

    print("\n[2] Checking budget...")
    budget = api_get("/budget")
    remaining = budget["queries_max"] - budget["queries_used"]
    print(f"  {remaining}/{budget['queries_max']} queries remaining")

    print("\n[3] Fetching initial states...")
    round_data = api_get(f"/rounds/{round_id}")
    initial_states = round_data["initial_states"]
    for i, s in enumerate(initial_states):
        print(f"  Seed {i}: {len(s['settlements'])} settlements ({sum(1 for st in s['settlements'] if st['has_port'])} ports)")

    if remaining > 0:
        print(f"\n[4] Allocating {remaining} queries...")
        allocations = allocate_queries(initial_states, remaining)
        print(f"  Allocation: {allocations}")

        print("\n[5] Running simulations...")
        all_observations = run_simulations(round_id, initial_states, allocations)
    else:
        print("\n  No queries left, using priors only.")
        all_observations = [defaultdict(list) for _ in range(5)]

    print("\n[6] Building predictions...")
    all_predictions = build_predictions(initial_states, all_observations)

    print("\n[7] Submitting...")
    results = submit_predictions(round_id, all_predictions)

    print("\n[8] Final check...")
    try:
        my_rounds = api_get("/my-rounds")
        for r in my_rounds:
            if r.get("round_id") == round_id or r.get("id") == round_id:
                print(f"  Score: {json.dumps(r, indent=2)}")
                break
    except Exception as e:
        print(f"  {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
