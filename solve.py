#!/usr/bin/env python3
"""Astar Island solver v9 — Per-settlement survival model + physics-based predictions."""

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

NC = 6  # Classes: 0=empty, 1=settlement, 2=port, 3=ruin, 4=forest, 5=mountain
H, W = 40, 40
VP = 15
FLOOR = 0.001  # Lower floor — let predictions be more confident

GRID_TO_CLASS = {11: 0, 0: 0, 10: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

CLASS_NAMES = ['empty', 'settlement', 'port', 'ruin', 'forest', 'mountain']


def api_get(path):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()


def api_post(path, data):
    r = requests.post(f"{BASE}{path}", headers=HEADERS, json=data, timeout=30, verify=False)
    r.raise_for_status()
    return r.json()


def fnorm(probs):
    """Normalize probabilities with floor."""
    p = [max(v, FLOOR) for v in probs]
    s = sum(p)
    return [v / s for v in p]


def tcat(code):
    """Terrain category from grid code."""
    if code == 5: return "m"   # mountain
    if code == 4: return "f"   # forest
    if code in (1, 2, 3): return "s"  # settlement/port/ruin
    return "e"  # empty/ocean/plains


def is_ocean(x, y, grid):
    return 0 <= x < W and 0 <= y < H and grid[y][x] == 10


def is_coastal(x, y, grid):
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        nx, ny = x+dx, y+dy
        if is_ocean(nx, ny, grid):
            return True
    return False


def dist_grid(settlements):
    """Manhattan distance to nearest settlement for each cell."""
    dg = [[999]*W for _ in range(H)]
    for s in settlements:
        sx, sy = s["x"], s["y"]
        for y in range(H):
            for x in range(W):
                d = abs(x-sx)+abs(y-sy)
                if d < dg[y][x]:
                    dg[y][x] = d
    return dg


# ── Settlement Feature Analysis ─────────────────────────────────────────

def count_terrain_radius(x, y, grid, terrain_code, radius):
    """Count cells of a terrain type within Manhattan distance radius."""
    count = 0
    for dy in range(-radius, radius+1):
        for dx in range(-radius, radius+1):
            if abs(dx)+abs(dy) > radius or (dx == 0 and dy == 0):
                continue
            nx, ny = x+dx, y+dy
            if 0 <= nx < W and 0 <= ny < H and grid[ny][nx] == terrain_code:
                count += 1
    return count


def compute_settlement_features(settlement, grid, all_settlements):
    """Compute local features for a settlement that predict its survival."""
    x, y = settlement["x"], settlement["y"]

    # Food supply: forests nearby
    forests_r2 = count_terrain_radius(x, y, grid, 4, 2)
    forests_r4 = count_terrain_radius(x, y, grid, 4, 4)

    # Natural defense: mountains nearby
    mountains_r3 = count_terrain_radius(x, y, grid, 5, 3)

    # Coastal access
    coastal = is_coastal(x, y, grid)

    # Competition: nearby rival settlements
    rival_dists = []
    for s2 in all_settlements:
        if s2["x"] == x and s2["y"] == y:
            continue
        d = abs(s2["x"] - x) + abs(s2["y"] - y)
        rival_dists.append(d)

    n_rivals_r4 = sum(1 for d in rival_dists if d <= 4)
    n_rivals_r6 = sum(1 for d in rival_dists if d <= 6)
    n_rivals_r8 = sum(1 for d in rival_dists if d <= 8)
    min_rival = min(rival_dists) if rival_dists else 99

    # Empty space to expand into
    empty_r3 = count_terrain_radius(x, y, grid, 11, 3)

    return {
        "forests_r2": forests_r2,
        "forests_r4": forests_r4,
        "mountains_r3": mountains_r3,
        "coastal": coastal,
        "has_port": settlement.get("has_port", False),
        "n_rivals_r4": n_rivals_r4,
        "n_rivals_r6": n_rivals_r6,
        "n_rivals_r8": n_rivals_r8,
        "min_rival_dist": min_rival,
        "empty_r3": empty_r3,
    }


def predict_settlement_survival(features):
    """Predict survival probability based on local geography.

    The simulation runs 50 years with growth, conflict, trade, winter, environment.
    - More forests → more food → better survival
    - More rivals nearby → more raiding → worse survival
    - Coastal → port/trade → better survival
    - Mountains → natural defense → better survival
    """
    # Start at neutral logit
    logit = 0.0  # sigmoid(0) = 0.5

    # Food supply is critical - forests within r2 are directly harvestable
    food = features["forests_r2"]
    logit += 0.20 * (food - 2)  # avg ~2 forests in r2

    # Broader food (r4)
    logit += 0.05 * (features["forests_r4"] - 6)

    # Competition kills
    logit -= 0.25 * features["n_rivals_r4"]   # very close rivals are dangerous
    logit -= 0.10 * features["n_rivals_r6"]   # medium-range raids

    # Isolation is safety
    if features["min_rival_dist"] >= 8:
        logit += 0.6
    elif features["min_rival_dist"] >= 5:
        logit += 0.3

    # Coastal = trade = wealth = better survival
    if features["coastal"]:
        logit += 0.25

    # Port = already established trade
    if features["has_port"]:
        logit += 0.35

    # Mountains give natural defense
    logit += 0.08 * features["mountains_r3"]

    # Empty space to expand
    logit += 0.02 * features["empty_r3"]

    survival = 1.0 / (1.0 + math.exp(-logit))
    return max(0.05, min(0.95, survival))


def predict_port_rate(features, survival):
    """Predict port probability given survival."""
    if not features["coastal"]:
        return 0.02  # Very unlikely without coast
    if features["has_port"]:
        return 0.60  # Had port initially, likely to keep it
    # Coastal without port: prosperous settlements build ports
    # Higher survival → more wealth → more likely to build port
    return 0.15 + 0.20 * survival


# ── Viewport Selection ───────────────────────────────────────────────────

def greedy_viewports(settlements, n_viewports):
    """Greedily select viewports to maximize settlement coverage."""
    if not settlements:
        return [(12, 12)]

    sett_positions = [(s["x"], s["y"]) for s in settlements]
    covered = set()
    viewports = []

    for _ in range(n_viewports):
        best_score, best_pos = -1, (0, 0)
        for vy in range(0, H - VP + 1):
            for vx in range(0, W - VP + 1):
                # Count uncovered settlements in this viewport
                new_covered = 0
                dyn_score = 0
                for sx, sy in sett_positions:
                    if vx <= sx < vx + VP and vy <= sy < vy + VP:
                        if (sx, sy) not in covered:
                            new_covered += 1
                        # Also value dynamic area around settlement
                        for r in range(1, 4):
                            for ddx in range(-r, r + 1):
                                for ddy in range(-r, r + 1):
                                    if abs(ddx) + abs(ddy) <= r:
                                        nx, ny = sx + ddx, sy + ddy
                                        if vx <= nx < vx + VP and vy <= ny < vy + VP:
                                            dyn_score += 0.05

                score = new_covered * 10 + dyn_score
                if score > best_score:
                    best_score = score
                    best_pos = (vx, vy)

        viewports.append(best_pos)
        vx, vy = best_pos
        for sx, sy in sett_positions:
            if vx <= sx < vx + VP and vy <= sy < vy + VP:
                covered.add((sx, sy))

    return viewports


# ── Prediction Building ─────────────────────────────────────────────────

def build_settlement_model(state):
    """Build per-settlement survival and port predictions from map topology."""
    grid = state["grid"]
    settlements = state["settlements"]

    model = {}
    for s in settlements:
        features = compute_settlement_features(s, grid, settlements)
        survival = predict_settlement_survival(features)
        port_rate = predict_port_rate(features, survival)
        model[(s["x"], s["y"])] = {
            "survival": survival,
            "port_rate": port_rate,
            "features": features,
        }

    return model


def update_model_with_observations(model, sett_snapshots, settlements):
    """Update settlement model with actual simulation observations."""
    n_snaps = len(sett_snapshots)
    if n_snaps == 0:
        return model

    for s in settlements:
        sx, sy = s["x"], s["y"]
        alive_count = 0
        port_count = 0
        observed = False

        for snap in sett_snapshots:
            found = None
            for ss in snap:
                if ss["x"] == sx and ss["y"] == sy:
                    found = ss
                    break

            if found is not None:
                observed = True
                if found.get("alive", True):
                    alive_count += 1
                    if found.get("has_port"):
                        port_count += 1

        if observed and (sx, sy) in model:
            # Blend model prediction with observed data
            obs_survival = alive_count / n_snaps
            obs_port = port_count / alive_count if alive_count > 0 else 0

            # Weight: more observations → trust data more
            w = min(0.9, n_snaps / (n_snaps + 3))
            model[(sx, sy)]["survival"] = w * obs_survival + (1 - w) * model[(sx, sy)]["survival"]
            model[(sx, sy)]["port_rate"] = w * obs_port + (1 - w) * model[(sx, sy)]["port_rate"]
            model[(sx, sy)]["observed"] = True
            model[(sx, sy)]["n_obs"] = n_snaps

    return model


def predict_cell(x, y, grid, sett_model, dg):
    """Predict class distribution for a single cell based on settlement model."""
    terrain = grid[y][x]
    tc = tcat(terrain)

    # Mountain: always static
    if tc == "m":
        return [FLOOR, FLOOR, FLOOR, FLOOR, FLOOR, 1.0]

    # Ocean: always stays empty (class 0)
    if terrain == 10:
        return [1.0, FLOOR, FLOOR, FLOOR, FLOOR, FLOOR]

    d_nearest = dg[y][x]
    coastal = is_coastal(x, y, grid)
    is_forest = (terrain == 4)

    # Collect influence from all nearby settlements
    p_becomes_sett = 0.0
    p_becomes_port = 0.0
    p_becomes_ruin = 0.0
    p_expansion_from_any = 0.0

    for (sx, sy), sm in sett_model.items():
        d = abs(x - sx) + abs(y - sy)
        if d > 12:
            continue  # Too far to influence

        survival = sm["survival"]
        port_rate = sm["port_rate"]

        if d == 0:
            # THIS IS the settlement cell itself
            p_sett = survival * (1 - port_rate)
            p_port = survival * port_rate
            # When settlement dies:
            p_ruin_dead = 0.20
            p_forest_dead = 0.35 if is_forest else 0.25
            p_empty_dead = 1.0 - p_ruin_dead - p_forest_dead

            return fnorm([
                (1 - survival) * p_empty_dead,
                p_sett,
                p_port,
                (1 - survival) * p_ruin_dead,
                (1 - survival) * p_forest_dead,
                0.0
            ])

        # Expansion probability from this settlement
        # Decays with distance, higher for forest (food expansion), lower for ocean adjacents
        if d <= 1:
            exp_base = 0.22
        elif d <= 2:
            exp_base = 0.14
        elif d <= 3:
            exp_base = 0.08
        elif d <= 4:
            exp_base = 0.05
        elif d <= 5:
            exp_base = 0.03
        elif d <= 7:
            exp_base = 0.015
        elif d <= 10:
            exp_base = 0.005
        else:
            exp_base = 0.001

        # Forest terrain: settlement expands preferentially toward food
        if is_forest:
            exp_base *= 1.4

        # Expansion probability = settlement survives AND expands this far
        p_expand = survival * exp_base

        # Port expansion: coastal cells near port settlements are prime port locations
        if coastal:
            p_port_expand = exp_base * survival * (0.15 if port_rate > 0.3 else 0.06)
        else:
            p_port_expand = 0.0

        # Ruin probability: when settlement dies, ruins may appear nearby
        if d <= 1:
            ruin_base = 0.04
        elif d <= 2:
            ruin_base = 0.02
        elif d <= 3:
            ruin_base = 0.008
        else:
            ruin_base = 0.002
        p_ruin_here = (1 - survival) * ruin_base

        # Accumulate (using probabilistic OR: 1 - prod(1-p))
        p_expansion_from_any = 1 - (1 - p_expansion_from_any) * (1 - p_expand)
        p_becomes_port = 1 - (1 - p_becomes_port) * (1 - p_port_expand)
        p_becomes_ruin = 1 - (1 - p_becomes_ruin) * (1 - p_ruin_here)

    p_becomes_sett = max(0, p_expansion_from_any - p_becomes_port)

    # Base terrain probability (what happens if no settlement influence)
    if is_forest:
        p_base_forest = 0.85
        p_base_empty = 0.10
    elif terrain == 11:  # Plains
        p_base_empty = 0.90
        p_base_forest = 0.05
    else:
        p_base_empty = 0.95
        p_base_forest = 0.02

    # Final distribution: combine settlement influence with terrain base
    total_sett_influence = p_becomes_sett + p_becomes_port + p_becomes_ruin
    base_weight = max(0, 1.0 - total_sett_influence * 1.3)

    p = [0.0] * NC
    p[0] = base_weight * p_base_empty + (1 - base_weight) * 0.1  # empty
    p[1] = p_becomes_sett                                         # settlement
    p[2] = p_becomes_port                                         # port
    p[3] = p_becomes_ruin                                         # ruin
    p[4] = base_weight * p_base_forest + (1 - base_weight) * 0.05  # forest
    p[5] = 0.0                                                     # mountain

    return fnorm(p)


def build_predictions(state, sett_model, grid_obs=None):
    """Build full prediction grid for one seed."""
    grid = state["grid"]
    settlements = state["settlements"]
    dg_mat = dist_grid(settlements)

    preds = [[[0.0]*NC for _ in range(W)] for _ in range(H)]
    stats = {"model": 0, "jeffreys": 0, "spatial": 0}

    for y in range(H):
        for x in range(W):
            # If we have direct observations, use them
            obs = grid_obs.get((x, y), []) if grid_obs else []

            if len(obs) >= 3:
                # Jeffreys posterior: let data dominate
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1
                alpha = 0.5
                total = len(obs) + NC * alpha
                pred = [(obs_counts[c] + alpha) / total for c in range(NC)]
                preds[y][x] = fnorm(pred)
                stats["jeffreys"] += 1

            elif len(obs) >= 1:
                # Few observations: blend with model prediction
                obs_counts = [0] * NC
                for o in obs:
                    obs_counts[o] += 1
                model_pred = predict_cell(x, y, grid, sett_model, dg_mat)

                # Light prior weight — let observations have influence
                pw = 1.0
                pred = [(obs_counts[c] + pw * model_pred[c]) / (len(obs) + pw)
                        for c in range(NC)]
                preds[y][x] = fnorm(pred)
                stats["jeffreys"] += 1

            else:
                # No observations: try spatial borrowing, then use model
                borrowed = False
                if grid_obs:
                    pseudo_counts, total_w = spatial_borrow(x, y, grid_obs, grid, dg_mat)
                    if total_w >= 1.5:
                        model_pred = predict_cell(x, y, grid, sett_model, dg_mat)
                        eff_n = min(total_w * 0.5, 2.0)
                        norm_pseudo = [pseudo_counts[c] / total_w for c in range(NC)]
                        pred = [(eff_n * norm_pseudo[c] + 1.5 * model_pred[c]) / (eff_n + 1.5)
                                for c in range(NC)]
                        preds[y][x] = fnorm(pred)
                        stats["spatial"] += 1
                        borrowed = True

                if not borrowed:
                    preds[y][x] = fnorm(predict_cell(x, y, grid, sett_model, dg_mat))
                    stats["model"] += 1

    return preds, stats


def spatial_borrow(x, y, grid_obs, grid, dg):
    """Borrow observations from nearby observed cells with similar features."""
    tc = tcat(grid[y][x])
    d = dg[y][x]

    pseudo_counts = [0.0] * NC
    total_weight = 0.0

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

                n_tc = tcat(grid[ny][nx])
                n_d = dg[ny][nx]

                if n_tc != tc:
                    continue
                if abs(n_d - d) > 2:
                    continue

                dist = abs(ddx) + abs(ddy)
                w = 1.0 / (1 + dist)
                if abs(n_d - d) == 0:
                    w *= 1.3

                for o in grid_obs[(nx, ny)]:
                    pseudo_counts[o] += w
                    total_weight += w

    return pseudo_counts, total_weight


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=== Astar Island Solver v9 (Settlement Model + Physics) ===\n")

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

    # 4. Build settlement models from map topology
    print("\n[4] Building settlement survival models...")
    sett_models = []
    for seed_idx in range(n_seeds):
        model = build_settlement_model(states[seed_idx])
        sett_models.append(model)

        survs = [m["survival"] for m in model.values()]
        ports = [m["port_rate"] for m in model.values()]
        print(f"  Seed {seed_idx}: avg_survival={sum(survs)/len(survs):.2f}, "
              f"avg_port={sum(ports)/len(ports):.2f}, "
              f"min_surv={min(survs):.2f}, max_surv={max(survs):.2f}")

    if remaining <= 0:
        print("\n  No queries left — using model-only predictions")
        all_preds = []
        for seed_idx in range(n_seeds):
            preds, stats = build_predictions(states[seed_idx], sett_models[seed_idx])
            all_preds.append(preds)
            print(f"  Seed {seed_idx}: {stats}")
        submit(round_id, all_preds)
        check_results(round_id)
        return

    # 5. Allocate queries across seeds
    print(f"\n[5] Allocating {remaining} queries...")
    base = remaining // n_seeds
    alloc = [base] * n_seeds
    for i in range(remaining - sum(alloc)):
        alloc[i] += 1
    print(f"  Allocation: {alloc}")

    # 6. Run simulations with smart viewport placement
    print(f"\n[6] Running simulations...")
    all_grid_obs = []
    all_sett_snapshots = []

    for seed_idx in range(n_seeds):
        state = states[seed_idx]
        settlements = state["settlements"]
        n_q = alloc[seed_idx]

        # Select viewports to maximize settlement coverage
        n_vps = min(3, max(1, n_q // 3))
        vps = greedy_viewports(settlements, n_vps)

        # Count coverage
        sett_positions = [(s["x"], s["y"]) for s in settlements]
        covered = set()
        for vx, vy in vps:
            for sx, sy in sett_positions:
                if vx <= sx < vx+VP and vy <= sy < vy+VP:
                    covered.add((sx, sy))

        # Distribute queries across viewports — more on viewport 1
        queries = []
        if n_vps == 1:
            queries = [vps[0]] * n_q
        elif n_vps == 2:
            n1 = (n_q + 1) // 2
            n2 = n_q - n1
            queries = [vps[0]] * n1 + [vps[1]] * n2
        else:
            per = n_q // n_vps
            for i, vp in enumerate(vps):
                count = per + (1 if i < n_q - per * n_vps else 0)
                queries.extend([vp] * count)

        print(f"  Seed {seed_idx}: {n_q}q on {n_vps} vp(s), "
              f"covering {len(covered)}/{len(settlements)} settlements")

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

        n_cells = len(grid_obs)
        max_o = max((len(v) for v in grid_obs.values()), default=0)
        print(f"    → {n_cells} cells, max {max_o} obs/cell")

        all_grid_obs.append(grid_obs)
        all_sett_snapshots.append(sett_snapshots)

    # 7. Update settlement models with observed data
    print(f"\n[7] Updating models with observations...")
    for seed_idx in range(n_seeds):
        sett_models[seed_idx] = update_model_with_observations(
            sett_models[seed_idx],
            all_sett_snapshots[seed_idx],
            states[seed_idx]["settlements"]
        )
        survs = [m["survival"] for m in sett_models[seed_idx].values()]
        n_obs = sum(1 for m in sett_models[seed_idx].values() if m.get("observed", False))
        print(f"  Seed {seed_idx}: {n_obs} observed, avg_surv={sum(survs)/len(survs):.2f}")

    # 8. Build predictions
    print(f"\n[8] Building predictions...")
    all_preds = []
    for seed_idx in range(n_seeds):
        preds, stats = build_predictions(
            states[seed_idx],
            sett_models[seed_idx],
            all_grid_obs[seed_idx]
        )
        all_preds.append(preds)
        print(f"  Seed {seed_idx}: {stats}")

    # 9. Submit
    print(f"\n[9] Submitting...")
    submit(round_id, all_preds)

    # 10. Check results
    check_results(round_id)

    print("\nDone!")


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


def check_results(round_id):
    print(f"\n[*] Final check...")
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


if __name__ == "__main__":
    main()
