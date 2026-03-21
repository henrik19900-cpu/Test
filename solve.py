#!/usr/bin/env python3
"""Astar Island solver v17 — Deep Observation + Online Calibration.

v17 improvements over v16:
1. Focused sampling: fewer viewports, many reps → 5+ obs/cell for direct distribution
2. Online calibration: compute per-seed correction factors from observed vs predicted
3. Better Bayesian: with many observations, trust empirical distribution more (lower alpha)
4. Per-settlement S: estimate survival per settlement based on local features
"""

import json
import math
import os
import sys
import time
import requests
import urllib3
import numpy as np
from collections import defaultdict

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("WARNING: xgboost not available, using kNN+Linear only")

urllib3.disable_warnings()

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhOGMxN2M1OC1lYzg0LTQ0MjQtYjMxNy1iYjgzY2UxY2IwNTUiLCJlbWFpbCI6ImhlbnJpazE5OTAwQGdtYWlsLmNvbSIsImlzX2FkbWluIjpmYWxzZSwiZXhwIjoxNzc0NjM2NDA2fQ.FmG-dX5M2v3PXBOfIneuWpouAwVnD-PU0cMwHdwsoAY"
BASE = "https://api.ainm.no/astar-island"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
CACHE_FILE = "obs_cache.json"
TRAINING_DB_FILE = "training_db.json"

