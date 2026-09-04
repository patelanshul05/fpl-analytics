#!/usr/bin/env python3
"""
FPL Transfer Target Finder
===========================
Ranks transfer targets by projected points (xP) over your lookahead window —
see fpl_common.py's module docstring for how the xP model works and its
limits. Legacy composite --score is still shown as a secondary column.

Usage:
  python fpl_transfer_finder.py --team-id YOUR_FPL_ID
  python fpl_transfer_finder.py --position MID --max-price 8.5 --lookahead 6
  python fpl_transfer_finder.py --differentials   # low-ownership, high-xP picks
"""

import argparse
import sys

from fpl_common import (
    DEFAULT_TEAM_ID, Weights, build_player_rows, build_xp, fetch_squad_by_team_id,
    find_differentials, get_current_gameweek, load_fpl_data, score_rows,
)

MY_SQUAD = {
    "Verbruggen", "Calafiori", "Mitchell", "O'Reilly", "Palmer",
    "Gibbs-White", "Anderson", "Tzolis", "Bruno G.", "Haaland",
    "João Pedro", "Dubravka", "Calvert-Lewin", "Robinson", "Davis",
}


def print_table(rows, top_n):
    header = (f"{'Player':<20}{'Team':<15}{'Pos':<5}{'£':<6}{'Form':<6}"
              f"{'xG':<6}{'xA':<6}{'SetPc':<7}{'xP':<7}{'Own%':<7}{'Score':<6}")
    print(header)
    print("-" * len(header))
    for r in rows[:top_n]:
        setpiece = "PEN" if r["is_penalty_taker"] else ("SP" if (r["is_corner_taker"] or r["is_freekick_taker"]) else "-")
        print(f"{r['name']:<20}{r['team']:<15}{r['position']:<5}"
              f"{r['price']:<6.1f}{r['form']:<6.1f}"
              f"{r['xg']:<6.2f}{r['xa']:<6.2f}{setpiece:<7}{r['xp']:<7.2f}{r['ownership']:<7.1f}"
              f"{r['score']:<6.3f}")
        if r["news"]:
            print(f"   ⚠ {r['news']}")


def main():
    parser = argparse.ArgumentParser(description="Rank FPL transfer targets by projected points")
    parser.add_argument("--position", choices=["GKP", "DEF", "MID", "FWD"], default=None)
    parser.add_argument("--max-price", type=float, default=None)
    parser.add_argument("--min-price", type=float, default=0.0)
    parser.add_argument("--lookahead", type=int, default=5)
    parser.add_argument("--min-avg-minutes", type=float, default=45.0)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)
    parser.add_argument("--exclude-none", action="store_true")
    parser.add_argument("--differentials", action="store_true",
                         help="Show low-ownership, high-xP picks instead of the standard ranking")
    parser.add_argument("--max-ownership", type=float, default=10.0,
                         help="Ownership ceiling for --differentials (default 10%%)")
    args = parser.parse_args()

    print("Fetching live FPL data...", file=sys.stderr)
    bootstrap, fixtures = load_fpl_data()
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    current_gw = get_current_gameweek(bootstrap["events"])

    rows = build_player_rows(bootstrap, fixtures, lookahead=args.lookahead,
                              min_avg_minutes=args.min_avg_minutes)
    rows = score_rows(rows, Weights())
    rows = build_xp(rows, fixtures, teams, current_gw, args.lookahead)

    owned_ids = set()
    if not args.exclude_none:
        owned_ids = set(fetch_squad_by_team_id(args.team_id, current_gw).keys())

    if args.differentials:
        diffs = find_differentials(rows, max_ownership=args.max_ownership, top_n=args.top)
        print(f"\nDifferentials — ≤{args.max_ownership}% owned, ranked by xP (Lookahead: {args.lookahead} GWs)\n")
        print_table(diffs, args.top)
        return

    filtered = []
    for r in rows:
        if args.position and r["position"] != args.position:
            continue
        if args.max_price and r["price"] > args.max_price:
            continue
        if r["price"] < args.min_price:
            continue
        if not r["meets_minutes_floor"] or not r["status_ok"]:
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

    filtered.sort(key=lambda r: r["xp"], reverse=True)
    print(f"\nGameweek {current_gw} Target Recommendations, by projected points (Lookahead: {args.lookahead} GWs)\n")
    print_table(filtered, args.top)


if __name__ == "__main__":
    main()
