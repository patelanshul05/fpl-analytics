"""
fpl_common.py
=============
Shared data-fetching and scoring engine for the fpl-analytics project.

Previously app.py, fpl_transfer_finder.py, and send_fpl_email.py each pulled
FPL data and computed metrics independently (and inconsistently — the email
script in particular ignored the scoring engine entirely and just emailed
"most transferred in this week", which rewards template/bandwagon picks
rather than good ones). Everything now goes through this module so all
three surfaces agree on: current gameweek, player metrics, fixture
difficulty, and the weighted composite score.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import requests

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
ENTRY_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/"
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

USER_AGENT = "fpl-analytics/3.0"

# Falls back to this if FPL_TEAM_ID isn't set anywhere (env var takes priority
# everywhere now instead of being hardcoded in three separate files).
DEFAULT_TEAM_ID = int(os.getenv("FPL_TEAM_ID", "152146"))


@dataclass
class Weights:
    """Composite score weights. Applied within each position group so, e.g.,
    defenders aren't penalized for having naturally lower xGI than forwards."""
    value: float = 0.15
    form: float = 0.20
    underlying: float = 0.30
    fixtures: float = 0.25
    ownership_penalty: float = 0.10


@dataclass
class CaptaincyWeights:
    """Separate, fixture-heavier weighting used only for captaincy — captaincy
    is a one-gameweek bet, so this-week's fixture and current form matter more
    than season-long value-for-money."""
    form: float = 0.40
    fixtures: float = 0.30
    underlying: float = 0.30


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
    """Min-max normalize a list to 0-1 range."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def load_fpl_data() -> tuple[dict, dict]:
    """Fetch bootstrap-static and fixtures in one call each."""
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
    """Manager name, overall rank/points, and bank (money in the bank, £M)."""
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
            "free_transfers": data.get("last_deadline_total_transfers"),
        }
    except requests.RequestException:
        return {}


def fetch_squad_by_team_id(team_id: int, current_gw: int) -> dict:
    """Returns {element_id: is_captain/is_vice/multiplier info} for the most
    recent gameweek we can get picks for (current, then falls back a week —
    picks for the upcoming GW aren't published until the previous one locks)."""
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


def calculate_fixture_score(fixtures: list, teams: dict, current_gw: int, lookahead: int) -> dict:
    """Accumulated fixture ease per team (Inverted difficulty: 5 = easiest, 1 = hardest).
    Naturally rewards Double Gameweeks (two fixtures both add ease) and
    scores Blank Gameweeks as 0 (no fixture in range = no ease added)."""
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
    """Ordered list of a single team's next fixtures, for squad fixture outlook,
    e.g. [{'gw': 4, 'opponent': 'ARS', 'home': True, 'difficulty': 4}, ...]."""
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


def build_player_rows(bootstrap: dict, fixtures: list, lookahead: int = 5,
                       min_avg_minutes: float = 45.0) -> list:
    """Core per-player metrics, unfiltered by ownership. Every row includes a
    'status_ok' flag (unavailable players are kept in the data but flagged,
    not silently dropped, so the caller can decide how to use that)."""
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    team_short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    current_gw = get_current_gameweek(bootstrap["events"])
    elapsed_gws = max(current_gw - 1, 1)
    fixture_scores = calculate_fixture_score(fixtures, teams, current_gw, lookahead)

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
        xgi = safe_float(el.get("expected_goal_involvements"))
        xgc = safe_float(el.get("expected_goals_conceded"))
        team_id = el.get("team")

        value = total_points / price if price > 0 else 0
        xgi_per90 = (xgi / minutes) * 90 if minutes > 0 else 0
        xgc_per90 = (xgc / minutes) * 90 if minutes > 0 else 0

        if position in ("GKP", "DEF"):
            underlying_metric = xgi_per90 - (xgc_per90 * 0.5)
        else:
            underlying_metric = xgi_per90

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
            "cost_change_event": el.get("cost_change_event", 0),
            "transfers_in_event": el.get("transfers_in_event", 0),
            "transfers_out_event": el.get("transfers_out_event", 0),
        })
    return rows


def score_rows(rows: list, weights: Weights = None) -> list:
    """Adds a 'score' key, normalized within each position group so positions
    with structurally different underlying numbers (e.g. GKP vs FWD) are
    compared fairly. Mutates and returns the same list."""
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
                weights.value * value_n[j]
                + weights.form * form_n[j]
                + weights.underlying * und_n[j]
                + weights.fixtures * fix_n[j]
                - weights.ownership_penalty * own_n[j]
            )
    return rows


def score_captaincy(rows: list, weights: CaptaincyWeights = None) -> list:
    """Separate fixture-heavy score for captaincy, normalized within position
    across the given rows (call this on just the owned squad)."""
    weights = weights or CaptaincyWeights()
    for pos in set(r["position"] for r in rows):
        idx = [i for i, r in enumerate(rows) if r["position"] == pos]
        form_n = normalize([rows[i]["form"] for i in idx])
        fix_n = normalize([rows[i]["fixture_score"] for i in idx])
        und_n = normalize([rows[i]["underlying_metric"] for i in idx])
        for j, i in enumerate(idx):
            rows[i]["captaincy_score"] = (
                weights.form * form_n[j]
                + weights.fixtures * fix_n[j]
                + weights.underlying * und_n[j]
            )
    return rows


def suggest_transfers(squad_rows: list, all_rows: list, bank: float,
                       max_suggestions_per_player: int = 1,
                       top_n: int = 3) -> list:
    """For each squad player, find the best-scoring unowned replacement in the
    same position affordable within (that player's price + bank). Returns the
    top_n swaps by score gain, sorted descending.

    This directly fixes the old email's biggest gap: it recommended players
    without ever checking whether they were an upgrade on someone you already
    own, or whether you could afford them.
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
            and r["score"] > out_player["score"]
        ]
        candidates.sort(key=lambda r: r["score"], reverse=True)
        for cand in candidates[:max_suggestions_per_player]:
            suggestions.append({
                "out": out_player,
                "in": cand,
                "score_gain": cand["score"] - out_player["score"],
                "cost_delta": cand["price"] - out_player["price"],
            })

    suggestions.sort(key=lambda s: s["score_gain"], reverse=True)
    return suggestions[:top_n]


def price_change_watch(rows: list, min_ownership: float = 0.5,
                        top_n: int = 5) -> dict:
    """Heuristic early-warning list based on today's net transfer momentum.
    This is NOT an exact price-change predictor (that requires tracking
    live transfer deltas against team-specific rise/fall thresholds, which
    the public API doesn't expose) — it's a directional signal: large net
    transfers in/out today, for a player who hasn't already moved today,
    tends to precede a price change within a day or two.
    """
    candidates = [
        r for r in rows
        if r["ownership"] >= min_ownership and r["cost_change_event"] == 0
    ]
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