NC = 6
H, W = 40, 40
VP = 15
FLOOR = 0.005
GRID_TO_CLASS = {11: 0, 0: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

# ── Linear model (fallback) ─────────────────────────────────────────────
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


def fnorm(probs, floor=FLOOR):
    p = [max(float(v), floor) for v in probs]
    s = sum(p)
    return [v / s for v in p]


# ── Grid precomputation ─────────────────────────────────────────────────

def precompute_grids(state):
    """Precompute distance grid, coastal map, feature grids for a seed."""
    grid = state["grid"]
    settlements = state["settlements"]

    dg = [[999] * W for _ in range(H)]
    for s in settlements:
        sx, sy = s["x"], s["y"]
        for y in range(H):
            for x in range(W):
                d = abs(x - sx) + abs(y - sy)
                if d < dg[y][x]:
                    dg[y][x] = d

    coastal = [[False] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == 10:
                    coastal[y][x] = True
                    break

    adj_sett = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] in (1, 2):
                    adj_sett[y][x] += 1

    n_sett_d3 = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            n_sett_d3[y][x] = sum(1 for s in settlements
                                  if abs(x - s["x"]) + abs(y - s["y"]) <= 3)

    # Additional features for XGBoost
    adj_water = [[0] * W for _ in range(H)]
    adj_forest = [[0] * W for _ in range(H)]
    adj_mountain = [[0] * W for _ in range(H)]
    adj8_water = [[0] * W for _ in range(H)]
    adj8_sett = [[0] * W for _ in range(H)]
    adj8_forest = [[0] * W for _ in range(H)]
    n_sett_d1 = [[0] * W for _ in range(H)]
    n_sett_d2 = [[0] * W for _ in range(H)]
    n_sett_d5 = [[0] * W for _ in range(H)]

    for y in range(H):
        for x in range(W):
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    t = grid[ny][nx]
                    if t == 10: adj_water[y][x] += 1
                    elif t == 4: adj_forest[y][x] += 1
                    elif t == 5: adj_mountain[y][x] += 1
            for ddx in range(-1, 2):
                for ddy in range(-1, 2):
                    if ddx == 0 and ddy == 0: continue
                    nx, ny = x + ddx, y + ddy
                    if 0 <= nx < W and 0 <= ny < H:
                        t = grid[ny][nx]
                        if t == 10: adj8_water[y][x] += 1
                        elif t in (1, 2): adj8_sett[y][x] += 1
                        elif t == 4: adj8_forest[y][x] += 1

    for y in range(H):
        for x in range(W):
            for s in settlements:
                d = abs(x - s["x"]) + abs(y - s["y"])
                if d <= 1: n_sett_d1[y][x] += 1
                if d <= 2: n_sett_d2[y][x] += 1
                if d <= 5: n_sett_d5[y][x] += 1

    # Distance to nearest port
    port_setts = [s for s in settlements if s.get("has_port")]
    d_port = [[99] * W for _ in range(H)]
    for s in port_setts:
        for y in range(H):
            for x in range(W):
                d = abs(x - s["x"]) + abs(y - s["y"])
                if d < d_port[y][x]:
                    d_port[y][x] = d

    n_total_sett = len(settlements)
    n_total_ports = len(port_setts)

    return {"dg": dg, "coastal": coastal, "adj_sett": adj_sett,
            "n_sett_d3": n_sett_d3, "grid": grid, "settlements": settlements,
            "adj_water": adj_water, "adj_forest": adj_forest,
            "adj_mountain": adj_mountain, "adj8_water": adj8_water,
            "adj8_sett": adj8_sett, "adj8_forest": adj8_forest,
            "n_sett_d1": n_sett_d1, "n_sett_d2": n_sett_d2,
            "n_sett_d5": n_sett_d5, "d_port": d_port,
            "n_total_sett": n_total_sett, "n_total_ports": n_total_ports}


def cell_knn_key(x, y, grids):
    """Generate kNN lookup key for a cell."""
    t = grids["grid"][y][x]
    d = grids["dg"][y][x]
    c = grids["coastal"][y][x]
    a_s = grids["adj_sett"][y][x]
    n_s3 = grids["n_sett_d3"][y][x]

    tc = "s" if t in (1, 2) else ("f" if t == 4 else "e")
    adj_w = 1 if c else 0
    if t == 10:
        adj_w = sum(1 for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                    if 0 <= x + dx < W and 0 <= y + dy < H
                    and grids["grid"][y + dy][x + dx] == 10)

    return f"{tc}_{min(d, 6)}_{min(adj_w, 2)}_{min(a_s, 2)}_{min(n_s3, 3)}"


def cell_linear_cat(x, y, grids):
    """Get linear model category for a cell."""
    t = grids["grid"][y][x]
    d = grids["dg"][y][x]
    c = grids["coastal"][y][x]

    if t == 10: return "water"
    if t == 5: return "mountain"
    tc = "s" if t in (1, 2) else ("f" if t == 4 else "e")

    if tc == "s":
        return "sett_coastal" if c else "sett_inland"
    if tc == "f":
        if d <= 1: return "f_d1"
        if d <= 2: return "f_d2"
        if d <= 3: return "f_d3"
        if d <= 5: return "f_d5"
        return "f_far"
    # empty
    if d <= 1: return "e_d1c" if c else "e_d1"
    if d <= 2: return "e_d2c" if c else "e_d2"
    if d <= 3: return "e_d3"
    if d <= 5: return "e_d5"
    return "e_far"


# ── Prior Models ─────────────────────────────────────────────────────────

def linear_prior(cat, S):
    """Linear model prior given category and S."""
    if cat == "water":
        return [1.0 - 5 * FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, FLOOR]
    if cat == "mountain":
        return [FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, 1.0 - 5 * FLOOR]
    coeffs = LINEAR_MODEL.get(cat)
    if not coeffs:
        return [1 / NC] * NC
    S = max(0, min(1, S))
    return fnorm([coeffs[i][0] + coeffs[i][1] * S for i in range(NC)])


def knn_prior(knn_key, S, training_db, fallback_cat):
    """kNN prior: find similar cells from historical data, weighted by S proximity."""
    entries = training_db.get(knn_key, [])

    if len(entries) < 15:
        # Not enough data, try coarser key (drop n_sett_d3)
        parts = knn_key.split("_")
        coarse_key = "_".join(parts[:4]) + "_1"
        entries = training_db.get(coarse_key, [])

    if len(entries) < 10:
        # Fall back to linear model
        return linear_prior(fallback_cat, S)

    # Weight by S proximity
    pred = [0.0] * NC
    total_w = 0
    for entry in entries:
        entry_S = entry[0]
        w = 1.0 / (abs(S - entry_S) + 0.03)
        for i in range(NC):
            pred[i] += w * entry[1 + i]
        total_w += w

    return fnorm([pred[i] / total_w for i in range(NC)])


def hybrid_prior(x, y, S, grids, training_db):
    """Hybrid prior: blend kNN and linear model.

    kNN is better for typical S values (0.15-0.55) but collapses at extremes.
    Linear model extrapolates better. Blend accordingly.
    """
    t = grids["grid"][y][x]

    if t == 10:
        return [1.0 - 5 * FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, FLOOR]
    if t == 5:
        return [FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, 1.0 - 5 * FLOOR]

    d = grids["dg"][y][x]
    knn_key = cell_knn_key(x, y, grids)
    lin_cat = cell_linear_cat(x, y, grids)

    entries = training_db.get(knn_key, [])
    n_entries = len(entries)

    # Count how many training entries are close to our S value
    n_close = sum(1 for e in entries if abs(e[0] - S) < 0.15) if entries else 0

    knn_p = knn_prior(knn_key, S, training_db, lin_cat)
    lin_p = linear_prior(lin_cat, S)

    # Base blend from data availability
    if n_close >= 30:
        blend = 0.85
    elif n_close >= 15:
        blend = 0.65
    elif n_close >= 5:
        blend = 0.35
    else:
        blend = 0.0

    # Reduce kNN weight for extreme S values (kNN struggles here)
    if S < 0.1 or S > 0.6:
        blend *= 0.4  # heavily favor linear for extremes
    elif S < 0.15 or S > 0.5:
        blend *= 0.7

    combined = [blend * knn_p[i] + (1 - blend) * lin_p[i] for i in range(NC)]
    return fnorm(combined)


def xgb_features(x, y, S, grids):
    """Extract 20 features for XGBoost model."""
    t = grids["grid"][y][x]
    tc = 2 if t in (1, 2) else (1 if t == 4 else 0)
    d = grids["dg"][y][x]
    adj_e4 = sum(1 for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                 if 0 <= x + dx < W and 0 <= y + dy < H
                 and grids["grid"][y + dy][x + dx] in (0, 11))

    ns_port = 0
    nearest = min(grids["settlements"],
                  key=lambda s: abs(x - s["x"]) + abs(y - s["y"]))
    if nearest.get("has_port"):
        ns_port = 1

    return [
        S,                              # 0
        tc,                             # 1
        d,                              # 2
        grids["adj_water"][y][x],       # 3
        adj_e4,                         # 4
        grids["adj_sett"][y][x],        # 5
        grids["adj_forest"][y][x],      # 6
        grids["adj_mountain"][y][x],    # 7
        grids["adj8_water"][y][x],      # 8
        grids["adj8_sett"][y][x],       # 9
        grids["adj8_forest"][y][x],     # 10
        grids["n_sett_d1"][y][x],       # 11
        grids["n_sett_d2"][y][x],       # 12
        grids["n_sett_d3"][y][x],       # 13
        grids["n_sett_d5"][y][x],       # 14
        ns_port,                        # 15
        grids["d_port"][y][x],          # 16
        grids["n_total_sett"],          # 17
        grids["n_total_ports"],         # 18
        min(x, y, W - 1 - x, H - 1 - y),  # 19: d_edge
    ]


def xgb_prior(x, y, S, grids, xgb_models):
    """XGBoost model prediction."""
    if not xgb_models:
        return None
    feats = np.array([xgb_features(x, y, S, grids)])
    preds = [model.predict(feats)[0] for model in xgb_models]
    return fnorm(preds)


def ensemble_prior(x, y, S, grids, training_db, xgb_models):
    """Ensemble: XGBoost + kNN + Linear with dynamic per-cell weighting.

    v16: Weight models based on terrain type, distance, and data availability.
    - Near settlements (d<=2): kNN has more relevant training data → favor hybrid
    - Forest/empty far cells: XGB generalizes better → favor XGB
    - Extreme S values: linear extrapolates better → reduce kNN
    """
    t = grids["grid"][y][x]
    if t == 10:
        return [1.0 - 5 * FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, FLOOR]
    if t == 5:
        return [FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, 1.0 - 5 * FLOOR]

    d = grids["dg"][y][x]
    if d > 8:
        lin_cat = cell_linear_cat(x, y, grids)
        return linear_prior(lin_cat, S)

    hyb_p = hybrid_prior(x, y, S, grids, training_db)

    if xgb_models and HAS_XGB:
        xgb_p = xgb_prior(x, y, S, grids, xgb_models)
        if xgb_p:
            # Dynamic weighting based on cell context
            tc = "s" if t in (1, 2) else ("f" if t == 4 else "e")

            # Base: 50/50
            w_xgb = 0.5

            # Settlement cells: kNN has rich history → favor hybrid
            if tc == "s":
                w_xgb = 0.35
            # Close to settlements: kNN also good
            elif d <= 2:
                w_xgb = 0.40
            # Far cells: XGB generalizes better
            elif d >= 5:
                w_xgb = 0.60

            # Extreme S: XGB trained on all S values, more robust
            if S < 0.1 or S > 0.6:
                w_xgb = min(w_xgb + 0.15, 0.75)

            # Check kNN data availability
            knn_key = cell_knn_key(x, y, grids)
            entries = training_db.get(knn_key, [])
            n_close = sum(1 for e in entries if abs(e[0] - S) < 0.15)
            if n_close < 10:
                w_xgb = min(w_xgb + 0.15, 0.80)  # less kNN data → lean XGB

            # Disagreement bonus: if models disagree a lot, hedge toward equal
            max_diff = max(abs(xgb_p[i] - hyb_p[i]) for i in range(NC))
            if max_diff > 0.3:
                w_xgb = 0.5  # large disagreement → equal weight (hedge)

            combined = [w_xgb * xgb_p[i] + (1 - w_xgb) * hyb_p[i] for i in range(NC)]
            return fnorm(combined)

    return hyb_p


# ── Viewport Placement ──────────────────────────────────────────────────

def cell_entropy(prior):
    """Shannon entropy of a probability distribution (higher = more uncertain)."""
    h = 0.0
    for p in prior:
        if p > 1e-9:
            h -= p * math.log(p)
    return h


def place_viewports(grids, n_vps, S=0.3, training_db=None, xgb_models=None,
                    grid_obs=None):
    """Entropy-aware viewport placement.

    v16: Combines settlement proximity value with model uncertainty (entropy).
    Cells where the model is uncertain get higher value → queries go where
    they help most.
    """
    dg = grids["dg"]

    cell_value = {}
    for y in range(H):
        for x in range(W):
            t = grids["grid"][y][x]
            if t in (10, 5):
                continue
            d = dg[y][x]

            # Base value from distance
            if d == 0:
                base = 10.0
            elif d == 1:
                base = 7.0
            elif d == 2:
                base = 4.0
            elif d == 3:
                base = 1.5
            elif d <= 5:
                base = 0.5
            else:
                continue

            # Entropy bonus: uncertain cells are more valuable to observe
            if training_db is not None:
                prior = ensemble_prior(x, y, S, grids, training_db, xgb_models)
                ent = cell_entropy(prior)
                # Max entropy for 6 classes is ln(6) ≈ 1.79
                ent_bonus = 1.0 + ent / 1.79  # range [1.0, 2.0]
                base *= ent_bonus

            # Reduce value if already observed
            if grid_obs and (x, y) in grid_obs:
                n_obs = len(grid_obs[(x, y)])
                base *= 0.3 / (1 + n_obs)  # diminishing returns

            cell_value[(x, y)] = base

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
                            score += v * 0.1
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)

        viewports.append(best_pos)
        vx, vy = best_pos
        for dy in range(VP):
            for dx in range(VP):
                covered.add((vx + dx, vy + dy))

    return viewports


