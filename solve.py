#!/usr/bin/env python3
"""Astar Island solver v11 — Full pipeline with caching + per-settlement personalization."""

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
FLOOR = 0.001
GRID_TO_CLASS = {11: 0, 0: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


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
    """Returns grid where each cell maps to index of nearest settlement."""
    ns = [[None] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            best_d = 999
            for i, s in enumerate(settlements):
                d = abs(x - s["x"]) + abs(y - s["y"])
                if d < best_d:
                    best_d = d
                    ns[y][x] = i
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


# ── Per-Settlement Survival Estimation ────────────────────────────────────

def estimate_settlement_survival(grid_obs, settlements, grid):
    """Estimate per-settlement survival from nearby observations."""
    sett_surv = {}
    for i, s in enumerate(settlements):
        sx, sy = s["x"], s["y"]
        alive_count = 0
        total_count = 0
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                nx, ny = sx + dx, sy + dy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                if (nx, ny) not in grid_obs:
                    continue
                d = abs(dx) + abs(dy)
                w = 1.0 if d == 0 else (0.7 if d == 1 else 0.3)
                for o in grid_obs[(nx, ny)]:
                    if o in (1, 2):
                        alive_count += w
                    total_count += w
        sett_surv[i] = alive_count / total_count if total_count > 0 else None
    return sett_surv


def settlement_features(settlements, grid):
    """Compute features that predict settlement survival."""
    features = {}
    for i, s in enumerate(settlements):
        sx, sy = s["x"], s["y"]
        forest_count = 0
        near_sett = 0
        coastal = 0
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                nx, ny = sx + dx, sy + dy
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                if abs(dx) + abs(dy) > 3:
                    continue
                t = grid[ny][nx]
                if t == 4:
                    forest_count += 1
                elif t in (1, 2, 3) and (dx != 0 or dy != 0):
                    near_sett += 1
        for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = sx + ddx, sy + ddy
            if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
                coastal = 1
                break
        features[i] = {"forest": forest_count, "near_sett": near_sett, "coastal": coastal}
    return features


def predict_settlement_survival(sett_surv, sett_feats, global_surv):
    """Predict survival for unobserved settlements using feature correlation."""
    observed = [(i, sett_surv[i], sett_feats[i])
                for i in sett_surv if sett_surv[i] is not None]

    if len(observed) < 3:
        return {i: (sett_surv[i] if sett_surv[i] is not None else global_surv)
                for i in sett_surv}

    mean_surv = sum(s for _, s, _ in observed) / len(observed)
    mean_forest = sum(f["forest"] for _, _, f in observed) / len(observed)
    mean_near = sum(f["near_sett"] for _, _, f in observed) / len(observed)

    # Simple linear feature-survival correlations
    corr_f = corr_n = 0
    var_f = var_n = 0
    for _, surv, feat in observed:
        df = feat["forest"] - mean_forest
        dn = feat["near_sett"] - mean_near
        ds = surv - mean_surv
        corr_f += df * ds
        corr_n += dn * ds
        var_f += df * df
        var_n += dn * dn

    beta_f = corr_f / var_f if var_f > 0 else 0
    beta_n = corr_n / var_n if var_n > 0 else 0
    # Clip betas to prevent extreme predictions
    beta_f = max(-0.05, min(0.05, beta_f))
    beta_n = max(-0.05, min(0.05, beta_n))

    predicted = {}
    for i in sett_surv:
        if sett_surv[i] is not None:
            predicted[i] = sett_surv[i]
        else:
            feat = sett_feats[i]
            adj = beta_f * (feat["forest"] - mean_forest) + beta_n * (feat["near_sett"] - mean_near)
            predicted[i] = max(0.05, min(0.95, mean_surv + adj))
    return predicted


# ── Prediction Building ──────────────────────────────────────────────────

def get_prior(x, y, grid, dg, ns_grid, sett_pred_surv, learned_priors, global_surv):
    terrain = grid[y][x]
    tc = tcat(terrain)

    if tc == "m":
        return [FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, 1.0]
    if terrain == 10:
        return [1.0, FLOOR, FLOOR, FLOOR, FLOOR, FLOOR]

    key = cat_key(x, y, grid, dg)
    d = dg[y][x]

    if key in learned_priors:
        prior = list(learned_priors[key])
    else:
        if tc == "f":
            return fnorm([0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        else:
            return fnorm([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    # Per-settlement personalization for cells near settlements
    if d <= 2 and ns_grid[y][x] is not None:
        sett_idx = ns_grid[y][x]
        if sett_idx in sett_pred_surv and global_surv > 0.01:
            local_surv = sett_pred_surv[sett_idx]
            ratio = local_surv / global_surv
            ratio = max(0.3, min(3.0, ratio))
            # Scale settlement classes by ratio
            prior[1] *= ratio
            prior[2] *= ratio
            if ratio > 1:
                prior[0] *= (1.0 / ratio) ** 0.5
            else:
                prior[0] *= (1.0 / ratio) ** 0.3

    return fnorm(prior)


def build_predictions(state, grid_obs, learned_priors, sett_pred_surv, global_surv):
    grid = state["grid"]
    settlements = state["settlements"]
    dg = dist_grid(settlements)
    ns_grid = nearest_sett_grid(settlements)

    preds = [[[0.0] * NC for _ in range(W)] for _ in range(H)]
    stats = {"obs": 0, "prior": 0, "spatial": 0}

    for y in range(H):
        for x in range(W):
            obs = grid_obs.get((x, y), [])
            prior = get_prior(x, y, grid, dg, ns_grid, sett_pred_surv, learned_priors, global_surv)

            if len(obs) >= 1:
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1

                # Bayesian with adaptive prior strength
                n_prior = max(0.5, 3.0 - len(obs) * 0.4)
                total = len(obs) + n_prior
                pred = [(obs_counts[c] + n_prior * prior[c]) / total for c in range(NC)]
                preds[y][x] = fnorm(pred)
                stats["obs"] += 1
            else:
                if dg[y][x] <= 4 and grid_obs:
                    pseudo, tw = spatial_borrow(x, y, grid_obs, grid, dg)
                    if tw >= 1.5:
                        n_eff = min(tw * 0.5, 2.5)
                        norm_p = [pseudo[c] / tw for c in range(NC)]
                        n_prior = 2.5
                        pred = [(n_eff * norm_p[c] + n_prior * prior[c]) / (n_eff + n_prior)
                                for c in range(NC)]
                        preds[y][x] = fnorm(pred)
                        stats["spatial"] += 1
                        continue
                preds[y][x] = prior
                stats["prior"] += 1

    return preds, stats


def spatial_borrow(x, y, grid_obs, grid, dg):
    tc = tcat(grid[y][x])
    d = dg[y][x]
    pseudo = [0.0] * NC
    tw = 0.0

    for r in range(1, 5):
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
    print(f"  Cached {sum(len(d) for d in data['obs'])} cells to {CACHE_FILE}")


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
    print(f"  Loaded {sum(len(d) for d in all_grid_obs)} cached cells")
    return all_grid_obs


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=== Astar Island Solver v11 ===\n")

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

    # Try cache first
    cached = load_cache(round_id)

    if remaining > 0:
        # Fresh observations
        alloc = [remaining // n_seeds] * n_seeds
        for i in range(remaining - sum(alloc)):
            alloc[i] += 1

        # Merge with cache if available
        all_grid_obs = cached if cached else [defaultdict(list) for _ in range(n_seeds)]

        print(f"\nRunning {remaining} simulations...")
        for seed_idx in range(n_seeds):
            if alloc[seed_idx] == 0:
                continue
            state = states[seed_idx]
            n_q = alloc[seed_idx]
            n_vps = min(3, max(1, n_q // 3))
            vps = place_viewports(state["grid"], state["settlements"], n_vps)

            queries = []
            for vi, vp in enumerate(vps):
                n_for_vp = n_q // n_vps + (1 if vi < n_q % n_vps else 0)
                queries.extend([vp] * n_for_vp)

            # Coverage report
            covered = set()
            for s in state["settlements"]:
                for vx, vy in vps:
                    if vx <= s["x"] < vx + VP and vy <= s["y"] < vy + VP:
                        covered.add((s["x"], s["y"]))
                        break
            print(f"  Seed {seed_idx}: {n_q}q, {n_vps}vp, {len(covered)}/{len(state['settlements'])} sett")

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

            print(f"    → {len(grid_obs)} cells, max {max((len(v) for v in grid_obs.values()), default=0)} obs")

        # Save cache for potential resubmission
        save_cache(round_id, all_grid_obs)

    elif cached:
        print("\n0 queries remaining, using cached observations")
        all_grid_obs = cached
    else:
        print("\nERROR: 0 queries and no cache! Cannot produce good predictions.")
        sys.exit(1)

    # Learn round-specific category priors from ALL observations across seeds
    print("\nLearning round priors...")
    learned_priors = learn_round_priors(all_grid_obs, states)
    for key in sorted(learned_priors.keys()):
        tc, dk = key
        p = learned_priors[key]
        print(f"  {tc}_d{dk}: [{', '.join(f'{v:.3f}' for v in p)}]")

    # Per-settlement survival estimation
    print("\nEstimating per-settlement survival...")
    global_alive = 0
    global_total = 0
    all_sett_pred = []

    for seed_idx in range(n_seeds):
        grid_obs = all_grid_obs[seed_idx]
        settlements = states[seed_idx]["settlements"]
        grid = states[seed_idx]["grid"]

        sett_surv = estimate_settlement_survival(grid_obs, settlements, grid)
        sett_feats = settlement_features(settlements, grid)

        for i, s in enumerate(settlements):
            sx, sy = s["x"], s["y"]
            if (sx, sy) in grid_obs:
                for o in grid_obs[(sx, sy)]:
                    if o in (1, 2):
                        global_alive += 1
                    global_total += 1

        global_surv = global_alive / global_total if global_total > 0 else 0.3
        sett_pred = predict_settlement_survival(sett_surv, sett_feats, global_surv)
        all_sett_pred.append(sett_pred)

        observed = sum(1 for v in sett_surv.values() if v is not None)
        print(f"  Seed {seed_idx}: {observed}/{len(settlements)} obs, "
              f"surv=[{min(sett_pred.values()):.2f}, {max(sett_pred.values()):.2f}]")

    global_surv = global_alive / global_total if global_total > 0 else 0.3
    print(f"  Global survival: {global_surv:.3f}")

    # Build predictions
    print("\nBuilding predictions...")
    all_preds = []
    for seed_idx in range(n_seeds):
        preds, stats = build_predictions(
            states[seed_idx], all_grid_obs[seed_idx],
            learned_priors, all_sett_pred[seed_idx], global_surv
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

    # Results
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
