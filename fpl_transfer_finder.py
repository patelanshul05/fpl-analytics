#!/usr/bin/env python3
"""
FPL Transfer Target Finder (Enhanced)
=====================================
Pulls live data from the FPL API and ranks transfer targets using:
  - Value (Total points per million)
  - Form (FPL rolling form)
  - Position-Aware Underlying Stats (xGI/90 for attackers, xGI - xGC for defenders)
  - Accumulated Fixture Ease (Accounts for Double & Blank Gameweeks)
  - Ownership penalty (Optional nudge away from heavy template picks)

Usage:
    python fpl_transfer_finder.py --team-id YOUR_FPL_ID
    python fpl_transfer_finder.py --position MID --max-price 8.5 --lookahead 6
"""

import argparse
import sys
from dataclasses import dataclass

try:
    import requests
except ImportError:
    sys.exit("This script needs the 'requests' library: pip install requests")

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Fallback squad list if --team-id is not passed
MY_SQUAD = {
    "Verbruggen", "Calafiori", "Mitchell", "O'Reilly", "Palmer",
    "Gibbs-White", "Anderson", "Tzolis", "Bruno G.", "Haaland",
    "João Pedro", "Dubravka", "Calvert-Lewin", "Robinson", "Davis",
}


@dataclass
class Weights:
    value: float = 0.15
    form: float = 0.20
    underlying: float = 0.30
    fixtures: float = 0.25
    ownership_penalty: float = 0.10


def fetch_json(url: str) -> dict:
    resp = requests.get(url, timeout=15, headers={"User-Agent": "fpl-transfer-finder/2.0"})
    resp.raise_for_status()
    return resp.json()


def safe_float(value, default=0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


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


def fetch_squad_by_team_id(team_id: int, current_gw: int) -> set:
    """Fetch user's current squad player IDs directly from FPL API."""
    for gw in [current_gw, max(current_gw - 1, 1)]:
        url = f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "fpl-transfer-finder/2.0"})
            if resp.status_code == 200:
                picks = resp.json().get("picks", [])
                return {p["element"] for p in picks}
        except Exception:
            continue
    return set()


def calculate_fixture_score(fixtures: list, teams: dict, current_gw: int, lookahead: int) -> dict:
    """Calculates accumulated fixture potential (Inverted Difficulty: 5 easy, 1 hard).
    Correctly handles Double Gameweeks (adds ease) and Blank Gameweeks (score = 0)."""
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