# ── S Estimation ─────────────────────────────────────────────────────────

def estimate_S_single(grid_obs, grids):
    """Estimate S for a single seed from its observations."""
    alive = 0
    total = 0
    for s in grids["settlements"]:
        key = (s["x"], s["y"])
        if key in grid_obs:
            for o in grid_obs[key]:
                if o in (1, 2):
                    alive += 1
                total += 1
    if total >= 3:
        return alive / total, total
    # Fallback: d<=2 zone
    alive2 = 0
    total2 = 0
    for (x, y), obs_list in grid_obs.items():
        d = grids["dg"][y][x]
        t = grids["grid"][y][x]
        if d <= 2 and t not in (10, 5):
            for o in obs_list:
                if o in (1, 2):
                    alive2 += 1
                total2 += 1
    if total2 >= 5:
        return min(alive2 / total2 * 1.1, 1.0), total2
    return None, 0


def estimate_S_per_settlement(grid_obs, grids):
    """Estimate per-settlement survival probability.

    v17: Each settlement gets its own survival rate based on:
    - Direct observations of this settlement
    - Observations of nearby settlements (spatial smoothing)
    - Settlement features (has_port, coastal, neighbor count)
    Returns dict: (sx, sy) -> S_local
    """
    settlements = grids["settlements"]

    # First pass: direct observation per settlement
    sett_obs = {}  # (sx,sy) -> (alive_count, total_count)
    for s in settlements:
        key = (s["x"], s["y"])
        if key in grid_obs:
            alive = sum(1 for o in grid_obs[key] if o in (1, 2))
            total = len(grid_obs[key])
            sett_obs[key] = (alive, total)

    # Global S as prior
    total_alive = sum(a for a, t in sett_obs.values())
    total_obs = sum(t for a, t in sett_obs.values())
    S_global = total_alive / total_obs if total_obs >= 5 else 0.3

    # Per-settlement S with spatial smoothing
    S_local = {}
    for s in settlements:
        sx, sy = s["x"], s["y"]

        # Collect observations from this + nearby settlements
        weighted_alive = 0.0
        weighted_total = 0.0

        for s2 in settlements:
            key2 = (s2["x"], s2["y"])
            if key2 not in sett_obs:
                continue
            d = abs(sx - s2["x"]) + abs(sy - s2["y"])
            if d > 8:
                continue

            a, t = sett_obs[key2]
            # Weight by distance: self=1.0, d=1: 0.5, d=2: 0.25, etc.
            w = 1.0 / (1 + d) ** 1.2

            # Bonus if similar features (both coastal, both have port)
            s1_coastal = grids["coastal"][sy][sx]
            s2_coastal = grids["coastal"][s2["y"]][s2["x"]]
            if s1_coastal == s2_coastal:
                w *= 1.3
            if s.get("has_port") == s2.get("has_port"):
                w *= 1.1

            weighted_alive += w * a
            weighted_total += w * t

        if weighted_total >= 2.0:
            S_raw = weighted_alive / weighted_total
            # Shrink toward global: more local data → less shrinkage
            shrink = min(weighted_total / 15.0, 0.85)
            S_local[(sx, sy)] = shrink * S_raw + (1 - shrink) * S_global
        else:
            S_local[(sx, sy)] = S_global

    return S_local, S_global


