#!/usr/bin/env python3
"""Astar Island solver for NM i AI 2026 — optimized with calibrated priors."""

import json
import math
import sys
import requests
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────────
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhOGMxN2M1OC1lYzg0LTQ0MjQtYjMxNy1iYjgzY2UxY2IwNTUiLCJlbWFpbCI6ImhlbnJpazE5OTAwQGdtYWlsLmNvbSIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzc0NjM2NDA2fQ.FmG-dX5M2v3PXBOfIneuWpouAwVnD-PU0cMwHdwsoAY"
BASE = "https://api.ainm.no/astar-island"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

GRID_TO_CLASS = {11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 10: 0}
NUM_CLASSES = 6
H, W = 40, 40
VP_SIZE = 15

# ── Calibrated priors from ground truth analysis of 9 completed rounds ──
# Key: (terrain_category, distance_bucket, is_coastal)
# Values: [empty, settlement, port, ruin, forest, mountain]
CALIBRATED_PRIORS = {
    # Empty/plains cells
    ("empty", "d0", False):   [0.4778, 0.2697, 0.0000, 0.0245, 0.2280, 0.0000],
    ("empty", "d0", True):    [0.5110, 0.0770, 0.1440, 0.0172, 0.2507, 0.0000],
    ("empty", "d1-2", False): [0.7550, 0.1757, 0.0000, 0.0160, 0.0533, 0.0000],
    ("empty", "d1-2", True):  [0.7661, 0.0744, 0.1032, 0.0140, 0.0422, 0.0000],
    ("empty", "d3-4", False): [0.8744, 0.0843, 0.0000, 0.0089, 0.0325, 0.0000],
    ("empty", "d3-4", True):  [0.8906, 0.0428, 0.0328, 0.0071, 0.0267, 0.0000],
    ("empty", "d5-6", False): [0.9277, 0.0469, 0.0000, 0.0053, 0.0200, 0.0000],
    ("empty", "d5-6", True):  [0.9385, 0.0197, 0.0193, 0.0045, 0.0180, 0.0000],
    ("empty", "d7+", False):  [0.9625, 0.0262, 0.0000, 0.0034, 0.0079, 0.0000],
    ("empty", "d7+", True):   [0.9719, 0.0109, 0.0085, 0.0021, 0.0066, 0.0000],
    # Forest cells
    ("forest", "d1-2", False): [0.1199, 0.1896, 0.0000, 0.0167, 0.6737, 0.0000],
    ("forest", "d1-2", True):  [0.1040, 0.0921, 0.1247, 0.0167, 0.6625, 0.0000],
    ("forest", "d3-4", False): [0.0668, 0.0901, 0.0000, 0.0092, 0.8339, 0.0000],
    ("forest", "d3-4", True):  [0.0573, 0.0457, 0.0324, 0.0073, 0.8574, 0.0000],
    ("forest", "d5-6", False): [0.0436, 0.0499, 0.0000, 0.0060, 0.9005, 0.0000],
    ("forest", "d5-6", True):  [0.0477, 0.0243, 0.0223, 0.0057, 0.8999, 0.0000],
    ("forest", "d7+", False):  [0.0174, 0.0285, 0.0000, 0.0033, 0.9508, 0.0000],
    ("forest", "d7+", True):   [0.0149, 0.0109, 0.0079, 0.0021, 0.9642, 0.0000],
    # Settlement cells (d=0 by definition)
    ("settlement", "d0", False): [0.4778, 0.2697, 0.0000, 0.0245, 0.2280, 0.0000],
    ("settlement", "d0", True):  [0.5110, 0.0770, 0.1440, 0.0172, 0.2507, 0.0000],
    # Port cells (d=0, always coastal)
    ("port", "d0", True):        [0.5253, 0.0771, 0.1203, 0.0175, 0.2599, 0.0000],
}
# Floor value to avoid KL catastrophe
PROB_FLOOR = 0.005


def api_get(path):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path, data):
    r = requests.post(f"{BASE}{path}", headers=HEADERS, json=data, timeout=30)
    r.raise_for_status()
    return r.json()


def precompute_distances(settlements):
    """Precompute min manhattan distance to any settlement for entire grid."""
    dist = [[999] * W for _ in range(H)]
    for s in settlements:
        sx, sy = s["x"], s["y"]
        for y in range(H):
            for x in range(W):
                d = abs(x - sx) + abs(y - sy)
                if d < dist[y][x]:
                    dist[y][x] = d
    return dist


