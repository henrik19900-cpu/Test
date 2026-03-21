#!/usr/bin/env python3
"""Astar Island solver v5 — auto-detect viewport, pooled + per-cell predictions."""

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
PROB_FLOOR = 0.004

# Fallback priors (average across 10 completed rounds)
FALLBACK_PRIORS = {
    ("settlement", "d0"):  [0.49, 0.25, 0.01, 0.02, 0.22, 0.01],
    ("port", "d0"):        [0.53, 0.08, 0.12, 0.02, 0.24, 0.01],
    ("empty", "d0"):       [0.49, 0.20, 0.03, 0.02, 0.25, 0.01],
    ("empty", "d1-2"):     [0.76, 0.14, 0.02, 0.01, 0.05, 0.01],
    ("empty", "d3-4"):     [0.88, 0.06, 0.01, 0.01, 0.03, 0.01],
    ("empty", "d5-6"):     [0.93, 0.03, 0.01, 0.005, 0.02, 0.005],
    ("empty", "d7+"):      [0.97, 0.01, 0.005, 0.003, 0.007, 0.005],
    ("forest", "d1-2"):    [0.11, 0.14, 0.03, 0.02, 0.68, 0.02],
    ("forest", "d3-4"):    [0.06, 0.07, 0.01, 0.01, 0.84, 0.01],
    ("forest", "d5-6"):    [0.05, 0.04, 0.01, 0.005, 0.90, 0.005],
    ("forest", "d7+"):     [0.02, 0.02, 0.005, 0.003, 0.95, 0.005],
}


def api_get(path):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path, data):
    r = requests.post(f"{BASE}{path}", headers=HEADERS, json=data, timeout=30)
    r.raise_for_status()
    return r.json()


def floor_normalize(probs):
    floored = [max(p, PROB_FLOOR) for p in probs]
    total = sum(floored)
    result = [p / total for p in floored]
    result = [max(p, PROB_FLOOR) for p in result]
    total = sum(result)
    return [p / total for p in result]


def precompute_distances(settlements):
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
    else:
        return "empty"


def cell_key(terrain, d):
    tc = terrain_category(terrain)
    db = dist_bucket(d)
    if tc == "forest" and db == "d0":
        db = "d1-2"
    return (tc, db)


# ── Viewport strategy ──────────────────────────────────────────────────

def detect_max_viewport(round_id, seed_idx):
    """Try progressively smaller viewports to find the maximum allowed size."""
    for size in [40, 30, 20, 15]:
        try:
            result = api_post("/simulate", {
                "round_id": round_id,
                "seed_index": seed_idx,
                "viewport_x": 0,
                "viewport_y": 0,
                "viewport_width": size,
                "viewport_height": size,
            })
            grid_data = result.get("grid", [])
            actual_h = len(grid_data)
            actual_w = len(grid_data[0]) if grid_data else 0
            print(f"  Viewport {size}x{size} → got {actual_w}x{actual_h}")
            return size, result
        except requests.exceptions.HTTPError as e:
            error_text = ""
            try:
                error_text = e.response.text
            except:
                pass
            if "viewport" in error_text.lower() or "size" in error_text.lower():
                print(f"  Viewport {size}x{size} rejected: {error_text[:100]}")
                continue
            else:
                # Other error (budget, auth, etc.) — re-raise
                raise
    return 15, None  # Fallback