def estimate_S(all_grid_obs, all_grids):
    """Estimate per-seed S with per-settlement heterogeneity.

    Returns (S_global, S_per_seed, S_per_settlement_per_seed)
    """
    # Global estimate
    alive_total = 0
    obs_total = 0
    for seed_idx, grids in enumerate(all_grids):
        grid_obs = all_grid_obs[seed_idx]
        for s in grids["settlements"]:
            key = (s["x"], s["y"])
            if key in grid_obs:
                for o in grid_obs[key]:
                    if o in (1, 2):
                        alive_total += 1
                    obs_total += 1

    if obs_total >= 5:
        S_global = alive_total / obs_total
    else:
        S_global = 0.3

    print(f"  S_global = {S_global:.3f} (from {obs_total} settlement obs)")

    # Per-seed S + per-settlement maps
    S_per_seed = []
    S_maps = []
    for seed_idx in range(len(all_grids)):
        S_seed, n_obs = estimate_S_single(all_grid_obs[seed_idx], all_grids[seed_idx])
        S_local_map, _ = estimate_S_per_settlement(
            all_grid_obs[seed_idx], all_grids[seed_idx])

        if S_seed is not None and n_obs >= 8:
            w_seed = min(n_obs / 30.0, 0.8)
            S_blend = w_seed * S_seed + (1 - w_seed) * S_global
            S_per_seed.append(S_blend)
            print(f"  Seed {seed_idx}: S={S_blend:.3f} (seed={S_seed:.3f}, n={n_obs})")
        else:
            S_per_seed.append(S_global)
            print(f"  Seed {seed_idx}: S={S_global:.3f} (using global)")

        S_maps.append(S_local_map)

        # Show S heterogeneity stats
        if S_local_map:
            vals = list(S_local_map.values())
            print(f"    Per-sett S range: [{min(vals):.3f}, {max(vals):.3f}], "
                  f"std={np.std(vals):.3f}")

    return S_global, S_per_seed, S_maps


