#!/usr/bin/env python3
"""Astar Island solver v13 — Data-calibrated 1-parameter model.

Key insight: ALL cell distributions are a linear function of one parameter:
the round's "settlement survival rate" S (measured from observations).
The linear coefficients are calibrated from ground truth of rounds 1-13.

Score formula: 100 * exp(-3 * weighted_KL)
FLOOR = 0.01 per class (official recommendation).
"""

import json
import math
import os
import sys
import requests
import urllib3
from collections import defaultdict

urllib3.disable_warnings()

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhOGMxN2M1OC1lYzg0LTQ0MjQtYjMxNy1iYjgzY2UxY2IwNTUiLCJlbWFpbCI6ImhlbnJpazE5OTAwQGdtYWlsLmNvbSIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzc0NjM2NDA2fQ.FmG-dX5M2v3PXBOfIneuWpouAwVnD-PU0cMwHdwsoAY"
BASE = "https://api.ainm.no/astar-island"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
CACHE_FILE = "obs_cache.json"

NC = 6
H, W = 40, 40
VP = 15
FLOOR = 0.01  # CRITICAL: official recommendation, prevents infinite KL
GRID_TO_CLASS = {11: 0, 0: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

# ── Linear model coefficients: prob = intercept + slope * S ──────────────
# Calibrated from ground truth of rounds 1-13 (13 rounds × 5 seeds = 65 data points)
# Format: category -> [(intercept, slope) for each of 6 classes]
LINEAR_MODEL = {
    "sett_inland":  [(0.6676, -0.6974), (0.0, 1.0), (0.0, 0.0), (0.0088, 0.0507), (0.3236, -0.3533), (0.0, 0.0)],
    "sett_coastal": [(0.6923, -0.6953), (-0.0066, 0.3244), (-0.0206, 0.6542), (0.0047, 0.0517), (0.3302, -0.3350), (0.0, 0.0)],
    "e_d1":         [(0.9481, -0.7785), (-0.0155, 0.7341), (0.0, 0.0), (0.0041, 0.0443), (0.0633, 0.0002), (0.0, 0.0)],
    "e_d1c":        [(0.9601, -0.7974), (-0.0105, 0.3439), (-0.0174, 0.4274), (0.0032, 0.0438), (0.0647, -0.0177), (0.0, 0.0)],
    "e_d2":         [(0.9771, -0.7251), (-0.0160, 0.6574), (0.0, 0.0), (0.0056, 0.0323), (0.0333, 0.0353), (0.0, 0.0)],
    "e_d2c":        [(0.9882, -0.7496), (-0.0079, 0.2918), (-0.0152, 0.4052), (0.0047, 0.0306), (0.0303, 0.0220), (0.0, 0.0)],
    "e_d3":         [(0.9459, -0.4115), (0.0208, 0.3395), (0.0019, 0.0210), (0.0048, 0.0246), (0.0266, 0.0264), (0.0, 0.0)],
    "e_d5":         [(0.9624, -0.2955), (0.0155, 0.2308), (0.0015, 0.0234), (0.0033, 0.0192), (0.0173, 0.0220), (0.0, 0.0)],
    "e_far":        [(0.9881, -0.1450), (0.0054, 0.1079), (0.0009, 0.0178), (0.0013, 0.0094), (0.0042, 0.0100), (0.0, 0.0)],
    "f_d1":         [(0.1359, 0.0204), (-0.0157, 0.7479), (-0.0035, 0.0407), (0.0043, 0.0467), (0.8791, -0.8557), (0.0, 0.0)],
    "f_d2":         [(0.0679, 0.0878), (-0.0155, 0.6528), (-0.0022, 0.0418), (0.0055, 0.0335), (0.9442, -0.8158), (0.0, 0.0)],
    "f_d3":         [(0.0529, 0.0679), (0.0214, 0.3463), (0.0014, 0.0213), (0.0049, 0.0255), (0.9194, -0.4609), (0.0, 0.0)],
    "f_d5":         [(0.0349, 0.0563), (0.0153, 0.2414), (0.0014, 0.0206), (0.0034, 0.0196), (0.9450, -0.3377), (0.0, 0.0)],
    "f_far":        [(0.0086, 0.0232), (0.0050, 0.1129), (0.0008, 0.0146), (0.0014, 0.0093), (0.9842, -0.1600), (0.0, 0.0)],
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
    """Floor + normalize probabilities."""
    p = [max(v, FLOOR) for v in probs]
    s = sum(p)
    return [v / s for v in p]


def tcat(code):
    if code == 5: return "m"
    if code == 4: return "f"
    if code in (1, 2, 3): return "s"
    return "e"


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


def is_coastal(x, y, grid):
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
            return True
    return False


def cell_category(x, y, grid, dg):
    """Map a cell to its linear model category."""
    t = grid[y][x]
    d = dg[y][x]
    c = is_coastal(x, y, grid)

    if t == 10:
        return "water"
    if t == 5:
        return "mountain"
    if t in (1, 2):
        return "sett_coastal" if c else "sett_inland"
    if t == 4:
        if d <= 1: return "f_d1"
        if d <= 2: return "f_d2"
        if d <= 3: return "f_d3"
        if d <= 5: return "f_d5"
        return "f_far"
    # Empty (0, 11)
    if d <= 1: return "e_d1c" if c else "e_d1"
    if d <= 2: return "e_d2c" if c else "e_d2"
    if d <= 3: return "e_d3"
    if d <= 5: return "e_d5"
    return "e_far"


def model_prior(category, survival_rate):
    """Compute prior distribution from linear model given settlement survival rate."""
    if category == "water":
        return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if category == "mountain":
        return [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    coeffs = LINEAR_MODEL.get(category)
    if coeffs is None:
        return [1.0 / NC] * NC

    S = max(0.0, min(1.0, survival_rate))
    probs = [coeffs[i][0] + coeffs[i][1] * S for i in range(NC)]
    return fnorm(probs)


# ── Viewport Placement ──────────────────────────────────────────────────

def place_viewports_greedy(grid, settlements, n_vps):
    """Greedy viewport placement maximizing coverage of high-value dynamic cells."""
    dg = dist_grid(settlements)

    # Value = scoring impact (entropy-weighted cells only)
    cell_value = {}
    for y in range(H):
        for x in range(W):
            if grid[y][x] in (10, 5):
                continue  # static, zero scoring weight
            d = dg[y][x]
            # Only dynamic cells matter for scoring
            if d == 0: cell_value[(x, y)] = 10.0   # settlement itself
            elif d == 1: cell_value[(x, y)] = 6.0   # high entropy zone
            elif d == 2: cell_value[(x, y)] = 4.0
            elif d == 3: cell_value[(x, y)] = 1.0
            elif d <= 5: cell_value[(x, y)] = 0.3
            # d>5 is essentially static, skip

    viewports = []
    covered = set()

    for _ in range(n_vps):
        best_score, best_pos = -1, (0, 0)
        for vy in range(0, H - VP + 1):
            for vx in range(0, W - VP + 1):
                score = 0
                for dy in range(VP):
                    for dx in range(VP):
                        pos = (vx + dx, vy + dy)
                        v = cell_value.get(pos, 0)
                        if pos not in covered:
                            score += v
                        else:
                            score += v * 0.05  # diminishing returns for overlap
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)

        viewports.append(best_pos)
        vx, vy = best_pos
        for dy in range(VP):
            for dx in range(VP):
                covered.add((vx + dx, vy + dy))

    return viewports


# ── Query Allocation ─────────────────────────────────────────────────────

def allocate_queries(states, total_budget):
    """Allocate queries to seeds proportional to settlement count."""
    n = len(states)
    counts = [len(s["settlements"]) for s in states]
    total = sum(counts)

    alloc = [max(6, round(total_budget * c / total)) for c in counts]
    while sum(alloc) > total_budget:
        idx = alloc.index(max(alloc))
        alloc[idx] -= 1
    while sum(alloc) < total_budget:
        ratios = [counts[i] / alloc[i] for i in range(n)]
        idx = ratios.index(max(ratios))
        alloc[idx] += 1
    return alloc


def plan_viewports(n_queries):
    """Decide viewports × queries. Maximize coverage (more VPs > more repeats)."""
    if n_queries <= 4: return n_queries, 1
    if n_queries <= 6: return 3, 2
    if n_queries <= 10: return 5, 2
    if n_queries <= 15: return 5, 3
    return min(7, n_queries // 2), 2


# ── Settlement Survival Estimation ───────────────────────────────────────

def estimate_survival_rate(all_grid_obs, states):
    """Estimate the round's settlement survival rate from observations.
    This is THE key parameter that drives all predictions."""

    # Method 1: Direct observation of settlement cells
    alive = 0
    total = 0
    for seed_idx in range(len(states)):
        grid_obs = all_grid_obs[seed_idx]
        settlements = states[seed_idx]["settlements"]
        for s in settlements:
            if (s["x"], s["y"]) in grid_obs:
                for o in grid_obs[(s["x"], s["y"])]:
                    if o in (1, 2):  # settlement or port
                        alive += 1
                    total += 1

    if total >= 10:
        direct = alive / total
        print(f"  Direct settlement observation: {alive}/{total} = {direct:.3f}")
    else:
        direct = None

    # Method 2: All d<=2 observations
    alive2 = 0
    total2 = 0
    for seed_idx in range(len(states)):
        grid_obs = all_grid_obs[seed_idx]
        grid = states[seed_idx]["grid"]
        dg = dist_grid(states[seed_idx]["settlements"])
        for (x, y), obs_list in grid_obs.items():
            d = dg[y][x]
            if d <= 2 and grid[y][x] not in (10, 5):
                for o in obs_list:
                    if o in (1, 2):
                        alive2 += 1
                    total2 += 1

    if total2 >= 20:
        indirect = alive2 / total2
        print(f"  D<=2 zone observation: {alive2}/{total2} = {indirect:.3f}")
    else:
        indirect = None

    # Combine: prefer direct if available, else indirect
    if direct is not None and total >= 20:
        S = direct
    elif indirect is not None:
        S = indirect * 1.1  # d<=2 slightly underestimates settlement survival
    else:
        S = 0.3  # fallback
        print(f"  WARNING: Not enough observations, using fallback S={S}")

    return S


# ── Per-Settlement Adjustment ────────────────────────────────────────────

def per_settlement_adjustment(grid_obs, settlements, grid, S_global):
    """Compute per-settlement survival deviation from global S."""
    sett_adj = {}
    for i, s in enumerate(settlements):
        sx, sy = s["x"], s["y"]
        alive = 0
        total = 0

        # Look at d<=2 neighborhood
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                d = abs(dx) + abs(dy)
                if d > 2:
                    continue
                nx, ny = sx + dx, sy + dy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                if (nx, ny) not in grid_obs:
                    continue
                w = 1.0 if d == 0 else (0.7 if d == 1 else 0.3)
                for o in grid_obs[(nx, ny)]:
                    if o in (1, 2):
                        alive += w
                    total += w

        if total >= 2.0:
            local_S = alive / total
            ratio = local_S / max(S_global, 0.01)
            sett_adj[i] = max(0.3, min(3.0, ratio))
        else:
            sett_adj[i] = 1.0  # no data, assume average

    return sett_adj


def nearest_sett_idx(settlements):
    ns = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            best_d = 999
            for i, s in enumerate(settlements):
                d = abs(x - s["x"]) + abs(y - s["y"])
                if d < best_d:
                    best_d = d
                    ns[y][x] = i
    return ns


# ── Prediction ───────────────────────────────────────────────────────────

def build_predictions(state, grid_obs, S_global, sett_adj):
    grid = state["grid"]
    settlements = state["settlements"]
    dg = dist_grid(settlements)
    ns = nearest_sett_idx(settlements)

    preds = [[[0.0] * NC for _ in range(W)] for _ in range(H)]
    stats = {"obs": 0, "model": 0, "spatial": 0}

    for y in range(H):
        for x in range(W):
            cat = cell_category(x, y, grid, dg)

            # Get model prior for this cell
            # Apply per-settlement adjustment for d<=3 cells
            d = dg[y][x]
            if d <= 3 and cat not in ("water", "mountain"):
                si = ns[y][x]
                adj = sett_adj.get(si, 1.0)
                # Adjust S locally
                S_local = min(1.0, max(0.0, S_global * adj))
                prior = model_prior(cat, S_local)
            else:
                prior = model_prior(cat, S_global)

            obs = grid_obs.get((x, y), [])

            if len(obs) >= 1:
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1

                # Bayesian: fewer prior pseudo-counts with more observations
                n_prior = max(0.3, 2.0 - len(obs) * 0.3)
                total = len(obs) + n_prior
                pred = [(obs_counts[c] + n_prior * prior[c]) / total for c in range(NC)]
                preds[y][x] = fnorm(pred)
                stats["obs"] += 1
            elif d <= 5 and grid_obs:
                # Spatial borrowing for unobserved dynamic cells
                pseudo, tw = spatial_borrow(x, y, grid_obs, grid, dg)
                if tw >= 1.0:
                    n_eff = min(tw * 0.4, 1.5)
                    norm_p = [pseudo[c] / tw for c in range(NC)]
                    n_prior = 2.0
                    pred = [(n_eff * norm_p[c] + n_prior * prior[c]) / (n_eff + n_prior)
                            for c in range(NC)]
                    preds[y][x] = fnorm(pred)
                    stats["spatial"] += 1
                else:
                    preds[y][x] = prior
                    stats["model"] += 1
            else:
                preds[y][x] = prior
                stats["model"] += 1

    return preds, stats


def spatial_borrow(x, y, grid_obs, grid, dg):
    """Borrow from nearby observed cells with same terrain type + distance."""
    tc = tcat(grid[y][x])
    d = dg[y][x]
    pseudo = [0.0] * NC
    tw = 0.0

    for r in range(1, 6):
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
                if abs(nd - d) > 2:
                    continue
                dist_val = abs(ddx) + abs(ddy)
                w = 1.0 / (1 + dist_val) ** 1.5
                if nd == d:
                    w *= 2.0
                elif abs(nd - d) == 1:
                    w *= 1.2
                for o in grid_obs[(nx, ny)]:
                    pseudo[o] += w
                    tw += w
    return pseudo, tw


# ── Cache ────────────────────────────────────────────────────────────────

def save_cache(round_id, all_grid_obs):
    data = {"round_id": round_id, "obs": []}
    for grid_obs in all_grid_obs:
        seed_data = {}
        for (x, y), obs_list in grid_obs.items():
            seed_data[f"{x},{y}"] = obs_list
        data["obs"].append(seed_data)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    total = sum(len(d) for d in data["obs"])
    print(f"  Cached {total} cells")


def load_cache(round_id):
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE) as f:
        data = json.load(f)
    if data.get("round_id") != round_id:
        return None
    all_grid_obs = []
    for seed_data in data["obs"]:
        grid_obs = defaultdict(list)
        for key, obs_list in seed_data.items():
            x, y = map(int, key.split(","))
            grid_obs[(x, y)] = obs_list
        all_grid_obs.append(grid_obs)
    total = sum(len(d) for d in all_grid_obs)
    print(f"  Loaded {total} cached cells")
    return all_grid_obs


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=== Astar Island Solver v13 ===")
    print("Score = 100 * exp(-3 * weighted_KL)\n")

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
    print(f"Budget: {remaining}/{budget['queries_max']}\n")

    rd = api_get(f"/rounds/{round_id}")
    states = rd["initial_states"]
    n_seeds = len(states)
    for i, s in enumerate(states):
        ports = sum(1 for ss in s["settlements"] if ss.get("has_port"))
        print(f"  Seed {i}: {len(s['settlements'])} settlements ({ports} ports)")

    # Load or gather observations
    cached = load_cache(round_id)

    if remaining > 0:
        alloc = allocate_queries(states, remaining)
        print(f"\nQuery allocation: {alloc}")

        all_grid_obs = cached if cached else [defaultdict(list) for _ in range(n_seeds)]

        for seed_idx in range(n_seeds):
            if alloc[seed_idx] == 0:
                continue
            state = states[seed_idx]
            n_q = alloc[seed_idx]
            n_vps, q_per = plan_viewports(n_q)
            vps = place_viewports_greedy(state["grid"], state["settlements"], n_vps)

            # Distribute queries
            queries = []
            for vi, vp in enumerate(vps):
                nq = q_per + (1 if vi < n_q - n_vps * q_per else 0)
                queries.extend([vp] * nq)
            queries = queries[:n_q]

            # Coverage stats
            sett_covered = set()
            for si, s in enumerate(state["settlements"]):
                for vx, vy in vps:
                    if vx <= s["x"] < vx + VP and vy <= s["y"] < vy + VP:
                        sett_covered.add(si)
                        break
            print(f"  Seed {seed_idx}: {n_q}q, {n_vps}vp, "
                  f"{len(sett_covered)}/{len(state['settlements'])} sett covered")

            grid_obs = all_grid_obs[seed_idx]
            for vx, vy in queries:
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

        save_cache(round_id, all_grid_obs)

    elif cached:
        print("\nUsing cached observations")
        all_grid_obs = cached
    else:
        print("\nERROR: No queries and no cache!")
        sys.exit(1)

    # ── Estimate settlement survival rate (THE key parameter) ──────────

    print("\nEstimating settlement survival rate...")
    S_global = estimate_survival_rate(all_grid_obs, states)
    print(f"  → S_global = {S_global:.3f}")
    print(f"  → Expected score range: {100 * math.exp(-3 * 0.05):.0f}-{100 * math.exp(-3 * 0.3):.0f}")

    # ── Per-settlement adjustments ─────────────────────────────────────

    print("\nComputing per-settlement adjustments...")
    all_sett_adj = []
    for seed_idx in range(n_seeds):
        adj = per_settlement_adjustment(
            all_grid_obs[seed_idx], states[seed_idx]["settlements"],
            states[seed_idx]["grid"], S_global
        )
        all_sett_adj.append(adj)
        vals = list(adj.values())
        n_adjusted = sum(1 for v in vals if abs(v - 1.0) > 0.01)
        print(f"  Seed {seed_idx}: {n_adjusted}/{len(vals)} adjusted, "
              f"range=[{min(vals):.2f}, {max(vals):.2f}]")

    # ── Build predictions ──────────────────────────────────────────────

    print("\nBuilding predictions...")
    all_preds = []
    for seed_idx in range(n_seeds):
        preds, stats = build_predictions(
            states[seed_idx], all_grid_obs[seed_idx],
            S_global, all_sett_adj[seed_idx]
        )
        all_preds.append(preds)
        print(f"  Seed {seed_idx}: {stats}")

    # ── Verify a sample prediction ─────────────────────────────────────

    # Check prediction for first settlement cell
    s0 = states[0]["settlements"][0]
    p = all_preds[0][s0["y"]][s0["x"]]
    print(f"\n  Sample (seed 0, settlement at {s0['x']},{s0['y']}):")
    print(f"    Pred: [{', '.join(f'{v:.3f}' for v in p)}]")
    print(f"    Model prior: [{', '.join(f'{v:.3f}' for v in model_prior('sett_inland', S_global))}]")

    # ── Submit ─────────────────────────────────────────────────────────

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

    # ── Results ────────────────────────────────────────────────────────

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