def normalize(values: list) -> list:
    """Min-max normalize a list to 0-1 range."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def main():
    parser = argparse.ArgumentParser(description="Rank FPL transfer targets")
    parser.add_argument("--position", choices=["GKP", "DEF", "MID", "FWD"], default=None)
    parser.add_argument("--max-price", type=float, default=None)
    parser.add_argument("--min-price", type=float, default=0.0)
    parser.add_argument("--lookahead", type=int, default=5)
    parser.add_argument("--min-avg-minutes", type=float, default=45.0,
                        help="Minimum average minutes played per elapsed gameweek")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--team-id", type=int, default=None, help="Your FPL Team ID to auto-exclude your squad")
    parser.add_argument("--exclude-none", action="store_true")
    args = parser.parse_args()

    print("Fetching live FPL data...", file=sys.stderr)
    bootstrap = fetch_json(BOOTSTRAP_URL)
    fixtures = fetch_json(FIXTURES_URL)

    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    current_gw = get_current_gameweek(bootstrap["events"])
    elapsed_gws = max(current_gw - 1, 1)

    fixture_scores = calculate_fixture_score(fixtures, teams, current_gw, args.lookahead)

    owned_element_ids = set()
    if args.team_id and not args.exclude_none:
        owned_element_ids = fetch_squad_by_team_id(args.team_id, current_gw)

    rows = []
    for el in bootstrap["elements"]:
        position = POSITION_MAP.get(el.get("element_type"))
        if not position or (args.position and position != args.position):
            continue

        price = safe_float(el.get("now_cost")) / 10.0
        if (args.max_price and price > args.max_price) or price < args.min_price:
            continue

        element_id = el.get("id")
        web_name = el.get("web_name", "Unknown")

        if not args.exclude_none:
            if owned_element_ids and element_id in owned_element_ids:
                continue
            elif not owned_element_ids and web_name in MY_SQUAD:
                continue

        status = el.get("status", "a")
        chance = el.get("chance_of_playing_next_round")
        if status in ("i", "s", "u") and (chance is None or chance == 0):
            continue

        minutes = safe_float(el.get("minutes"))
        avg_minutes_per_gw = minutes / elapsed_gws
        if avg_minutes_per_gw < args.min_avg_minutes:
            continue

        total_points = safe_float(el.get("total_points"))
        form = safe_float(el.get("form"))
        xgi = safe_float(el.get("expected_goal_involvements"))
        xgc = safe_float(el.get("expected_goals_conceded"))
        team_id = el.get("team")

        # Metric calculations
        value = total_points / price if price > 0 else 0
        xgi_per90 = (xgi / minutes) * 90 if minutes > 0 else 0
        xgc_per90 = (xgc / minutes) * 90 if minutes > 0 else 0

        # Position-aware underlying metric: penalize high xGC for defenders/goalkeepers
        if position in ("GKP", "DEF"):
            underlying_metric = xgi_per90 - (xgc_per90 * 0.5)
        else:
            underlying_metric = xgi_per90

        ownership = safe_float(el.get("selected_by_percent"))
        fix_score = fixture_scores.get(team_id, 0.0)

        rows.append({
            "id": element_id,
            "name": web_name,
            "team": teams.get(team_id, "?"),
            "position": position,
            "price": price,
            "total_points": total_points,
            "form": form,
            "xgi_per90": xgi_per90,
            "underlying_metric": underlying_metric,
            "fixture_score": fix_score,
            "ownership": ownership,
            "value": value,
            "minutes": minutes,
            "avg_mins": avg_minutes_per_gw
        })

    if not rows:
        print("No players matched your filters.")
        return

    weights = Weights()

    # Normalize within position groups so defenders aren't penalized for lower xGI
    for pos in set(r["position"] for r in rows):
        pos_indices = [i for i, r in enumerate(rows) if r["position"] == pos]

        value_n = normalize([rows[i]["value"] for i in pos_indices])
        form_n = normalize([rows[i]["form"] for i in pos_indices])
        und_n = normalize([rows[i]["underlying_metric"] for i in pos_indices])
        fix_n = normalize([rows[i]["fixture_score"] for i in pos_indices])
        own_n = normalize([rows[i]["ownership"] for i in pos_indices])

        for idx, i in enumerate(pos_indices):
            rows[i]["score"] = (
                weights.value * value_n[idx]
                + weights.form * form_n[idx]
                + weights.underlying * und_n[idx]
                + weights.fixtures * fix_n[idx]
                - weights.ownership_penalty * own_n[idx]
            )

    rows.sort(key=lambda r: r["score"], reverse=True)

    print(f"\nGameweek {current_gw} Target Recommendations (Lookahead: {args.lookahead} GWs)\n")
    header = f"{'Player':<20}{'Team':<15}{'Pos':<5}{'£':<6}{'Pts':<6}{'Form':<6}{'xGI/90':<8}{'FixScore':<10}{'Own%':<7}{'Score':<6}"
    print(header)
    print("-" * len(header))
    for r in rows[:args.top]:
        print(f"{r['name']:<20}{r['team']:<15}{r['position']:<5}"
              f"{r['price']:<6.1f}{r['total_points']:<6.0f}{r['form']:<6.1f}"
              f"{r['xgi_per90']:<8.2f}{r['fixture_score']:<10.1f}{r['ownership']:<7.1f}"
              f"{r['score']:<6.3f}")


if __name__ == "__main__":
    main()