# ── Bayesian Updating ────────────────────────────────────────────────────

def bayesian_update(prior, obs_counts, n_obs):
    """Bayesian update with adaptive prior weight.

    The prior has ~5% error per class (KL ~0.05).
    Each observation is a point sample (very noisy for 6-class multinomial).
    With few observations, the prior should dominate.
    With many observations, observations should dominate.

    Optimal prior strength: balance bias (from prior error) vs variance (from sampling).
    For 6-class multinomial: variance term = (K-1)/(2*(alpha+n))
    For our prior: bias term = alpha^2/(alpha+n)^2 * KL_prior

    With KL_prior ≈ 0.05 and K=6:
      optimal alpha ≈ sqrt(5 / (2 * 0.05)) ≈ 7
    """
    # Optimal alpha from cross-validation on R12 (leave-one-out):
    # alpha=5-8 is best across all observation counts
    if n_obs <= 2:
        alpha0 = 7.0
    elif n_obs <= 5:
        alpha0 = 6.0
    elif n_obs <= 10:
        alpha0 = 5.0
    else:
        alpha0 = 4.0

    total = n_obs + alpha0
    posterior = [(obs_counts[c] + alpha0 * prior[c]) / total for c in range(NC)]
    return fnorm(posterior)


# ── Spatial Borrowing ────────────────────────────────────────────────────

def spatial_borrow(x, y, grid_obs, grids):
    """Borrow from nearby observed cells with similar terrain context.

    v16: Also considers coastal similarity and adjacent settlement count
    for better terrain-context matching. Increased n_eff cap to 2.0.
    """
    t = grids["grid"][y][x]
    d = grids["dg"][y][x]
    tc = "s" if t in (1, 2) else ("f" if t == 4 else "e")
    is_coastal = grids["coastal"][y][x]
    adj_s = grids["adj_sett"][y][x]

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

                nt = grids["grid"][ny][nx]
                n_tc = "s" if nt in (1, 2) else ("f" if nt == 4 else "e")
                if n_tc != tc:
                    continue

                nd = grids["dg"][ny][nx]
                if abs(nd - d) > 2:
                    continue

                dist_val = abs(ddx) + abs(ddy)
                w = 1.0 / (1 + dist_val) ** 1.5

                # Distance-to-settlement similarity bonus
                if nd == d:
                    w *= 2.0
                elif abs(nd - d) == 1:
                    w *= 1.2

                # Terrain context similarity: coastal match
                n_coastal = grids["coastal"][ny][nx]
                if n_coastal == is_coastal:
                    w *= 1.3

                # Adjacent settlement count similarity
                n_adj_s = grids["adj_sett"][ny][nx]
                if n_adj_s == adj_s:
                    w *= 1.2
                elif abs(n_adj_s - adj_s) <= 1:
                    w *= 1.05

                for o in grid_obs[(nx, ny)]:
                    pseudo[o] += w
                    tw += w

    return pseudo, tw


