"""
fpl_common.py
=============
Shared data-fetching and analysis engine for the fpl-analytics project.

v3: adds a real expected-points (xP) projection model, set-piece taker
data, Double/Blank Gameweek detection with chip timing hints, an optimal
starting-XI + captain picker, and differential (low-ownership, high-upside)
identification. xP is now the primary metric behind transfer suggestions,
targets, and captaincy — a concrete "how many points is this worth" number
instead of an abstract composite score.

xP MODEL — HOW IT WORKS AND ITS LIMITS
---------------------------------------
For each of a player's fixtures in the lookahead window:
  - expected minutes: derived from their season minutes-per-elapsed-GW,
    heavily discounted if injured/suspended/flagged.
  - goal/assist rate: their season expected_goals / expected_assists per 90,
    scaled by an "attacking multiplier" from the fixture's difficulty
    rating (easier fixture -> more expected output, harder -> less).
  - clean sheet probability: a heuristic from the fixture's difficulty
    rating (not a full Poisson goals model — FPL's own 1-5 difficulty
    rating is used as the proxy for defensive matchup strength).
  - appearance points: 2 if likely to play 60+ mins, 1 if a late-sub /
    rotation risk profile, 0 if very unlikely to feature.
This is a reasonable directional model, not a professional statistical
one — it doesn't model bonus points, cards, or own goals, and the fixture
difficulty inputs are FPL's own rough 1-5 ratings rather than a bespoke
Elo/Poisson system. Treat xP as "which players project best", not as an
exact points guarantee.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
ENTRY_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/"
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
USER_AGENT = "fpl-analytics/3.0"

DEFAULT_TEAM_ID = int(os.getenv("FPL_TEAM_ID", "152146"))

GOAL_POINTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3

FORMATION_RULES = {  # (min, max) outfield players allowed by position in a starting XI
    "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3),
}


@dataclass
class Weights:
    """Legacy composite-score weights, still used as a secondary sanity
    metric alongside xP (e.g. the 'value' angle xP doesn't capture)."""
    value: float = 0.15
    form: float = 0.20
    underlying: float = 0.30
    fixtures: float = 0.25
    ownership_penalty: float = 0.10


# ---------------------------------------------------------------- fetching

def fetch_json(url: str, timeout: int = 15) -> dict:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.json()


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def normalize(values: list) -> list:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def load_fpl_data() -> tuple[dict, dict]:
    bootstrap = fetch_json(BOOTSTRAP_URL)
    fixtures = fetch_json(FIXTURES_URL)
    return bootstrap, fixtures


def get_current_gameweek(events: list) -> int:
    for event in events:
        if event.get("is_next"):
            return event["id"]
    for event in events:
        if event.get("is_current"):
            return event["id"]
    for event in events:
        if not event.get("finished"):
            return event["id"]
    return events[-1]["id"] if events else 1


def fetch_manager_overview(team_id: int) -> dict:
    try:
        resp = requests.get(ENTRY_URL.format(team_id=team_id), timeout=10,
                             headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return {
            "team_name": data.get("name", f"Team {team_id}"),
            "manager_name": f"{data.get('player_first_name', '')} {data.get('player_last_name', '')}".strip(),
            "overall_rank": data.get("summary_overall_rank"),
            "overall_points": data.get("summary_overall_points"),
            "bank": safe_float(data.get("last_deadline_bank")) / 10.0,
            "team_value": safe_float(data.get("last_deadline_value")) / 10.0,
        }
    except requests.RequestException:
        return {}


def fetch_squad_by_team_id(team_id: int, current_gw: int) -> dict:
    for gw in [current_gw, max(current_gw - 1, 1)]:
        url = PICKS_URL.format(team_id=team_id, gw=gw)
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                picks = resp.json().get("picks", [])
                if picks:
                    return {p["element"]: p for p in picks}
        except requests.RequestException:
            continue
    return {}


# ---------------------------------------------------------- fixture helpers

def calculate_fixture_score(fixtures: list, teams: dict, current_gw: int, lookahead: int) -> dict:
    """Accumulated fixture ease per team (inverted difficulty: 5=easiest gw, 1=hardest)."""
    upcoming = [
        f for f in fixtures
        if f.get("event") and current_gw <= f["event"] < current_gw + lookahead
    ]
    team_ease_sum = {team_id: 0.0 for team_id in teams}
    for fx in upcoming:
        th, ta = fx.get("team_h"), fx.get("team_a")
        thd = safe_float(fx.get("team_h_difficulty"), 3.0)
        tad = safe_float(fx.get("team_a_difficulty"), 3.0)
        if th in team_ease_sum:
            team_ease_sum[th] += (6.0 - thd)
        if ta in team_ease_sum:
            team_ease_sum[ta] += (6.0 - tad)
    return team_ease_sum


def get_team_upcoming_fixtures(fixtures: list, teams: dict, team_id: int,
                                current_gw: int, lookahead: int = 5) -> list:
    upcoming = [
        f for f in fixtures
        if f.get("event") and current_gw <= f["event"] < current_gw + lookahead
        and (f.get("team_h") == team_id or f.get("team_a") == team_id)
    ]
    upcoming.sort(key=lambda f: f["event"])
    out = []
    for fx in upcoming:
        is_home = fx.get("team_h") == team_id
        opponent_id = fx.get("team_a") if is_home else fx.get("team_h")
        difficulty = fx.get("team_h_difficulty") if is_home else fx.get("team_a_difficulty")
        out.append({
            "gw": fx["event"],
            "opponent": teams.get(opponent_id, "?"),
            "home": is_home,
            "difficulty": int(safe_float(difficulty, 3)),
        })
    return out


def detect_dgw_bgw(fixtures: list, teams: dict, current_gw: int, lookahead: int) -> dict:
    """Returns {team_id: {'dgw_gws': [...], 'bgw_gws': [...]}} for the lookahead window."""
    window = list(range(current_gw, current_gw + lookahead))
    result = {}
    for team_id in teams:
        counts = {gw: 0 for gw in window}
        for f in fixtures:
            gw = f.get("event")
            if gw in counts and (f.get("team_h") == team_id or f.get("team_a") == team_id):
                counts[gw] += 1
        result[team_id] = {
            "dgw_gws": [gw for gw, c in counts.items() if c > 1],
            "bgw_gws": [gw for gw, c in counts.items() if c == 0],
        }
    return result


# --------------------------------------------------------------- core rows

def build_player_rows(bootstrap: dict, fixtures: list, lookahead: int = 5,
                       min_avg_minutes: float = 45.0) -> list:
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    team_short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    current_gw = get_current_gameweek(bootstrap["events"])
    elapsed_gws = max(current_gw - 1, 1)
    fixture_scores = calculate_fixture_score(fixtures, teams, current_gw, lookahead)
    dgw_bgw = detect_dgw_bgw(fixtures, teams, current_gw, lookahead)

    rows = []
    for el in bootstrap["elements"]:
        position = POSITION_MAP.get(el.get("element_type"))
        if not position:
            continue

        price = safe_float(el.get("now_cost")) / 10.0
        minutes = safe_float(el.get("minutes"))
        avg_minutes_per_gw = minutes / elapsed_gws

        status = el.get("status", "a")
        chance = el.get("chance_of_playing_next_round")
        status_ok = not (status in ("i", "s", "u") and (chance is None or chance == 0))

        total_points = safe_float(el.get("total_points"))
        form = safe_float(el.get("form"))
        xg = safe_float(el.get("expected_goals"))
        xa = safe_float(el.get("expected_assists"))
        xgi = safe_float(el.get("expected_goal_involvements"))
        xgc = safe_float(el.get("expected_goals_conceded"))
        team_id = el.get("team")

        value = total_points / price if price > 0 else 0
        xgi_per90 = (xgi / minutes) * 90 if minutes > 0 else 0
        xgc_per90 = (xgc / minutes) * 90 if minutes > 0 else 0
        underlying_metric = (xgi_per90 - xgc_per90 * 0.5) if position in ("GKP", "DEF") else xgi_per90

        rows.append({
            "id": el.get("id"),
            "name": el.get("web_name", "Unknown"),
            "team": teams.get(team_id, "?"),
            "team_short": team_short.get(team_id, "?"),
            "team_id": team_id,
            "position": position,
            "price": price,
            "total_points": total_points,
            "form": form,
            "xg": xg,
            "xa": xa,
            "xgi_per90": xgi_per90,
            "underlying_metric": underlying_metric,
            "fixture_score": fixture_scores.get(team_id, 0.0),
            "ownership": safe_float(el.get("selected_by_percent")),
            "value": value,
            "minutes": minutes,
            "avg_mins": avg_minutes_per_gw,
            "meets_minutes_floor": avg_minutes_per_gw >= min_avg_minutes,
            "status": status,
            "status_ok": status_ok,
            "news": el.get("news", "") or "",
            "cost_change_event": el.get("cost_change_event", 0),
            "transfers_in_event": el.get("transfers_in_event", 0),
            "transfers_out_event": el.get("transfers_out_event", 0),
            "is_penalty_taker": el.get("penalties_order") == 1,
            "is_corner_taker": el.get("corners_and_indirect_freekicks_order") == 1,
            "is_freekick_taker": el.get("direct_freekicks_order") == 1,
            "dgw_gws": dgw_bgw.get(team_id, {}).get("dgw_gws", []),
            "bgw_gws": dgw_bgw.get(team_id, {}).get("bgw_gws", []),
        })
    return rows


def score_rows(rows: list, weights: Weights = None) -> list:
    """Legacy composite score, normalized within position — kept as a
    secondary 'value for money' signal alongside xP."""
    weights = weights or Weights()
    for pos in set(r["position"] for r in rows):
        idx = [i for i, r in enumerate(rows) if r["position"] == pos]
        value_n = normalize([rows[i]["value"] for i in idx])
        form_n = normalize([rows[i]["form"] for i in idx])
        und_n = normalize([rows[i]["underlying_metric"] for i in idx])
        fix_n = normalize([rows[i]["fixture_score"] for i in idx])
        own_n = normalize([rows[i]["ownership"] for i in idx])
        for j, i in enumerate(idx):
            rows[i]["score"] = (
                weights.value * value_n[j] + weights.form * form_n[j]
                + weights.underlying * und_n[j] + weights.fixtures * fix_n[j]
                - weights.ownership_penalty * own_n[j]
            )
    return rows


# ------------------------------------------------------------- xP engine

def _expected_start_probability(row: dict) -> float:
    avg_mins = row["avg_mins"]
    if avg_mins >= 60:
        p = 1.0
    elif avg_mins >= 30:
        p = 0.6
    elif avg_mins > 0:
        p = 0.25
    else:
        p = 0.0
    if not row["status_ok"]:
        p *= 0.3  # injured/suspended/flagged — heavily discounted, not zeroed
        # (chance_of_playing could be partial, e.g. "75%"), so this stays
        # conservative rather than assuming a guaranteed absence.
    return p


def build_xp(rows: list, fixtures: list, teams: dict, current_gw: int, lookahead: int) -> list:
    """Adds 'xp' (total projected points over the lookahead window) and
    'xp_breakdown' (per-fixture detail, including DGW/BGW awareness) to
    each row. See module docstring for the model and its limits."""
    for r in rows:
        team_id = r["team_id"]
        team_fixtures = [
            f for f in fixtures
            if f.get("event") and current_gw <= f["event"] < current_gw + lookahead
            and (f.get("team_h") == team_id or f.get("team_a") == team_id)
        ]
        team_fixtures.sort(key=lambda f: f["event"])

        p_start = _expected_start_probability(r)
        goals_rate_per90 = (r["xg"] / r["minutes"] * 90) if r["minutes"] > 0 else 0.0
        assists_rate_per90 = (r["xa"] / r["minutes"] * 90) if r["minutes"] > 0 else 0.0

        total_xp = 0.0
        breakdown = []
        for fx in team_fixtures:
            is_home = fx.get("team_h") == team_id
            opponent_id = fx.get("team_a") if is_home else fx.get("team_h")
            difficulty = safe_float(fx.get("team_h_difficulty") if is_home else fx.get("team_a_difficulty"), 3.0)

            attacking_mult = max(0.7, min(1.3, 1.3 - (difficulty - 1) * 0.15))
            cs_prob = max(0.05, min(0.55, 0.55 - (difficulty - 1) * 0.10))
            expected_minutes = p_start * 90
            minutes_frac = expected_minutes / 90

            pts_goals = goals_rate_per90 * minutes_frac * attacking_mult * GOAL_POINTS[r["position"]]
            pts_assists = assists_rate_per90 * minutes_frac * attacking_mult * ASSIST_POINTS
            cs_weight = 1.0 if expected_minutes >= 60 else 0.3
            pts_cs = cs_prob * cs_weight * CLEAN_SHEET_POINTS[r["position"]]
            pts_appearance = 2 * p_start if expected_minutes >= 60 else (1 * p_start if expected_minutes > 0 else 0)
            set_piece_bonus = 0.0
            if r["is_penalty_taker"]:
                set_piece_bonus += 0.35 * minutes_frac
            if r["is_corner_taker"] or r["is_freekick_taker"]:
                set_piece_bonus += 0.10 * minutes_frac

            fixture_xp = pts_goals + pts_assists + pts_cs + pts_appearance + set_piece_bonus
            total_xp += fixture_xp
            breakdown.append({
                "gw": fx["event"],
                "opponent": teams.get(opponent_id, "?"),
                "home": is_home,
                "difficulty": int(difficulty),
                "xp": round(fixture_xp, 2),
            })

        r["xp"] = round(total_xp, 2)
        r["xp_per_fixture"] = round(total_xp / len(team_fixtures), 2) if team_fixtures else 0.0
        r["xp_breakdown"] = breakdown
    return rows


# ------------------------------------------------------- transfers & picks

def suggest_transfers(squad_rows: list, all_rows: list, bank: float,
                       max_suggestions_per_player: int = 1, top_n: int = 3,
                       metric: str = "xp") -> list:
    """For each squad player, finds the best-projected unowned replacement in
    the same position affordable within (their price + bank). Ranked by xP
    gain over the lookahead window by default — a concrete 'this swap is
    worth +N points over the next M gameweeks' rather than an abstract score.
    """
    owned_ids = {r["id"] for r in squad_rows}
    suggestions = []
    for out_player in squad_rows:
        budget = out_player["price"] + bank
        candidates = [
            r for r in all_rows
            if r["position"] == out_player["position"]
            and r["id"] not in owned_ids
            and r["price"] <= budget
            and r["status_ok"]
            and r["meets_minutes_floor"]
            and r[metric] > out_player[metric]
        ]
        candidates.sort(key=lambda r: r[metric], reverse=True)
        for cand in candidates[:max_suggestions_per_player]:
            suggestions.append({
                "out": out_player,
                "in": cand,
                "gain": cand[metric] - out_player[metric],
                "cost_delta": cand["price"] - out_player["price"],
                "metric": metric,
            })
    suggestions.sort(key=lambda s: s["gain"], reverse=True)
    return suggestions[:top_n]


def price_change_watch(rows: list, min_ownership: float = 0.5, top_n: int = 5) -> dict:
    """Heuristic early-warning based on today's net transfer momentum — not
    an exact predictor, just a directional signal for players who haven't
    already moved price today."""
    candidates = [r for r in rows if r["ownership"] >= min_ownership and r["cost_change_event"] == 0]
    for r in candidates:
        r["net_transfers"] = r["transfers_in_event"] - r["transfers_out_event"]
    rising = sorted(candidates, key=lambda r: r["net_transfers"], reverse=True)[:top_n]
    falling = sorted(candidates, key=lambda r: r["net_transfers"])[:top_n]
    already_moved = [r for r in rows if r["cost_change_event"] != 0]
    return {
        "rising_soon": [r for r in rising if r["net_transfers"] > 0],
        "falling_soon": [r for r in falling if r["net_transfers"] < 0],
        "already_moved_today": already_moved,
    }


def find_differentials(rows: list, max_ownership: float = 10.0, top_n: int = 8) -> list:
    """Low-ownership, high-xP players by position — picks that could
    separate you from your mini-league if they come off, since most of
    the league won't have them."""
    pool = [r for r in rows if r["ownership"] <= max_ownership
            and r["status_ok"] and r["meets_minutes_floor"]]
    pool.sort(key=lambda r: r["xp"], reverse=True)
    return pool[:top_n]


def pick_starting_xi(squad_rows: list, current_gw: int) -> dict:
    """Picks the highest-projected valid starting XI from a 15-man squad for
    THIS gameweek specifically (uses each player's xp for current_gw only,
    from their xp_breakdown — a bench-warmer with a great fixture next week
    still sits if they've got nothing this week), plus captain/vice.

    Falls back to 0 projected points for anyone with a Blank Gameweek this
    week (no fixture in their breakdown for current_gw).
    """
    def this_week_xp(r):
        for fx in r.get("xp_breakdown", []):
            if fx["gw"] == current_gw:
                return fx["xp"]
        return 0.0

    for r in squad_rows:
        r["_this_gw_xp"] = this_week_xp(r)

    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for r in squad_rows:
        by_pos[r["position"]].append(r)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda r: r["_this_gw_xp"], reverse=True)

    if not by_pos["GKP"]:
        return {"starting_xi": [], "bench": squad_rows, "captain": None, "vice_captain": None}

    best_total = -1
    best_combo = None
    for def_n in range(FORMATION_RULES["DEF"][0], FORMATION_RULES["DEF"][1] + 1):
        for mid_n in range(FORMATION_RULES["MID"][0], FORMATION_RULES["MID"][1] + 1):
            fwd_n = 10 - def_n - mid_n
            if not (FORMATION_RULES["FWD"][0] <= fwd_n <= FORMATION_RULES["FWD"][1]):
                continue
            if def_n > len(by_pos["DEF"]) or mid_n > len(by_pos["MID"]) or fwd_n > len(by_pos["FWD"]):
                continue
            combo = (
                by_pos["GKP"][:1] + by_pos["DEF"][:def_n]
                + by_pos["MID"][:mid_n] + by_pos["FWD"][:fwd_n]
            )
            total = sum(p["_this_gw_xp"] for p in combo)
            if total > best_total:
                best_total = total
                best_combo = combo

    if best_combo is None:  # squad doesn't have enough players in some position
        best_combo = by_pos["GKP"][:1] + by_pos["DEF"][:3] + by_pos["MID"][:2] + by_pos["FWD"][:1]

    starting_ids = {p["id"] for p in best_combo}
    bench = [r for r in squad_rows if r["id"] not in starting_ids]
    bench.sort(key=lambda r: (r["position"] != "GKP", -r["_this_gw_xp"]))

    ranked_starters = sorted(best_combo, key=lambda r: r["_this_gw_xp"], reverse=True)
    captain = ranked_starters[0] if ranked_starters else None
    vice_captain = ranked_starters[1] if len(ranked_starters) > 1 else None

    return {
        "starting_xi": sorted(best_combo, key=lambda r: (r["position"] != "GKP", r["position"], -r["_this_gw_xp"])),
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "projected_points": round(best_total, 1),
    }


def build_chip_hints(rows: list, squad_rows: list, current_gw: int, lookahead: int,
                      bank: float = 0.0) -> list:
    """Heuristic chip-timing nudges — not a strict recommendation, just
    flags worth your attention:
      - Wildcard: your squad is leaving a lot of projected points on the
        table vs affordable replacements.
      - Bench Boost: several of your squad share a Double Gameweek.
      - Triple Captain: your best captain candidate has a Double Gameweek.
      - Free Hit: your squad is hit hard by a Blank Gameweek.
    """
    hints = []
    if not squad_rows:
        return hints

    swaps = suggest_transfers(squad_rows, rows, bank=bank, top_n=5, metric="xp")
    total_gain = sum(s["gain"] for s in swaps)
    if total_gain >= 8.0:
        hints.append(
            f"Wildcard worth considering: your best available transfers add up to "
            f"roughly +{total_gain:.1f} projected points over the next {lookahead} GWs."
        )

    dgw_counts = {}
    for r in squad_rows:
        for gw in r.get("dgw_gws", []):
            dgw_counts[gw] = dgw_counts.get(gw, 0) + 1
    for gw, count in dgw_counts.items():
        if count >= 3:
            hints.append(f"Bench Boost candidate: {count} of your squad have a Double Gameweek in GW{gw}.")

    best = max(squad_rows, key=lambda r: r["xp"], default=None)
    if best and best.get("dgw_gws"):
        hints.append(
            f"Triple Captain candidate: {best['name']} has a Double Gameweek "
            f"in GW{best['dgw_gws'][0]} and projects as your top points scorer."
        )

    bgw_counts = {}
    for r in squad_rows:
        for gw in r.get("bgw_gws", []):
            bgw_counts[gw] = bgw_counts.get(gw, 0) + 1
    for gw, count in bgw_counts.items():
        if count >= 5:
            hints.append(f"Free Hit candidate: {count} of your squad have no fixture in GW{gw} (Blank Gameweek).")

    return hints