def compute_dynamic_value(grid, dist_grid):
    value = [[0.0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            terrain = grid[y][x]
            if terrain in (10, 5):
                continue
            d = dist_grid[y][x]
            if d == 0:
                value[y][x] = 5.0
            elif d <= 2:
                value[y][x] = 3.0
            elif d <= 4:
                value[y][x] = 1.0
            elif d <= 6:
                value[y][x] = 0.3
    return value


def find_viewports(value, n_viewports, vp_size):
    """Greedy viewport placement for maximum coverage."""
    viewports = []
    coverage = [[0] * W for _ in range(H)]
    step = max(1, vp_size // 5)

    for _ in range(n_viewports):
        best_score = -1
        best_pos = None
        for vy in range(0, H - vp_size + 1, step):
            for vx in range(0, W - vp_size + 1, step):
                score = 0.0
                for dy in range(vp_size):
                    for dx in range(vp_size):
                        v = value[vy + dy][vx + dx]
                        c = coverage[vy + dy][vx + dx]
                        score += v / (1 + c * 5)
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)
        if best_pos is None or best_score <= 0:
            break
        viewports.append(best_pos)
        vx, vy = best_pos
        for dy in range(vp_size):
            for dx in range(vp_size):
                coverage[vy + dy][vx + dx] += 1
    return viewports


def allocate_queries(initial_states, total_budget, vp_size):
    """Allocate queries. With full-grid viewport, split evenly."""
    n_seeds = len(initial_states)
    if vp_size >= 40:
        # Full grid: split evenly across seeds
        base = total_budget // n_seeds
        allocations = [base] * n_seeds
        for i in range(total_budget - sum(allocations)):
            allocations[i] += 1
        return allocations

    # Proportional to dynamic cell count
    complexities = []
    for s in initial_states:
        dist_grid = precompute_distances(s["settlements"])
        n_dynamic = sum(
            1 for y in range(H) for x in range(W)
            if s["grid"][y][x] not in (10, 5) and dist_grid[y][x] <= 6
        )
        complexities.append(n_dynamic)

    total_c = sum(complexities)
    allocations = [max(7, round(total_budget * c / total_c)) for c in complexities]
    while sum(allocations) > total_budget:
        idx = allocations.index(max(allocations))
        allocations[idx] -= 1
    while sum(allocations) < total_budget:
        idx = allocations.index(min(allocations))
        allocations[idx] += 1
    return allocations


def collect_observations(result, observations):
    """Parse simulation grid into observations dict."""
    grid_data = result.get("grid", [])
    vx = result.get("viewport_x", 0)
    vy = result.get("viewport_y", 0)
    for dy, row in enumerate(grid_data):
        for dx, cell_code in enumerate(row):
            cx, cy = vx + dx, vy + dy
            if 0 <= cx < W and 0 <= cy < H:
                cls = GRID_TO_CLASS.get(cell_code, 0)
                observations[(cx, cy)].append(cls)


def run_simulations(round_id, initial_states, allocations, vp_size, first_result=None, first_seed=0):
    """Run simulation queries. Use full-grid viewport if possible."""
    all_observations = []

    for seed_idx, (state, n_queries) in enumerate(zip(initial_states, allocations)):
        observations = defaultdict(list)

        # Count the first detection query if it was for this seed
        start_qi = 0
        if first_result is not None and seed_idx == first_seed:
            collect_observations(first_result, observations)
            start_qi = 1
            n_queries -= 1

        if vp_size >= 40:
            # Full-grid mode: just repeat (0,0) viewport
            for qi in range(n_queries):
                try:
                    result = api_post("/simulate", {
                        "round_id": round_id,
                        "seed_index": seed_idx,
                        "viewport_x": 0,
                        "viewport_y": 0,
                        "viewport_width": vp_size,
                        "viewport_height": vp_size,
                    })
                    collect_observations(result, observations)
                    if (qi + 1) % 10 == 0 or qi == n_queries - 1:
                        print(f"    Seed {seed_idx}: {start_qi + qi + 1}/{allocations[seed_idx]} done")
                except Exception as e:
                    print(f"    Q{qi+1} ERR: {e}")
        else:
            # Viewport mode: maximize coverage
            dist_grid = precompute_distances(state["settlements"])
            value = compute_dynamic_value(state["grid"], dist_grid)
            viewports = find_viewports(value, n_queries, vp_size)

            print(f"  Seed {seed_idx}: {n_queries} queries, {len(set(viewports))} unique")
            for qi, (vx, vy) in enumerate(viewports):
                try:
                    result = api_post("/simulate", {
                        "round_id": round_id,
                        "seed_index": seed_idx,
                        "viewport_x": vx,
                        "viewport_y": vy,
                        "viewport_width": vp_size,
                        "viewport_height": vp_size,
                    })
                    collect_observations(result, observations)
                    if (qi + 1) % 10 == 0 or qi == n_queries - 1:
                        print(f"    Seed {seed_idx}: {start_qi + qi + 1}/{allocations[seed_idx]} done")
                except Exception as e:
                    print(f"    Q{qi+1} ERR: {e}")

        all_observations.append(observations)
    return all_observations


def learn_round_priors(initial_states, all_observations):
    """Pool observations by (terrain, dist_bucket) → round-specific priors."""
    group_counts = defaultdict(lambda: [0] * NUM_CLASSES)
    group_totals = defaultdict(int)

    for state, observations in zip(initial_states, all_observations):
        grid = state["grid"]
        dist_grid = precompute_distances(state["settlements"])

        for (x, y), obs_list in observations.items():
            terrain = grid[y][x]
            if terrain in (10, 5):
                continue
            d = dist_grid[y][x]
            key = cell_key(terrain, d)
            for obs in obs_list:
                group_counts[key][obs] += 1
                group_totals[key] += 1

    round_priors = {}
    for key in group_counts:
        total = group_totals[key]
        if total >= 5:
            probs = [group_counts[key][c] / total for c in range(NUM_CLASSES)]
            round_priors[key] = floor_normalize(probs)

    print("  Learned priors:")
    print(f"  {'Key':<25} {'N':>6}  Empty  Settl  Port   Ruin   Forest Mount")
    for key in sorted(round_priors.keys()):
        n = group_totals[key]
        p = round_priors[key]
        print(f"  {str(key):<25} {n:>6}  {p[0]:.3f}  {p[1]:.3f}  {p[2]:.3f}  {p[3]:.3f}  {p[4]:.3f}  {p[5]:.3f}")

    return round_priors


def build_predictions(initial_states, all_observations, round_priors, full_grid_mode):
    """Build predictions.
    - full_grid_mode: per-cell Bayesian with pooled prior (many obs per cell)
    - viewport mode: pooled priors for most cells, per-cell only if 8+ obs
    """
    all_predictions = []

    for seed_idx, (state, observations) in enumerate(zip(initial_states, all_observations)):
        grid = state["grid"]
        settlements = state["settlements"]
        dist_grid = precompute_distances(settlements)
        coastal_grid = precompute_coastal(grid)

        predictions = [[[0.0] * NUM_CLASSES for _ in range(W)] for _ in range(H)]
        n_percell = 0
        n_pooled = 0

        for y in range(H):
            for x in range(W):
                terrain = grid[y][x]

                if terrain == 10:
                    predictions[y][x] = [0.98, 0.004, 0.004, 0.004, 0.004, 0.004]
                    continue
                elif terrain == 5:
                    predictions[y][x] = [0.004, 0.004, 0.004, 0.004, 0.004, 0.98]
                    continue

                d = dist_grid[y][x]
                key = cell_key(terrain, d)
                obs = observations.get((x, y), [])

                # Get group prior
                prior = round_priors.get(key)
                if prior is None:
                    prior = FALLBACK_PRIORS.get(key, [0.80, 0.05, 0.01, 0.01, 0.10, 0.03])
                    prior = floor_normalize(prior)

                min_obs = 3 if full_grid_mode else 8

                if len(obs) >= min_obs:
                    # Per-cell Bayesian with pooled round prior
                    counts = [0] * NUM_CLASSES
                    for o in obs:
                        counts[o] += 1
                    N = len(obs)
                    # Prior weight: use more prior for few observations, less for many
                    # With full grid: N~10, prior_weight=1 → 91% observation, 9% prior
                    # With full grid: N~50, prior_weight=1 → 98% observation, 2% prior
                    pw = 1.0
                    pred = [(counts[c] + pw * prior[c]) / (N + pw) for c in range(NUM_CLASSES)]
                    predictions[y][x] = floor_normalize(pred)
                    n_percell += 1
                else:
                    # Use pooled round prior
                    predictions[y][x] = prior[:]
                    n_pooled += 1

        all_predictions.append(predictions)
        n_obs = sum(1 for v in observations.values() if v)
        max_obs = max((len(v) for v in observations.values()), default=0)
        print(f"  Seed {seed_idx}: {n_obs} cells obs (max {max_obs}/cell), "
              f"{n_percell} per-cell, {n_pooled} pooled")

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
    print("=== Astar Island Solver v5 (Auto-detect + Adaptive) ===\n")

    # 1. Get active round
    print("[1] Fetching rounds...")
    rounds = api_get("/rounds")
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        print("No active round!")
        sys.exit(1)
    round_info = active[0]
    round_id = round_info["id"]
    print(f"  Round #{round_info['round_number']} (closes {round_info['closes_at']})")

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

    if remaining <= 0:
        print("\n  No queries left!")
        all_observations = [defaultdict(list) for _ in range(len(initial_states))]
        round_priors = {}
        full_grid_mode = False
    else:
        # 4. Detect maximum viewport size (costs 1 query)
        print(f"\n[4] Detecting max viewport size (1 query)...")
        vp_size, first_result = detect_max_viewport(round_id, 0)
        remaining -= 1
        full_grid_mode = (vp_size >= 40)
        print(f"  Using viewport: {vp_size}x{vp_size}" +
              (" (FULL GRID!)" if full_grid_mode else ""))

        # 5. Allocate and run queries
        print(f"\n[5] Allocating {remaining} queries...")
        allocations = allocate_queries(initial_states, remaining, vp_size)
        print(f"  Allocation: {allocations}")

        print(f"\n[6] Running simulations...")
        all_observations = run_simulations(
            round_id, initial_states, allocations, vp_size,
            first_result=first_result, first_seed=0
        )

        # 6. Learn round-specific priors
        print(f"\n[7] Learning round-specific priors...")
        round_priors = learn_round_priors(initial_states, all_observations)

    # 7. Build predictions
    print(f"\n[8] Building predictions...")
    all_predictions = build_predictions(
        initial_states, all_observations, round_priors, full_grid_mode
    )

    # 8. Submit
    print(f"\n[9] Submitting...")
    results = submit_predictions(round_id, all_predictions)

    # 9. Check results
    print(f"\n[10] Final check...")
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