# ── Online Calibration ─────────────────────────────────────────────────

def compute_calibration(grids, grid_obs, S, training_db, xgb_models):
    """v17: Compute per-category calibration factors.

    Compare model predictions to actual observations for cells we've seen.
    Group by terrain category and compute ratio: observed_freq / predicted_prob.
    """
    cat_pred = defaultdict(lambda: [0.0] * NC)
    cat_obs = defaultdict(lambda: [0] * NC)
    cat_n = defaultdict(int)

    for (x, y), obs_list in grid_obs.items():
        t = grids["grid"][y][x]
        if t in (10, 5):
            continue

        cat = cell_linear_cat(x, y, grids)
        prior = ensemble_prior(x, y, S, grids, training_db, xgb_models)

        for c in range(NC):
            cat_pred[cat][c] += prior[c] * len(obs_list)
        for o in obs_list:
            cat_obs[cat][o] += 1
        cat_n[cat] += len(obs_list)

    calibration = {}
    for cat in cat_pred:
        n = cat_n[cat]
        if n < 10:
            continue
        ratios = [1.0] * NC
        for c in range(NC):
            pred_frac = cat_pred[cat][c] / n if n > 0 else 1.0 / NC
            obs_frac = cat_obs[cat][c] / n if n > 0 else 1.0 / NC
            if pred_frac > 0.01:
                raw_ratio = obs_frac / pred_frac
                # Shrink toward 1.0 to avoid over-correction
                shrink = min(n / 200.0, 0.7)  # more data → trust correction more
                ratios[c] = shrink * raw_ratio + (1 - shrink)
            else:
                ratios[c] = 1.0
        calibration[cat] = ratios

    return calibration


def calibrate_prior(prior, cat, calibration):
    """Apply calibration correction to a prior prediction."""
    if cat not in calibration:
        return prior
    ratios = calibration[cat]
    adjusted = [prior[c] * ratios[c] for c in range(NC)]
    return fnorm(adjusted)


# ── Prediction Building ─────────────────────────────────────────────────