def precompute_coastal(grid):
    """Precompute coastal status for entire grid."""
    coastal = [[False] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
                    coastal[y][x] = True
                    break
    return coastal


def dist_bucket(d):
    if d == 0:
        return "d0"
    elif d <= 2:
        return "d1-2"
    elif d <= 4:
        return "d3-4"
    elif d <= 6:
        return "d5-6"
    else:
        return "d7+"


def terrain_category(terrain_code):
    if terrain_code == 1:
        return "settlement"
    elif terrain_code == 2:
        return "port"
    elif terrain_code == 4:
        return "forest"
    else:  # 11 = empty/plains
        return "empty"


def get_calibrated_prior(terrain, d, coastal):
    """Get calibrated prior from ground truth analysis."""
    tc = terrain_category(terrain)
    db = dist_bucket(d)

    # Settlement/port are always d0
    if tc == "settlement":
        key = ("settlement", "d0", coastal)
    elif tc == "port":
        key = ("port", "d0", True)
    elif tc == "forest":
        # Forest at d=0 doesn't exist in calibration data (it's a settlement cell)
        # Use d1-2 as fallback
        if db == "d0":
            db = "d1-2"
        key = (tc, db, coastal)
    else:
        key = ("empty", db, coastal)

    prior = CALIBRATED_PRIORS.get(key)
    if prior is None:
        # Fallback: try without coastal distinction
        key_fallback = (key[0], key[1], False)
        prior = CALIBRATED_PRIORS.get(key_fallback)
    if prior is None:
        # Ultimate fallback
        prior = [0.85, 0.05, 0.01, 0.01, 0.07, 0.01]

    # Apply floor and normalize (floor after normalization to ensure min)
    floored = [max(p, PROB_FLOOR) for p in prior]
    total = sum(floored)
    result = [p / total for p in floored]
    # Re-floor after normalization
    result = [max(p, PROB_FLOOR) for p in result]
    total = sum(result)
    return [p / total for p in result]


def compute_dynamic_value(grid, dist_grid, coastal_grid):
    """Compute expected entropy/dynamism per cell for viewport planning."""
    value = [[0.0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            terrain = grid[y][x]
            if terrain in (10, 5):  # Ocean/Mountain: static, no value
                continue
            d = dist_grid[y][x]
            # Value based on expected entropy (from calibrated priors)
            if d == 0:
                value[y][x] = 5.0  # Settlement cells: very dynamic
            elif d <= 2:
                value[y][x] = 3.0
            elif d <= 4:
                value[y][x] = 1.5
            elif d <= 6:
                value[y][x] = 0.5
            # else: 0 (very far, almost static)

            # Coastal bonus: ports are interesting
            if coastal_grid[y][x] and d <= 3:
                value[y][x] *= 1.5
    return value


def plan_two_phase_viewports(seed_state, n_queries):
    """Two-phase viewport strategy: broad coverage first, then repeats for variance."""
    grid = seed_state["grid"]
    dist_grid = precompute_distances(seed_state["settlements"])
    coastal_grid = precompute_coastal(grid)
    value = compute_dynamic_value(grid, dist_grid, coastal_grid)

    # Phase 1: Find unique viewport positions (60% of budget)
    n_unique = max(2, int(n_queries * 0.55))
    n_repeat = n_queries - n_unique

    unique_viewports = []
    coverage = [[0] * W for _ in range(H)]

    for _ in range(n_unique):
        best_score = -1
        best_pos = None
        # Step by 1 for finer resolution
        for vy in range(0, H - VP_SIZE + 1):
            for vx in range(0, W - VP_SIZE + 1):
                score = 0.0
                for dy in range(VP_SIZE):
                    for dx in range(VP_SIZE):
                        v = value[vy + dy][vx + dx]
                        c = coverage[vy + dy][vx + dx]
                        score += v / (1 + c * 2)  # Stronger penalty for overlap
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)
        if best_pos is None or best_score <= 0:
            break
        unique_viewports.append(best_pos)
        vx, vy = best_pos
        for dy in range(VP_SIZE):
            for dx in range(VP_SIZE):
                coverage[vy + dy][vx + dx] += 1

    # Phase 2: Repeat the most valuable viewports
    # Score each unique viewport by how many dynamic cells it covers
    vp_scores = []
    for vx, vy in unique_viewports:
        score = sum(
            value[vy + dy][vx + dx]
            for dy in range(VP_SIZE)
            for dx in range(VP_SIZE)
        )
        vp_scores.append(score)

    # Distribute repeats proportionally to value
    repeat_viewports = []
    if vp_scores and n_repeat > 0:
        total_score = sum(vp_scores)
        if total_score > 0:
            for i, score in enumerate(vp_scores):
                n_reps = round(n_repeat * score / total_score)
                repeat_viewports.extend([unique_viewports[i]] * n_reps)
        # Trim or pad
        while len(repeat_viewports) > n_repeat:
            repeat_viewports.pop()
        while len(repeat_viewports) < n_repeat:
            # Add the highest-value viewport
            best_idx = vp_scores.index(max(vp_scores))
            repeat_viewports.append(unique_viewports[best_idx])

    all_viewports = unique_viewports + repeat_viewports
    return all_viewports


def allocate_queries(initial_states, total_budget=50):
    """Allocate queries proportionally to settlement count, min 7 per seed."""
    complexities = []
    for s in initial_states:
        n = len(s["settlements"])
        # Also consider settlement density (more clustered = more interesting)
        complexities.append(n)

    total_c = sum(complexities)
    allocations = [max(7, round(total_budget * c / total_c)) for c in complexities]

    while sum(allocations) > total_budget:
        idx = allocations.index(max(allocations))
        allocations[idx] -= 1
    while sum(allocations) < total_budget:
        idx = allocations.index(min(allocations))
        allocations[idx] += 1
    return allocations


def run_simulations(round_id, initial_states, allocations):
    """Run simulation queries with two-phase viewport strategy."""
    all_observations = []
    all_settlement_stats = []

    for seed_idx, (state, n_queries) in enumerate(zip(initial_states, allocations)):
        observations = defaultdict(list)
        settlement_stats = []

        viewports = plan_two_phase_viewports(state, n_queries)
        unique_count = len(set(viewports))
        print(f"  Seed {seed_idx}: {n_queries} queries, {unique_count} unique viewports")

        for qi, (vx, vy) in enumerate(viewports):
            print(f"    Q{qi + 1}/{n_queries} ({vx},{vy})", end=" ")
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
                print(f"ERR: {e}")
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

            # Collect settlement stats if available
            if "settlements" in result:
                for s in result["settlements"]:
                    settlement_stats.append(s)

            print(f"ok", end="")
            if (qi + 1) % 5 == 0 or qi == n_queries - 1:
                print()
            else:
                print(" | ", end="")

        all_observations.append(observations)
        all_settlement_stats.append(settlement_stats)

    return all_observations, all_settlement_stats


def spatial_smooth(predictions, observations, grid, dist_grid, radius=2):
    """Apply spatial smoothing: borrow information from nearby observed cells."""
    smoothed = [[[0.0] * NUM_CLASSES for _ in range(W)] for _ in range(H)]

    for y in range(H):
        for x in range(W):
            terrain = grid[y][x]
            if terrain in (10, 5):  # Static cells, no smoothing
                smoothed[y][x] = predictions[y][x][:]
                continue

            obs = observations.get((x, y), [])
            if len(obs) >= 2:
                # Enough direct observations, no need to smooth
                smoothed[y][x] = predictions[y][x][:]
                continue

            # Collect weighted neighbor observations
            neighbor_weight = 0.0
            neighbor_probs = [0.0] * NUM_CLASSES

            for ny in range(max(0, y - radius), min(H, y + radius + 1)):
                for nx in range(max(0, x - radius), min(W, x + radius + 1)):
                    if nx == x and ny == y:
                        continue
                    if grid[ny][nx] in (10, 5):
                        continue
                    n_obs = observations.get((nx, ny), [])
                    if not n_obs:
                        continue
                    # Weight by inverse distance and similar terrain
                    d = abs(nx - x) + abs(ny - y)
                    same_terrain = 1.0 if grid[ny][nx] == terrain else 0.5
                    same_dist = 1.0 if abs(dist_grid[ny][nx] - dist_grid[y][x]) <= 1 else 0.5
                    w = same_terrain * same_dist / d

                    # Count-based distribution from neighbor
                    counts = [0] * NUM_CLASSES
                    for o in n_obs:
                        counts[o] += 1
                    n_total = len(n_obs)
                    for c in range(NUM_CLASSES):
                        neighbor_probs[c] += w * counts[c] / n_total
                    neighbor_weight += w

            if neighbor_weight > 0:
                # Blend: own prediction (weight=1) + neighbor info
                own_weight = 1.0 if len(obs) == 0 else 2.0
                total_weight = own_weight + neighbor_weight * 0.3  # Reduce neighbor influence
                blended = [
                    (own_weight * predictions[y][x][c] + 0.3 * neighbor_probs[c]) / total_weight
                    for c in range(NUM_CLASSES)
                ]
                # Floor and normalize
                blended = [max(p, PROB_FLOOR) for p in blended]
                total = sum(blended)
                smoothed[y][x] = [p / total for p in blended]
            else:
                smoothed[y][x] = predictions[y][x][:]

    return smoothed


def build_predictions(initial_states, all_observations, all_settlement_stats):
    """Build predictions using calibrated priors + observations + spatial smoothing."""
    all_predictions = []

    for seed_idx, (state, observations) in enumerate(zip(initial_states, all_observations)):
        grid = state["grid"]
        settlements = state["settlements"]
        dist_grid = precompute_distances(settlements)
        coastal_grid = precompute_coastal(grid)

        predictions = [[[0.0] * NUM_CLASSES for _ in range(W)] for _ in range(H)]

        for y in range(H):
            for x in range(W):
                terrain = grid[y][x]
                obs = observations.get((x, y), [])
                d = dist_grid[y][x]
                coastal = coastal_grid[y][x]

                if terrain == 10:  # Ocean
                    pred = [0.98, 0.004, 0.004, 0.004, 0.004, 0.004]
                elif terrain == 5:  # Mountain
                    pred = [0.004, 0.004, 0.004, 0.004, 0.004, 0.98]
                elif len(obs) > 0:
                    # Bayesian: calibrated prior + observations
                    prior = get_calibrated_prior(terrain, d, coastal)
                    # Use Jeffreys-style prior weight: less weight = trust observations more
                    # With calibrated priors, we can trust them more (weight=2)
                    prior_weight = 2.0
                    counts = [0] * NUM_CLASSES
                    for o in obs:
                        counts[o] += 1
                    N = len(obs)
                    pred = [
                        (counts[c] + prior_weight * prior[c]) / (N + prior_weight)
                        for c in range(NUM_CLASSES)
                    ]
                else:
                    # No observations: use calibrated prior directly
                    pred = get_calibrated_prior(terrain, d, coastal)

                # Floor and normalize
                pred = [max(p, PROB_FLOOR) for p in pred]
                total = sum(pred)
                pred = [p / total for p in pred]
                predictions[y][x] = pred

        # Apply spatial smoothing for cells with few observations
        predictions = spatial_smooth(predictions, observations, grid, dist_grid)

        all_predictions.append(predictions)
        n_obs = sum(1 for v in observations.values() if v)
        n_multi = sum(1 for v in observations.values() if len(v) >= 2)
        print(f"  Seed {seed_idx}: {n_obs} observed cells ({n_multi} with 2+ obs)")

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
            try:
                print(f"    {e.response.text[:300]}")
            except:
                pass
            results.append(None)
    return results


def main():
    print("=== Astar Island Solver v2 (Calibrated) ===\n")

    # 1. Get active round
    print("[1] Fetching rounds...")
    rounds = api_get("/rounds")
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        print("No active round!")
        sys.exit(1)
    round_info = active[0]
    round_id = round_info["id"]
    print(f"  Active: round #{round_info['round_number']} (closes {round_info['closes_at']})")

    # 2. Check budget
    print("\n[2] Checking budget...")
    budget = api_get("/budget")
    remaining = budget["queries_max"] - budget["queries_used"]
    print(f"  {remaining}/{budget['queries_max']} queries remaining")

    # 3. Fetch initial states
    print("\n[3] Fetching initial states...")
    round_data = api_get(f"/rounds/{round_id}")
    initial_states = round_data["initial_states"]
    for i, s in enumerate(initial_states):
        n_set = len(s["settlements"])
        n_ports = sum(1 for st in s["settlements"] if st["has_port"])
        print(f"  Seed {i}: {n_set} settlements ({n_ports} ports)")

    # 4-5. Run simulations
    all_settlement_stats = [[] for _ in range(5)]
    if remaining > 0:
        print(f"\n[4] Allocating {remaining} queries...")
        allocations = allocate_queries(initial_states, remaining)
        print(f"  Allocation: {allocations}")

        print("\n[5] Running simulations...")
        all_observations, all_settlement_stats = run_simulations(
            round_id, initial_states, allocations
        )
    else:
        print("\n  No queries left, using calibrated priors only.")
        all_observations = [defaultdict(list) for _ in range(5)]

    # 6. Build predictions
    print("\n[6] Building predictions...")
    all_predictions = build_predictions(
        initial_states, all_observations, all_settlement_stats
    )

    # 7. Submit
    print("\n[7] Submitting...")
    results = submit_predictions(round_id, all_predictions)

    # 8. Check results
    print("\n[8] Final check...")
    try:
        my_rounds = api_get("/my-rounds")
        for r in my_rounds:
            if r.get("id") == round_id:
                score_info = {
                    k: v for k, v in r.items()
                    if k in ("round_number", "round_score", "seed_scores", "rank",
                             "total_teams", "seeds_submitted", "queries_used")
                }
                print(f"  {json.dumps(score_info, indent=2)}")
                break
    except Exception as e:
        print(f"  {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
