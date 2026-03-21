#!/usr/bin/env python3
"""Astar Island solver v10 — Within-round cross-seed learning + calibrated priors."""

import json
import math
import sys
import requests
import urllib3
from collections import defaultdict

urllib3.disable_warnings()

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhOGMxN2M1OC1lYzg0LTQ0MjQtYjMxNy1iYjgzY2UxY2IwNTUiLCJlbWFpbCI6ImhlbnJpazE5OTAwQGdtYWlsLmNvbSIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzc0NjM2NDA2fQ.FmG-dX5M2v3PXBOfIneuWpouAwVnD-PU0cMwHdwsoAY"
BASE = "https://api.ainm.no/astar-island"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

NC = 6
H, W = 40, 40
VP = 15
FLOOR = 0.001
GRID_TO_CLASS = {11: 0, 0: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

# Fallback priors from aggregated rounds 1-12 (used when no observations available)
HIST_PRIORS = {
    ("s", 0): [0.450, 0.301, 0.011, 0.024, 0.213, 0.001],
    ("e", 1): [0.619, 0.284, 0.019, 0.024, 0.054, 0.001],
    ("e", 2): [0.829, 0.110, 0.009, 0.012, 0.040, 0.001],
    ("e", 3): [0.949, 0.022, 0.002, 0.003, 0.024, 0.001],
    ("f", 1): [0.122, 0.294, 0.019, 0.024, 0.542, 0.001],
    ("f", 2): [0.083, 0.110, 0.008, 0.012, 0.788, 0.001],
    ("f", 3): [0.050, 0.022, 0.002, 0.003, 0.923, 0.001],
}


def api_get(path):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()


def api_post(path, data):
    r = requests.post(f"{BASE}{path}", headers=HEADERS, json=data, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()


def fnorm(probs):
    p = [max(v, FLOOR) for v in probs]
    s = sum(p)
    return [v / s for v in p]


def tcat(code):
    if code == 5: return "m"
    if code == 4: return "f"
    if code in (1, 2, 3): return "s"
    return "e"


def is_coastal(x, y, grid):
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
            return True
    return False


def dist_grid(settlements):
    dg = [[999] * W for _ in range(H)]
    for s in settlements:
        sx, sy = s["x"], s["y"]
        for y in range(H):
            for x in range(W):
                d = abs(x - sx) + abs(y - sy)
                if d < dg[y][x]:
                    dg[y][x] = d
    return dg


def nearest_sett_grid(settlements):
    ns = [[None] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            best_d = 999
            for s in settlements:
                d = abs(x - s["x"]) + abs(y - s["y"])
                if d < best_d:
                    best_d = d
                    ns[y][x] = (s["x"], s["y"])
    return ns


def cat_key(x, y, grid, dg):
    terrain = grid[y][x]
    tc = tcat(terrain)
    if tc == "m" or terrain == 10:
        return (tc, 99)
    d = dg[y][x]
    if tc == "s":
        return ("s", 0)
    if d <= 1: return (tc, 1)
    if d <= 2: return (tc, 2)
    if d <= 3: return (tc, 3)
    return (tc, 99)


# ── Viewport Placement ──────────────────────────────────────────────────

def place_viewports(grid, settlements, n_vps):
    dg = dist_grid(settlements)
    value = [[0.0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if grid[y][x] in (10, 5):
                continue
            d = dg[y][x]
            if d == 0: value[y][x] = 5.0
            elif d == 1: value[y][x] = 4.0
            elif d == 2: value[y][x] = 3.0
            elif d == 3: value[y][x] = 0.5

    viewports = []
    covered = set()
    for _ in range(n_vps):
        best_score, best_pos = -1, (0, 0)
        for vy in range(0, H - VP + 1):
            for vx in range(0, W - VP + 1):
                score = 0
                for dy in range(VP):
                    for dx in range(VP):
                        cx, cy = vx + dx, vy + dy
                        if (cx, cy) not in covered:
                            score += value[cy][cx]
                        else:
                            score += value[cy][cx] * 0.1
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)
        viewports.append(best_pos)
        vx, vy = best_pos
        for dy in range(VP):
            for dx in range(VP):
                covered.add((vx + dx, vy + dy))
    return viewports


# ── Cross-seed Category Prior Learning ───────────────────────────────────

def learn_round_priors(all_grid_obs, states):
    cat_counts = defaultdict(lambda: [0] * NC)
    cat_totals = defaultdict(int)

    for seed_idx, grid_obs in enumerate(all_grid_obs):
        grid = states[seed_idx]["grid"]
        settlements = states[seed_idx]["settlements"]
        dg = dist_grid(settlements)

        for (x, y), obs_list in grid_obs.items():
            key = cat_key(x, y, grid, dg)
            for o in obs_list:
                cat_counts[key][o] += 1
                cat_totals[key] += 1

    learned = {}
    for key, counts in cat_counts.items():
        total = cat_totals[key]
        alpha = 0.5
        learned[key] = [(counts[c] + alpha) / (total + NC * alpha) for c in range(NC)]

    return learned


# ── Settlement Survival Calibration ──────────────────────────────────────

def calibrate_survival(all_grid_obs, states):
    """Compute per-seed survival calibration from observed settlement cells."""
    seed_cal = []
    # Also compute global survival rate
    global_alive = 0
    global_total = 0

    for seed_idx in range(len(states)):
        grid_obs = all_grid_obs[seed_idx]
        settlements = states[seed_idx]["settlements"]

        alive_sum = 0
        total_obs = 0

        for s in settlements:
            sx, sy = s["x"], s["y"]
            if (sx, sy) not in grid_obs:
                continue
            obs = grid_obs[(sx, sy)]
            alive = sum(1 for o in obs if o in (1, 2))
            alive_sum += alive
            total_obs += len(obs)

        if total_obs > 0:
            obs_rate = alive_sum / total_obs
        else:
            obs_rate = 0.3  # fallback

        seed_cal.append(obs_rate)
        global_alive += alive_sum
        global_total += total_obs

    global_rate = global_alive / global_total if global_total > 0 else 0.3
    return seed_cal, global_rate


# ── Prediction Building ──────────────────────────────────────────────────

def get_prior(x, y, grid, dg, ns_grid, seed_survival, learned_priors):
    terrain = grid[y][x]
    tc = tcat(terrain)

    if tc == "m":
        return [FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, 1.0]
    if terrain == 10:
        return [1.0, FLOOR, FLOOR, FLOOR, FLOOR, FLOOR]

    d = dg[y][x]
    key = cat_key(x, y, grid, dg)

    # Get base prior from learned round priors, fallback to historical
    if key in learned_priors:
        prior = list(learned_priors[key])
    elif key in HIST_PRIORS:
        prior = list(HIST_PRIORS[key])
    else:
        # Far from settlements: static
        if tc == "f":
            return fnorm([0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        else:
            return fnorm([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    # Personalize for settlement cells based on per-settlement features
    if d <= 2 and ns_grid[y][x] is not None:
        # We personalize using a simple scaling by the settlement's
        # local feature advantage vs average
        ns_pos = ns_grid[y][x]
        # We don't have per-settlement survival predictions anymore,
        # but we have the round survival rate, which is already baked
        # into the learned priors. So just use the learned priors directly.
        pass

    return fnorm(prior)


def build_predictions(state, grid_obs, learned_priors, seed_survival):
    grid = state["grid"]
    settlements = state["settlements"]
    dg = dist_grid(settlements)
    ns_grid = nearest_sett_grid(settlements)

    preds = [[[0.0] * NC for _ in range(W)] for _ in range(H)]
    stats = {"obs": 0, "prior": 0, "spatial": 0}

    for y in range(H):
        for x in range(W):
            obs = grid_obs.get((x, y), [])
            prior = get_prior(x, y, grid, dg, ns_grid, seed_survival, learned_priors)

            if len(obs) >= 1:
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1

                # Informed Bayesian: prior weight decreases with more observations
                n_prior = max(1.0, 4.0 - len(obs) * 0.3)
                total = len(obs) + n_prior
                pred = [(obs_counts[c] + n_prior * prior[c]) / total for c in range(NC)]
                preds[y][x] = fnorm(pred)
                stats["obs"] += 1
            else:
                # Unobserved: try spatial borrowing for dynamic cells
                if dg[y][x] <= 3 and grid_obs:
                    pseudo, tw = spatial_borrow(x, y, grid_obs, grid, dg)
                    if tw >= 2.0:
                        n_eff = min(tw * 0.4, 2.0)
                        norm_p = [pseudo[c] / tw for c in range(NC)]
                        n_prior = 3.0
                        pred = [(n_eff * norm_p[c] + n_prior * prior[c]) / (n_eff + n_prior) for c in range(NC)]
                        preds[y][x] = fnorm(pred)
                        stats["spatial"] += 1
                        continue

                preds[y][x] = prior  # already fnorm'd
                stats["prior"] += 1

    return preds, stats


def spatial_borrow(x, y, grid_obs, grid, dg):
    tc = tcat(grid[y][x])
    d = dg[y][x]
    pseudo = [0.0] * NC
    tw = 0.0

    for r in range(1, 4):
        for ddx in range(-r, r + 1):
            for ddy in range(-r, r + 1):
                if abs(ddx) + abs(ddy) != r:
                    continue
                nx, ny = x + ddx, y + ddy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                if (nx, ny) not in grid_obs:
                    continue
                if tcat(grid[ny][nx]) != tc:
                    continue
                nd = dg[ny][nx]
                if abs(nd - d) > 1:
                    continue
                dist_val = abs(ddx) + abs(ddy)
                w = 1.0 / (1 + dist_val)
                if nd == d:
                    w *= 1.5
                for o in grid_obs[(nx, ny)]:
                    pseudo[o] += w
                    tw += w
    return pseudo, tw


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=== Astar Island Solver v10 ===\n")

    rounds_list = api_get("/rounds")
    active = [r for r in rounds_list if r["status"] == "active"]
    if not active:
        print("No active round!")
        sys.exit(1)
    rinfo = active[0]
    round_id = rinfo["id"]
    print(f"Round #{rinfo['round_number']} (closes {rinfo['closes_at']})")

    budget = api_get("/budget")
    remaining = budget["queries_max"] - budget["queries_used"]
    print(f"Budget: {remaining}/{budget['queries_max']}")

    rd = api_get(f"/rounds/{round_id}")
    states = rd["initial_states"]
    n_seeds = len(states)
    for i, s in enumerate(states):
        print(f"  Seed {i}: {len(s['settlements'])} settlements")

    # Allocate queries
    alloc = [remaining // n_seeds] * n_seeds
    for i in range(remaining - sum(alloc)):
        alloc[i] += 1

    # Run simulations
    print(f"\nRunning {remaining} simulations...")
    all_grid_obs = []

    for seed_idx in range(n_seeds):
        state = states[seed_idx]
        n_q = alloc[seed_idx]
        n_vps = 2 if n_q >= 6 else 1
        vps = place_viewports(state["grid"], state["settlements"], n_vps)

        # Distribute queries across viewports
        queries = []
        if n_vps == 1:
            queries = [vps[0]] * n_q
        else:
            n1 = (n_q + 1) // 2
            queries = [vps[0]] * n1 + [vps[1]] * (n_q - n1)

        # Count coverage
        covered = 0
        for s in state["settlements"]:
            for vx, vy in vps:
                if vx <= s["x"] < vx + VP and vy <= s["y"] < vy + VP:
                    covered += 1
                    break
        print(f"  Seed {seed_idx}: {n_q}q, {n_vps}vp, {covered}/{len(state['settlements'])} sett covered")

        grid_obs = defaultdict(list)
        for qi, (vx, vy) in enumerate(queries):
            try:
                result = api_post("/simulate", {
                    "round_id": round_id,
                    "seed_index": seed_idx,
                    "viewport_x": vx, "viewport_y": vy,
                    "viewport_width": VP, "viewport_height": VP,
                })
                for dy, row in enumerate(result.get("grid", [])):
                    for dx, cell in enumerate(row):
                        cx, cy = vx + dx, vy + dy
                        if 0 <= cx < W and 0 <= cy < H:
                            grid_obs[(cx, cy)].append(GRID_TO_CLASS.get(cell, 0))
            except Exception as e:
                print(f"    ERR: {e}")

        print(f"    → {len(grid_obs)} cells, max {max((len(v) for v in grid_obs.values()), default=0)} obs")
        all_grid_obs.append(grid_obs)

    # Learn round-specific category priors from ALL observations
    print("\nLearning round priors from pooled observations...")
    learned_priors = learn_round_priors(all_grid_obs, states)
    for key in sorted(learned_priors.keys()):
        tc, dk = key
        p = learned_priors[key]
        print(f"  {tc}_d{dk}: [{', '.join(f'{v:.3f}' for v in p)}]")

    # Calibrate survival
    seed_survivals, global_surv = calibrate_survival(all_grid_obs, states)
    print(f"\nSurvival rates: per-seed={[f'{s:.3f}' for s in seed_survivals]}, global={global_surv:.3f}")

    # Build predictions
    print("\nBuilding predictions...")
    all_preds = []
    for seed_idx in range(n_seeds):
        preds, stats = build_predictions(
            states[seed_idx], all_grid_obs[seed_idx],
            learned_priors, seed_survivals[seed_idx]
        )
        all_preds.append(preds)
        print(f"  Seed {seed_idx}: {stats}")

    # Submit
    print("\nSubmitting...")
    for seed_idx, preds in enumerate(all_preds):
        try:
            result = api_post("/submit", {
                "round_id": round_id,
                "seed_index": seed_idx,
                "prediction": preds,
            })
            print(f"  Seed {seed_idx}: {result}")
        except requests.exceptions.HTTPError as e:
            print(f"  Seed {seed_idx} ERROR: {e}")
            try:
                print(f"    {e.response.text[:300]}")
            except Exception:
                pass

    # Check
    print("\nResults:")
    try:
        my_rounds = api_get("/my-rounds")
        for r in my_rounds:
            if r.get("id") == round_id:
                info = {k: v for k, v in r.items()
                        if k in ("round_number", "round_score", "seed_scores",
                                 "rank", "total_teams", "seeds_submitted", "queries_used")}
                print(f"  {json.dumps(info, indent=2)}")
                break
    except Exception as e:
        print(f"  {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