def build_predictions(grids, grid_obs, S, training_db, xgb_models=None,
                      S_local_map=None, calibration=None):
    """Build per-cell predictions with per-settlement S + online calibration.

    v17: With deep observations (5+), trusts empirical distribution heavily.
    Uses per-settlement S for cells near settlements.
    """
    preds = [[[0.0] * NC for _ in range(W)] for _ in range(H)]
    stats = {"obs": 0, "spatial": 0, "model": 0, "obs_deep": 0}

    for y in range(H):
        for x in range(W):
            # v17: Per-settlement S for cells near settlements
            S_cell = S
            if S_local_map:
                d = grids["dg"][y][x]
                if d <= 5:
                    best_d = 999
                    skey = None
                    for s in grids["settlements"]:
                        sd = abs(x - s["x"]) + abs(y - s["y"])
                        if sd < best_d:
                            best_d = sd
                            skey = (s["x"], s["y"])
                    if skey and skey in S_local_map:
                        S_cell = S_local_map[skey]

            prior = ensemble_prior(x, y, S_cell, grids, training_db, xgb_models)

            # v17: Online calibration correction
            if calibration:
                cat = cell_linear_cat(x, y, grids)
                prior = calibrate_prior(prior, cat, calibration)

            obs = grid_obs.get((x, y), [])

            if len(obs) >= 5:
                # v17: Deep observations — trust empirical more
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1
                n = len(obs)
                # Lower alpha = trust observations more
                alpha = max(1.5, 4.0 - n * 0.3)
                total = n + alpha
                preds[y][x] = fnorm([(obs_counts[c] + alpha * prior[c]) / total
                                      for c in range(NC)])
                stats["obs_deep"] += 1
                stats["obs"] += 1
            elif len(obs) >= 1:
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1
                preds[y][x] = bayesian_update(prior, obs_counts, len(obs))
                stats["obs"] += 1
            elif grids["dg"][y][x] <= 5 and grid_obs:
                pseudo, tw = spatial_borrow(x, y, grid_obs, grids)
                if tw >= 1.0:
                    n_eff = min(tw * 0.35, 2.0)
                    norm_p = [pseudo[c] / tw for c in range(NC)]
                    alpha0 = 3.0
                    pred = [(n_eff * norm_p[c] + alpha0 * prior[c]) / (n_eff + alpha0)
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


def load_cache(round_id):
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE) as f:
        data = json.load(f)
    if data.get("round_id") != round_id:
        return None
    result = []
    for seed_data in data["obs"]:
        grid_obs = defaultdict(list)
        for key, obs_list in seed_data.items():
            x, y = map(int, key.split(","))
            grid_obs[(x, y)] = obs_list
        result.append(grid_obs)
    return result


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=== Astar Island Solver v17 — Deep Obs + Online Calibration ===\n")

    # Load XGBoost models
    xgb_models = None
    if HAS_XGB:
        xgb_models = []
        for c in range(NC):
            fpath = f"xgb_class{c}.json"
            if os.path.exists(fpath):
                model = xgb.XGBRegressor()
                model.load_model(fpath)
                xgb_models.append(model)
            else:
                print(f"WARNING: {fpath} not found!")
                xgb_models = None
                break
        if xgb_models:
            print(f"XGBoost: loaded {len(xgb_models)} class models")
    else:
        print("XGBoost: not available (fallback to kNN+Linear)")

    # Load training database
    if not os.path.exists(TRAINING_DB_FILE):
        print(f"ERROR: {TRAINING_DB_FILE} not found! Run training data builder first.")
        sys.exit(1)
    with open(TRAINING_DB_FILE) as f:
        training_db = json.load(f)
    n_entries = sum(len(v) for v in training_db.values())
    print(f"Training DB: {len(training_db)} categories, {n_entries} entries")

    # Get active round
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

    # Precompute grids for all seeds
    all_grids = [precompute_grids(s) for s in states]
    for i, g in enumerate(all_grids):
        ports = sum(1 for s in g["settlements"] if s.get("has_port"))
        print(f"  Seed {i}: {len(g['settlements'])} settlements ({ports} ports)")

    # ── PHASE 1: Focused observation gathering ─────────────────────────
    # v17: Use fewer viewports with more repetitions to get deep observations
    # Goal: 5+ observations per dynamic cell → direct distribution estimation

    cached = load_cache(round_id)

    if remaining > 0:
        print(f"\n--- Phase 1: Focused observations ({remaining} queries) ---")

        # Allocate queries proportional to settlement count
        counts = [len(g["settlements"]) for g in all_grids]
        total = sum(counts)
        alloc = [max(4, round(remaining * c / total)) for c in counts]
        while sum(alloc) > remaining:
            alloc[alloc.index(max(alloc))] -= 1
        while sum(alloc) < remaining:
            ratios = [counts[i] / alloc[i] for i in range(n_seeds)]
            alloc[ratios.index(max(ratios))] += 1

        print(f"  Allocation: {alloc}")

        all_grid_obs = cached if cached else [defaultdict(list) for _ in range(n_seeds)]

        for seed_idx in range(n_seeds):
            if alloc[seed_idx] == 0:
                continue
            n_q = alloc[seed_idx]

            # v17: FOCUSED strategy — fewer viewports, more reps
            # With 10 queries: 2 viewports × 5 reps = 5 obs per cell
            # Better than 4 viewports × 2.5 reps = 2 obs per cell
            n_sett = len(all_grids[seed_idx]["settlements"])
            if n_q >= 8:
                n_vps = 2  # always 2 for deep observation
            elif n_q >= 4:
                n_vps = 2
            else:
                n_vps = 1
            q_per_vp = n_q // n_vps
            extra = n_q - n_vps * q_per_vp

            vps = place_viewports(all_grids[seed_idx], n_vps,
                                  S=0.3, training_db=training_db,
                                  xgb_models=xgb_models,
                                  grid_obs=all_grid_obs[seed_idx])

            # Coverage stats
            covered_setts = set()
            for si, s in enumerate(all_grids[seed_idx]["settlements"]):
                for vx, vy in vps:
                    if vx <= s["x"] < vx + VP and vy <= s["y"] < vy + VP:
                        covered_setts.add(si)
                        break
            print(f"  Seed {seed_idx}: {n_q}q, {n_vps}vp ({q_per_vp}+ reps/vp), "
                  f"{len(covered_setts)}/{n_sett} sett")

            grid_obs = all_grid_obs[seed_idx]
            for vi, (vx, vy) in enumerate(vps):
                n_reps = q_per_vp + (1 if vi < extra else 0)
                for _ in range(n_reps):
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

        # Report observation depth stats
        for seed_idx in range(n_seeds):
            obs_counts = [len(v) for v in all_grid_obs[seed_idx].values()]
            if obs_counts:
                avg = sum(obs_counts) / len(obs_counts)
                deep = sum(1 for c in obs_counts if c >= 5)
                print(f"  Seed {seed_idx}: {len(obs_counts)} cells observed, "
                      f"avg {avg:.1f} obs/cell, {deep} cells with 5+ obs")

    elif cached:
        all_grid_obs = cached
        total_obs = sum(len(d) for d in all_grid_obs)
        print(f"\nUsing cached: {total_obs} cell-observations")
    else:
        all_grid_obs = [defaultdict(list) for _ in range(n_seeds)]
        print("\nNo queries and no cache — model-only mode")

    # ── PHASE 2: Estimate S (per-seed + per-settlement) ───────────────

    print("\n--- Phase 2: Estimating S (per-seed + per-settlement) ---")
    S_global, S_per_seed, S_maps = estimate_S(all_grid_obs, all_grids)

    # ── PHASE 2.5: Online calibration ─────────────────────────────────

    print("\n--- Phase 2.5: Online calibration ---")
    all_calibrations = []
    for seed_idx in range(n_seeds):
        cal = compute_calibration(
            all_grids[seed_idx], all_grid_obs[seed_idx],
            S_per_seed[seed_idx], training_db, xgb_models
        )
        all_calibrations.append(cal)
        if cal:
            # Show biggest corrections
            biggest = []
            for cat, ratios in cal.items():
                max_adj = max(abs(r - 1.0) for r in ratios)
                biggest.append((max_adj, cat, ratios))
            biggest.sort(reverse=True)
            for mag, cat, ratios in biggest[:3]:
                r_str = ", ".join(f"{r:.2f}" for r in ratios)
                print(f"  Seed {seed_idx} [{cat}]: [{r_str}] (max adj: {mag:.2f})")

    # ── PHASE 3: Build and submit predictions ─────────────────────────

    print("\n--- Phase 3: Building predictions (per-settlement S + calibrated) ---")

    all_preds = []
    for seed_idx in range(n_seeds):
        S_seed = S_per_seed[seed_idx]
        preds, stats = build_predictions(
            all_grids[seed_idx], all_grid_obs[seed_idx],
            S_seed, training_db, xgb_models,
            S_local_map=S_maps[seed_idx],
            calibration=all_calibrations[seed_idx]
        )
        all_preds.append(preds)
        print(f"  Seed {seed_idx} (S={S_seed:.3f}): {stats}")

    # Submit main prediction
    print("\nSubmitting main prediction (calibrated + per-settlement S)...")
    for seed_idx, preds in enumerate(all_preds):
        try:
            result = api_post("/submit", {
                "round_id": round_id,
                "seed_index": seed_idx,
                "prediction": preds,
            })
            print(f"  Seed {seed_idx}: {result.get('status', 'unknown')}")
        except requests.exceptions.HTTPError as e:
            print(f"  Seed {seed_idx} ERROR: {e}")

    # ── PHASE 4: Multi-S fallback submissions ─────────────────────────

    print("\n--- Phase 4: Concentrated multi-S fallback ---")
    S_offsets = [-0.25, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15, 0.25, 0.40, 0.60]
    S_alternatives = sorted(set(
        max(0.0, min(1.0, S_global + off)) for off in S_offsets
        if abs(off) > 0.02
    ))
    for s_ext in [0.0, 0.5, 1.0]:
        if all(abs(s_ext - s) > 0.04 for s in S_alternatives + [S_global]):
            S_alternatives.append(s_ext)
    S_alternatives.sort()

    for S_alt in S_alternatives:
        for seed_idx in range(n_seeds):
            preds, _ = build_predictions(
                all_grids[seed_idx], all_grid_obs[seed_idx],
                S_alt, training_db, xgb_models,
                S_local_map=S_maps[seed_idx],
                calibration=all_calibrations[seed_idx]
            )
            try:
                api_post("/submit", {
                    "round_id": round_id,
                    "seed_index": seed_idx,
                    "prediction": preds,
                })
            except Exception:
                pass
        print(f"  S={S_alt:.3f}: submitted")
        time.sleep(0.2)

    # Re-submit with best (calibrated + per-settlement S) as final
    print(f"\nRe-submitting calibrated per-settlement S as final...")
    for seed_idx in range(n_seeds):
        preds, _ = build_predictions(
            all_grids[seed_idx], all_grid_obs[seed_idx],
            S_per_seed[seed_idx], training_db, xgb_models,
            S_local_map=S_maps[seed_idx],
            calibration=all_calibrations[seed_idx]
        )
        try:
            api_post("/submit", {
                "round_id": round_id,
                "seed_index": seed_idx,
                "prediction": preds,
            })
        except Exception:
            pass

    # ── Results ───────────────────────────────────────────────────────

    print("\n--- Results ---")
    try:
        my_rounds = api_get("/my-rounds")
        for r in my_rounds:
            if r.get("id") == round_id:
                for k in ("round_number", "round_score", "seed_scores", "rank",
                           "seeds_submitted", "queries_used"):
                    print(f"  {k}: {r.get(k)}")
                break
    except Exception as e:
        print(f"  {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
