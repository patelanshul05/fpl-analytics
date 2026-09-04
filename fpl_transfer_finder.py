#!/usr/bin/env python3
"""
FPL Transfer Target Finder
===========================
Ranks transfer targets using a weighted composite of value, form,
position-aware underlying stats, accumulated fixture ease, and an
ownership penalty (nudges away from heavy template picks).

Now a thin CLI over fpl_common.py — the scoring logic itself lives there
so app.py and send_fpl_email.py use the exact same numbers.

Usage:
  python fpl_transfer_finder.py --team-id YOUR_FPL_ID
  python fpl_transfer_finder.py --position MID --max-price 8.5 --lookahead 6
"""

import argparse
import sys

from fpl_common import (
    DEFAULT_TEAM_ID, Weights, build_player_rows, fetch_squad_by_team_id,
    get_current_gameweek, load_fpl_data, score_rows,
)

# Fallback squad list (by name) if the FPL API can't return picks for the
# given team-id yet (e.g. before GW1 picks lock).
MY_SQUAD = {
    "Verbruggen", "Calafiori", "Mitchell", "O'Reilly", "Palmer",
    "Gibbs-White", "Anderson", "Tzolis", "Bruno G.", "Haaland",
    "João Pedro", "Dubravka", "Calvert-Lewin", "Robinson", "Davis",
}


def main():
    parser = argparse.ArgumentParser(description="Rank FPL transfer targets")
    parser.add_argument("--position", choices=["GKP", "DEF", "MID", "FWD"], default=None)
    parser.add_argument("--max-price", type=float, default=None)
    parser.add_argument("--min-price", type=float, default=0.0)
    parser.add_argument("--lookahead", type=int, default=5)
    parser.add_argument("--min-avg-minutes", type=float, default=45.0,
                         help="Minimum average minutes played per elapsed gameweek")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID,
                         help="Your FPL Team ID to auto-exclude your squad (defaults to FPL_TEAM_ID env var)")
    parser.add_argument("--exclude-none", action="store_true",
                         help="Don't exclude your own squad from results")
    args = parser.parse_args()

    print("Fetching live FPL data...", file=sys.stderr)
    bootstrap, fixtures = load_fpl_data()
    current_gw = get_current_gameweek(bootstrap["events"])

    rows = build_player_rows(bootstrap, fixtures, lookahead=args.lookahead,
                              min_avg_minutes=args.min_avg_minutes)
    rows = score_rows(rows, Weights())

    owned_ids = set()
    if not args.exclude_none:
        owned_picks = fetch_squad_by_team_id(args.team_id, current_gw)
        owned_ids = set(owned_picks.keys())

    filtered = []
    for r in rows:
        if args.position and r["position"] != args.position:
            continue
        if args.max_price and r["price"] > args.max_price:
            continue
        if r["price"] < args.min_price:
            continue
        if not r["meets_minutes_floor"]:
            continue
        if not r["status_ok"]:
            continue
        if not args.exclude_none:
            if owned_ids and r["id"] in owned_ids:
                continue
            elif not owned_ids and r["name"] in MY_SQUAD:
                continue
        filtered.append(r)

    if not filtered:
        print("No players matched your filters.")
        return

    filtered.sort(key=lambda r: r["score"], reverse=True)

    print(f"\nGameweek {current_gw} Target Recommendations (Lookahead: {args.lookahead} GWs)\n")
    header = (f"{'Player':<20}{'Team':<15}{'Pos':<5}{'£':<6}{'Pts':<6}{'Form':<6}"
              f"{'xGI/90':<8}{'FixScore':<10}{'Own%':<7}{'Score':<6}")
    print(header)
    print("-" * len(header))
    for r in filtered[:args.top]:
        print(f"{r['name']:<20}{r['team']:<15}{r['position']:<5}"
              f"{r['price']:<6.1f}{r['total_points']:<6.0f}{r['form']:<6.1f}"
              f"{r['xgi_per90']:<8.2f}{r['fixture_score']:<10.1f}{r['ownership']:<7.1f}"
              f"{r['score']:<6.3f}")


if __name__ == "__main__":
    main()
