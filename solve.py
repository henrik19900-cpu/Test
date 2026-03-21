#!/usr/bin/env python3
"""Astar Island solver v8 — Concentrated queries + Jeffreys prior + Spatial borrowing."""

import json
import math
import sys
import requests
import urllib3
from collections import defaultdict, Counter

urllib3.disable_warnings()

# ── Config ──────────────────────────────────────────────────────────────
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhOGMxN2M1OC1lYzg0LTQ0MjQtYjMxNy1iYjgzY2UxY2IwNTUiLCJlbWFpbCI6ImhlbnJpazE5OTAwQGdtYWlsLmNvbSIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzc0NjM2NDA2fQ.FmG-dX5M2v3PXBOfIneuWpouAwVnD-PU0cMwHdwsoAY"
BASE = "https://api.ainm.no/astar-island"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

NC = 6
H, W = 40, 40
VP = 15
FLOOR = 0.002
JEFFREYS_ALPHA = 0.5  # Jeffreys prior for Dirichlet

GRID_TO_CLASS = {11: 0, 0: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

# GT-calibrated priors from 11 rounds of ground truth analysis
CAL = {
    ("s", 0, False): [0.474, 0.272, 0.002, 0.024, 0.226, 0.002],
    ("s", 0, True):  [0.516, 0.073, 0.145, 0.018, 0.246, 0.002],
    ("e", 1, False): [0.740, 0.179, 0.002, 0.016, 0.060, 0.002],
    ("e", 1, True):  [0.822, 0.056, 0.068, 0.011, 0.041, 0.002],
    ("e", 2, False): [0.767, 0.167, 0.002, 0.016, 0.046, 0.002],
    ("e", 2, True):  [0.869, 0.044, 0.055, 0.008, 0.023, 0.002],
    ("e", 3, False): [0.797, 0.145, 0.002, 0.014, 0.040, 0.002],
    ("e", 3, True):  [0.901, 0.035, 0.039, 0.006, 0.017, 0.002],
    ("e", 4, False): [0.819, 0.129, 0.002, 0.012, 0.035, 0.002],
    ("e", 4, True):  [0.916, 0.029, 0.033, 0.005, 0.014, 0.002],
    ("e", 5, False): [0.870, 0.096, 0.002, 0.010, 0.021, 0.002],
    ("e", 5, True):  [0.947, 0.022, 0.018, 0.003, 0.008, 0.002],
    ("e", 6, False): [0.901, 0.075, 0.002, 0.007, 0.013, 0.002],
    ("e", 6, True):  [0.961, 0.017, 0.013, 0.002, 0.004, 0.002],
    ("e", 7, False): [0.933, 0.051, 0.002, 0.004, 0.008, 0.002],
    ("e", 7, True):  [0.972, 0.012, 0.009, 0.002, 0.003, 0.002],
    ("e", 8, False): [0.953, 0.036, 0.002, 0.003, 0.004, 0.002],
    ("e", 8, True):  [0.981, 0.008, 0.005, 0.002, 0.002, 0.002],
    ("e", 9, False): [0.972, 0.020, 0.002, 0.002, 0.002, 0.002],
    ("e", 9, True):  [0.987, 0.005, 0.002, 0.002, 0.002, 0.002],
    ("e", 10, False): [0.979, 0.013, 0.002, 0.002, 0.002, 0.002],
    ("e", 10, True):  [0.989, 0.003, 0.002, 0.002, 0.002, 0.002],
    ("e", 99, False): [0.987, 0.005, 0.002, 0.002, 0.002, 0.002],
    ("e", 99, True):  [0.990, 0.002, 0.002, 0.002, 0.002, 0.002],
    ("f", 1, False): [0.133, 0.183, 0.002, 0.017, 0.662, 0.002],
    ("f", 1, True):  [0.126, 0.086, 0.108, 0.016, 0.662, 0.002],
    ("f", 2, False): [0.101, 0.174, 0.002, 0.016, 0.704, 0.002],
    ("f", 2, True):  [0.084, 0.076, 0.095, 0.014, 0.729, 0.002],
    ("f", 3, False): [0.085, 0.146, 0.002, 0.015, 0.750, 0.002],
    ("f", 3, True):  [0.067, 0.071, 0.078, 0.012, 0.770, 0.002],
    ("f", 4, False): [0.077, 0.135, 0.002, 0.013, 0.770, 0.002],
    ("f", 4, True):  [0.062, 0.057, 0.064, 0.010, 0.805, 0.002],
    ("f", 5, False): [0.048, 0.103, 0.002, 0.010, 0.836, 0.002],
    ("f", 5, True):  [0.040, 0.051, 0.044, 0.007, 0.856, 0.002],
    ("f", 6, False): [0.027, 0.077, 0.002, 0.008, 0.885, 0.002],
    ("f", 6, True):  [0.022, 0.040, 0.031, 0.005, 0.900, 0.002],
    ("f", 7, False): [0.019, 0.056, 0.002, 0.005, 0.917, 0.002],
    ("f", 7, True):  [0.018, 0.034, 0.026, 0.004, 0.916, 0.002],
    ("f", 8, False): [0.012, 0.041, 0.002, 0.003, 0.940, 0.002],
    ("f", 8, True):  [0.015, 0.025, 0.016, 0.003, 0.940, 0.002],
    ("f", 9, False): [0.006, 0.028, 0.002, 0.003, 0.960, 0.002],
    ("f", 9, True):  [0.006, 0.013, 0.007, 0.002, 0.971, 0.002],
    ("f", 10, False): [0.002, 0.013, 0.002, 0.002, 0.979, 0.002],
    ("f", 10, True):  [0.003, 0.011, 0.005, 0.002, 0.977, 0.002],
    ("f", 99, False): [0.002, 0.003, 0.002, 0.002, 0.989, 0.002],
    ("f", 99, True):  [0.002, 0.005, 0.002, 0.002, 0.987, 0.002],
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
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        nx, ny = x+dx, y+dy
        if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
            return True
    return False


def dist_grid(settlements):
    dg = [[999]*W for _ in range(H)]
    for s in settlements:
        sx, sy = s["x"], s["y"]
        for y in range(H):
            for x in range(W):
                d = abs(x-sx)+abs(y-sy)
                if d < dg[y][x]:
                    dg[y][x] = d
    return dg


def get_cal_prior(tc, d, coastal):
    if tc == "m":
        return fnorm([0, 0, 0, 0, 0, 1])
    dk = min(d, 10) if d <= 10 else 99
    key = (tc, dk, coastal)
    if key in CAL:
        return fnorm(CAL[key])
    key2 = (tc, dk, not coastal)
    if key2 in CAL:
        return fnorm(CAL[key2])
    key3 = (tc, 99, coastal)
    if key3 in CAL:
        return fnorm(CAL[key3])
    if tc == "f":
        return fnorm([0.01, 0.01, 0.005, 0.005, 0.97, 0.005])
    return fnorm([0.97, 0.01, 0.005, 0.005, 0.005, 0.005])


def best_viewport(settlements):
    """Find the single best viewport covering the most dynamic area."""
    if not settlements:
        return (12, 12)

    best_score, best_pos = -1, (0, 0)
    for vy in range(0, H-VP+1):
        for vx in range(0, W-VP+1):
            score = 0
            for s in settlements:
                sx, sy = s["x"], s["y"]
                if vx <= sx < vx+VP and vy <= sy < vy+VP:
                    # Settlement in viewport - high value
                    score += 10
                    # Bonus for cells near settlement also in viewport
                    for r in range(1, 5):
                        for ddx in range(-r, r+1):
                            for ddy in range(-r, r+1):
                                if abs(ddx)+abs(ddy) == r:
                                    nx, ny = sx+ddx, sy+ddy
                                    if vx <= nx < vx+VP and vy <= ny < vy+VP:
                                        score += 0.3
            if score > best_score:
                best_score = score
                best_pos = (vx, vy)
    return best_pos


def second_viewport(settlements, first_vp):
    """Find second viewport covering settlements NOT in first viewport."""
    fvx, fvy = first_vp
    uncovered = [s for s in settlements
                 if not (fvx <= s["x"] < fvx+VP and fvy <= s["y"] < fvy+VP)]

    if not uncovered:
        return first_vp  # All covered, just repeat first

    best_score, best_pos = -1, first_vp
    for vy in range(0, H-VP+1):
        for vx in range(0, W-VP+1):
            score = 0
            for s in uncovered:
                sx, sy = s["x"], s["y"]
                if vx <= sx < vx+VP and vy <= sy < vy+VP:
                    score += 10
                    for r in range(1, 5):
                        for ddx in range(-r, r+1):
                            for ddy in range(-r, r+1):
                                if abs(ddx)+abs(ddy) == r:
                                    nx, ny = sx+ddx, sy+ddy
                                    if vx <= nx < vx+VP and vy <= ny < vy+VP:
                                        score += 0.3
            if score > best_score:
                best_score = score
                best_pos = (vx, vy)
    return best_pos


def jeffreys_posterior(obs_counts, n_obs):
    """Dirichlet posterior with Jeffreys prior (alpha=0.5)."""
    alpha = JEFFREYS_ALPHA
    total = n_obs + NC * alpha
    return [(obs_counts[c] + alpha) / total for c in range(NC)]


def spatial_borrow(x, y, grid_obs, grid, dg, max_radius=3):
    """Borrow observations from nearby observed cells with similar features."""
    tc = tcat(grid[y][x])
    d = dg[y][x]
    coastal = is_coastal(x, y, grid)

    pseudo_counts = [0.0] * NC
    total_weight = 0.0

    for r in range(1, max_radius + 1):
        for ddx in range(-r, r + 1):
            for ddy in range(-r, r + 1):
                if abs(ddx) + abs(ddy) != r:
                    continue
                nx, ny = x + ddx, y + ddy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                if (nx, ny) not in grid_obs:
                    continue

                # Check feature similarity
                n_tc = tcat(grid[ny][nx])
                n_d = dg[ny][nx]
                n_coastal = is_coastal(nx, ny, grid)

                # Same terrain type and similar distance
                if n_tc != tc:
                    continue
                if abs(n_d - d) > 2:
                    continue

                # Weight by distance and feature match
                dist = abs(ddx) + abs(ddy)
                w = 1.0 / (1 + dist)
                if n_coastal == coastal:
                    w *= 1.5
                if abs(n_d - d) == 0:
                    w *= 1.5

                for o in grid_obs[(nx, ny)]:
                    pseudo_counts[o] += w
                    total_weight += w

    if total_weight < 1.0:
        return None

    return pseudo_counts, total_weight


def main():
    print("=== Astar Island Solver v8 (Concentrated + Jeffreys + Spatial) ===\n")

    # 1. Active round
    print("[1] Fetching rounds...")
    rounds_list = api_get("/rounds")
    active = [r for r in rounds_list if r["status"] == "active"]
    if not active:
        print("No active round!")
        sys.exit(1)
    rinfo = active[0]
    round_id = rinfo["id"]
    print(f"  Round #{rinfo['round_number']} (closes {rinfo['closes_at']})")

    # 2. Budget
    print("\n[2] Checking budget...")
    budget = api_get("/budget")
    used = budget["queries_used"]
    total_q = budget["queries_max"]
    remaining = total_q - used
    print(f"  {remaining}/{total_q} queries remaining ({used} used)")

    # 3. Initial states
    print("\n[3] Fetching initial states...")
    rd = api_get(f"/rounds/{round_id}")
    states = rd["initial_states"]
    n_seeds = len(states)
    for i, s in enumerate(states):
        n_s = len(s["settlements"])
        n_p = sum(1 for st in s["settlements"] if st["has_port"])
        print(f"  Seed {i}: {n_s} settlements ({n_p} ports)")

    if remaining <= 0:
        print("\n  No queries left!")
        all_preds = build_prior_only_predictions(states)
        submit(round_id, all_preds)
        return

    # 4. Allocate queries — concentrate on fewer viewports
    print(f"\n[4] Allocating {remaining} queries...")
    base = remaining // n_seeds
    alloc = [base] * n_seeds
    for i in range(remaining - sum(alloc)):
        alloc[i] += 1
    print(f"  Allocation: {alloc}")

    # 5. Run simulations — CONCENTRATED viewports for max observations per cell
    print(f"\n[5] Running simulations (concentrated strategy)...")
    all_grid_obs = []
    all_sett_stats = []

    for seed_idx in range(n_seeds):
        state = states[seed_idx]
        settlements = state["settlements"]
        n_q = alloc[seed_idx]

        # Phase 1: Scout with 1 query to find best viewport
        vp1 = best_viewport(settlements)
        vp2 = second_viewport(settlements, vp1)

        # Check how many settlements are uncovered by vp1
        covered_by_vp1 = sum(1 for s in settlements
                            if vp1[0] <= s["x"] < vp1[0]+VP and vp1[1] <= s["y"] < vp1[1]+VP)
        total_setts = len(settlements)
        uncovered = total_setts - covered_by_vp1

        # Strategy: concentrate most queries on best viewport
        # Only use second viewport if many settlements are uncovered
        if uncovered >= 2 and n_q >= 4:
            # Split: 70% on vp1, 30% on vp2
            n_vp1 = max(n_q * 7 // 10, 2)
            n_vp2 = n_q - n_vp1
            queries = [(vp1)] * n_vp1 + [(vp2)] * n_vp2
        else:
            # All queries on single viewport
            queries = [vp1] * n_q

        n_unique = len(set(queries))
        print(f"  Seed {seed_idx}: {n_q} queries on {n_unique} viewport(s), "
              f"covering {covered_by_vp1}/{total_setts} settlements in primary")

        grid_obs = defaultdict(list)
        sett_snapshots = []

        for qi, (vx, vy) in enumerate(queries):
            try:
                result = api_post("/simulate", {
                    "round_id": round_id,
                    "seed_index": seed_idx,
                    "viewport_x": vx, "viewport_y": vy,
                    "viewport_width": VP, "viewport_height": VP,
                })

                grid_data = result.get("grid", [])
                for dy, row in enumerate(grid_data):
                    for dx, cell in enumerate(row):
                        cx, cy = vx+dx, vy+dy
                        if 0 <= cx < W and 0 <= cy < H:
                            grid_obs[(cx, cy)].append(GRID_TO_CLASS.get(cell, 0))

                sett_snapshots.append(result.get("settlements", []))

            except Exception as e:
                print(f"    Q{qi+1} ERR: {e}")

        n_cells = sum(1 for v in grid_obs.values() if v)
        max_o = max((len(v) for v in grid_obs.values()), default=0)
        print(f"    → {n_cells} cells, max {max_o} obs/cell, {len(sett_snapshots)} snapshots")

        all_grid_obs.append(grid_obs)
        all_sett_stats.append(sett_snapshots)

    # 6. Analyze settlement stats
    print(f"\n[6] Analyzing settlement stats...")
    all_sett_analysis = []

    for seed_idx in range(n_seeds):
        settlements = states[seed_idx]["settlements"]
        snapshots = all_sett_stats[seed_idx]
        n_snaps = len(snapshots)

        sett_analysis = {}
        for s in settlements:
            sx, sy = s["x"], s["y"]
            alive_count = 0
            port_count = 0
            pops = []
            owners = []

            for snap in snapshots:
                found = None
                for ss in snap:
                    if ss["x"] == sx and ss["y"] == sy:
                        found = ss
                        break

                if found and found.get("alive", True):
                    alive_count += 1
                    if found.get("has_port"):
                        port_count += 1
                    pops.append(found.get("population", 0))
                    owners.append(found.get("owner_id", -1))

            survival_rate = alive_count / n_snaps if n_snaps > 0 else 0.5
            port_rate = port_count / alive_count if alive_count > 0 else 0

            sett_analysis[(sx, sy)] = {
                "survival": survival_rate,
                "port_rate": port_rate,
                "alive_count": alive_count,
                "n_snaps": n_snaps,
                "has_port_initial": s.get("has_port", False),
            }

        all_sett_analysis.append(sett_analysis)

        alive_rates = [a["survival"] for a in sett_analysis.values()]
        if alive_rates:
            print(f"  Seed {seed_idx}: {len(settlements)} settlements, "
                  f"avg survival={sum(alive_rates)/len(alive_rates):.2f}")

    # 7. Build predictions using Jeffreys posterior + spatial borrowing
    print(f"\n[7] Building predictions...")
    all_preds = []

    for seed_idx in range(n_seeds):
        grid = states[seed_idx]["grid"]
        settlements = states[seed_idx]["settlements"]
        dg = dist_grid(settlements)
        grid_obs = all_grid_obs[seed_idx]
        sett_analysis = all_sett_analysis[seed_idx]

        preds = [[[0.0]*NC for _ in range(W)] for _ in range(H)]
        n_jeffreys = 0
        n_spatial = 0
        n_sett_pred = 0
        n_prior = 0

        for y in range(H):
            for x in range(W):
                terrain = grid[y][x]
                tc = tcat(terrain)

                # Mountain: always static
                if tc == "m":
                    preds[y][x] = fnorm([0, 0, 0, 0, 0, 1])
                    continue

                d = dg[y][x]
                dk = min(d, 10) if d <= 10 else 99
                coastal = is_coastal(x, y, grid)

                obs = grid_obs.get((x, y), [])
                n_obs = len(obs)

                # Settlement cell: use settlement stats + observations
                if (x, y) in sett_analysis:
                    sa = sett_analysis[(x, y)]
                    surv = sa["survival"]
                    pr = sa["port_rate"]

                    # Settlement-based prior
                    p_empty = (1 - surv) * 0.60
                    p_sett = surv * (1 - pr)
                    p_port = surv * pr
                    p_ruin = (1 - surv) * 0.10
                    p_forest = (1 - surv) * 0.30
                    p_mount = 0.0
                    sett_prior = [p_empty, p_sett, p_port, p_ruin, p_forest, p_mount]

                    if n_obs >= 3:
                        # Enough observations: use Jeffreys posterior
                        obs_counts = [0]*NC
                        for o in obs: obs_counts[o] += 1
                        pred = jeffreys_posterior(obs_counts, n_obs)
                    elif n_obs >= 1:
                        # Few observations: light Bayesian with settlement prior
                        obs_counts = [0]*NC
                        for o in obs: obs_counts[o] += 1
                        pw = 1.5
                        pred = [(obs_counts[c] + pw*sett_prior[c]) / (n_obs + pw) for c in range(NC)]
                    else:
                        pred = sett_prior

                    preds[y][x] = fnorm(pred)
                    n_sett_pred += 1
                    continue

                # Non-settlement cells with observations
                if n_obs >= 3:
                    # Enough observations: use pure Jeffreys posterior
                    obs_counts = [0]*NC
                    for o in obs: obs_counts[o] += 1
                    preds[y][x] = fnorm(jeffreys_posterior(obs_counts, n_obs))
                    n_jeffreys += 1
                elif n_obs >= 1:
                    # Few observations: light Bayesian blend with calibrated prior
                    obs_counts = [0]*NC
                    for o in obs: obs_counts[o] += 1
                    prior = get_cal_prior(tc, d, coastal)

                    # Adjust prior based on nearest settlement health
                    if d <= 4:
                        best_sa = None
                        best_d = 999
                        for (sx, sy), sa in sett_analysis.items():
                            dd = abs(x-sx) + abs(y-sy)
                            if dd < best_d:
                                best_d = dd
                                best_sa = sa
                        if best_sa:
                            surv = best_sa["survival"]
                            surv_ratio = max(0.3, min(2.0, surv / 0.55))
                            adjusted = prior[:]
                            adjusted[1] *= surv_ratio
                            adjusted[2] *= surv_ratio
                            excess = (adjusted[1] - prior[1]) + (adjusted[2] - prior[2])
                            adjusted[0] = max(FLOOR, adjusted[0] - excess)
                            prior = fnorm(adjusted)

                    # Light prior weight — let data dominate more
                    pw = 1.5
                    pred = [(obs_counts[c] + pw*prior[c]) / (n_obs + pw) for c in range(NC)]
                    preds[y][x] = fnorm(pred)
                    n_jeffreys += 1
                else:
                    # No direct observations — try spatial borrowing
                    borrowed = spatial_borrow(x, y, grid_obs, grid, dg)
                    if borrowed is not None:
                        pseudo_counts, total_w = borrowed
                        # Use borrowed observations with Jeffreys-like posterior
                        # But scale down: borrowed data is weaker than direct
                        effective_n = min(total_w, 3.0)  # Cap effective observations
                        prior = get_cal_prior(tc, d, coastal)

                        # Adjust prior for settlement health
                        if d <= 4:
                            best_sa = None
                            best_d = 999
                            for (sx, sy), sa in sett_analysis.items():
                                dd = abs(x-sx) + abs(y-sy)
                                if dd < best_d:
                                    best_d = dd
                                    best_sa = sa
                            if best_sa:
                                surv = best_sa["survival"]
                                surv_ratio = max(0.3, min(2.0, surv / 0.55))
                                adjusted = prior[:]
                                adjusted[1] *= surv_ratio
                                adjusted[2] *= surv_ratio
                                excess = (adjusted[1] - prior[1]) + (adjusted[2] - prior[2])
                                adjusted[0] = max(FLOOR, adjusted[0] - excess)
                                prior = fnorm(adjusted)

                        # Blend borrowed observations with prior
                        pw = 2.0
                        norm_pseudo = [pseudo_counts[c] / total_w for c in range(NC)] if total_w > 0 else [1.0/NC]*NC
                        pred = [(effective_n * norm_pseudo[c] + pw * prior[c]) / (effective_n + pw) for c in range(NC)]
                        preds[y][x] = fnorm(pred)
                        n_spatial += 1
                    else:
                        # Pure prior
                        prior = get_cal_prior(tc, d, coastal)

                        # Adjust for settlement health
                        if d <= 4:
                            best_sa = None
                            best_d = 999
                            for (sx, sy), sa in sett_analysis.items():
                                dd = abs(x-sx) + abs(y-sy)
                                if dd < best_d:
                                    best_d = dd
                                    best_sa = sa
                            if best_sa:
                                surv = best_sa["survival"]
                                surv_ratio = max(0.3, min(2.0, surv / 0.55))
                                adjusted = prior[:]
                                adjusted[1] *= surv_ratio
                                adjusted[2] *= surv_ratio
                                excess = (adjusted[1] - prior[1]) + (adjusted[2] - prior[2])
                                adjusted[0] = max(FLOOR, adjusted[0] - excess)
                                prior = fnorm(adjusted)

                        preds[y][x] = prior[:]
                        n_prior += 1

        all_preds.append(preds)
        print(f"  Seed {seed_idx}: {n_sett_pred} settlement, {n_jeffreys} Jeffreys, "
              f"{n_spatial} spatial, {n_prior} prior-only")

    # 8. Submit
    print(f"\n[8] Submitting...")
    submit(round_id, all_preds)

    # 9. Check results
    print(f"\n[9] Final check...")
    try:
        my_rounds = api_get("/my-rounds")
        for r in my_rounds:
            if r.get("id") == round_id:
                info = {k: v for k, v in r.items()
                        if k in ("round_number", "round_score", "seed_scores",
                                 "rank", "total_teams", "seeds_submitted",
                                 "queries_used")}
                print(f"  {json.dumps(info, indent=2)}")
                break
    except Exception as e:
        print(f"  {e}")

    print("\nDone!")


def build_prior_only_predictions(states):
    """Predictions using only calibrated priors (no queries)."""
    all_preds = []
    for state in states:
        grid = state["grid"]
        settlements = state["settlements"]
        dg = dist_grid(settlements)
        preds = [[[0.0]*NC for _ in range(W)] for _ in range(H)]
        for y in range(H):
            for x in range(W):
                tc = tcat(grid[y][x])
                if tc == "m":
                    preds[y][x] = fnorm([0, 0, 0, 0, 0, 1])
                else:
                    d = dg[y][x]
                    coastal = is_coastal(x, y, grid)
                    preds[y][x] = get_cal_prior(tc, d, coastal)
        all_preds.append(preds)
    return all_preds


def submit(round_id, all_preds):
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


if __name__ == "__main__":
    main()
