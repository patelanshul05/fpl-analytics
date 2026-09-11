#!/usr/bin/env python3

"""
FPL Transfer Finder
===================

Command-line transfer and player-selection tool using the same xP engine
as the Streamlit dashboard.

Examples:

    python fpl_transfer_finder.py

    python fpl_transfer_finder.py \
        --position MID \
        --max-price 8.5 \
        --lookahead 5

    python fpl_transfer_finder.py \
        --differentials

    python fpl_transfer_finder.py \
        --squad

    python fpl_transfer_finder.py \
        --team-id 152146
"""

import argparse
import sys

from fpl_common import (
    DEFAULT_TEAM_ID,
    Weights,
    build_player_rows,
    build_xp,
    fetch_squad_by_team_id,
    find_differentials,
    get_current_gameweek,
    load_fpl_data,
    score_rows,
    suggest_transfers,
)


def print_table(rows, top_n=20):

    rows = rows[:top_n]

    if not rows:
        print("No players matched.")
        return

    header = (
        f"{'Player':<20}"
        f"{'Team':<8}"
        f"{'Pos':<5}"
        f"{'£':<6}"
        f"{'GW xP':<8}"
        f"{'5GW xP':<9}"
        f"{'xP/£m':<8}"
        f"{'xMins':<8}"
        f"{'Own%':<8}"
    )

    print(header)
    print("-" * len(header))

    for row in rows:

        print(
            f"{row['name'][:19]:<20}"
            f"{row['team_short']:<8}"
            f"{row['position']:<5}"
            f"{row['price']:<6.1f}"
            f"{row.get('xp_next', 0):<8.2f}"
            f"{row.get('xp', 0):<9.2f}"
            f"{row.get('xp_per_million', 0):<8.2f}"
            f"{row.get('expected_minutes', 0):<8.0f}"
            f"{row['ownership']:<8.1f}"
        )

        if row.get("news"):
            print(
                f"   ⚠ {row['news']}"
            )


def print_transfers(
    swaps,
    top_n=10,
):

    if not swaps:
        print(
            "No positive projected-xP transfers found."
        )
        return

    header = (
        f"{'Sell':<20}"
        f"{'Buy':<20}"
        f"{'Pos':<5}"
        f"{'Cost Δ':<9}"
        f"{'xP Gain':<10}"
        f"{'Value Gain':<12}"
    )

    print(header)
    print("-" * len(header))

    for swap in swaps[:top_n]:

        print(
            f"{swap['out']['name'][:19]:<20}"
            f"{swap['in']['name'][:19]:<20}"
            f"{swap['out']['position']:<5}"
            f"{swap['cost_delta']:<9.1f}"
            f"{swap['gain']:<10.2f}"
            f"{swap['value_gain']:<12.2f}"
        )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "FPL transfer and player-selection "
            "analysis using projected points."
        )
    )

    parser.add_argument(
        "--team-id",
        type=int,
        default=DEFAULT_TEAM_ID,
        help="Your FPL team ID.",
    )

    parser.add_argument(
        "--position",
        choices=[
            "GKP",
            "DEF",
            "MID",
            "FWD",
        ],
        default=None,
    )

    parser.add_argument(
        "--max-price",
        type=float,
        default=None,
    )

    parser.add_argument(
        "--min-price",
        type=float,
        default=0.0,
    )

    parser.add_argument(
        "--lookahead",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--min-minutes",
        type=float,
        default=45.0,
    )

    parser.add_argument(
        "--top",
        type=int,
        default=20,
    )

    parser.add_argument(
        "--differentials",
        action="store_true",
        help="Show low-ownership differential picks.",
    )

    parser.add_argument(
        "--max-ownership",
        type=float,
        default=10.0,
    )

    parser.add_argument(
        "--transfers",
        action="store_true",
        help="Show recommended transfers.",
    )

    parser.add_argument(
        "--squad",
        action="store_true",
        help="Show your current squad.",
    )

    args = parser.parse_args()

    print(
        "Fetching live FPL data...",
        file=sys.stderr,
    )

    bootstrap, fixtures = load_fpl_data()

    teams = {
        team["id"]: team["name"]
        for team in bootstrap["teams"]
    }

    current_gw = get_current_gameweek(
        bootstrap["events"],
        prefer_next=True,
    )

    print(
        f"Planning Gameweek: {current_gw}",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # Build player model
    # ------------------------------------------------------------------

    rows = build_player_rows(
        bootstrap,
        fixtures,
        lookahead=args.lookahead,
        min_avg_minutes=args.min_minutes,
    )

    rows = score_rows(
        rows,
        Weights(),
    )

    rows = build_xp(
        rows,
        fixtures,
        teams,
        current_gw,
        args.lookahead,
    )

    # ------------------------------------------------------------------
    # Load squad
    # ------------------------------------------------------------------

    owned_picks = fetch_squad_by_team_id(
        args.team_id,
        current_gw,
    )

    owned_ids = set(
        owned_picks.keys()
    )

    for row in rows:
        row["is_owned"] = (
            row["id"] in owned_ids
        )

    squad_rows = [
        row
        for row in rows
        if row["is_owned"]
    ]

    # ------------------------------------------------------------------
    # Squad mode
    # ------------------------------------------------------------------

    if args.squad:

        print()
        print(
            f"YOUR SQUAD — GW{current_gw}"
        )
        print()

        squad_sorted = sorted(
            squad_rows,
            key=lambda row: row.get(
                "xp_next",
                0,
            ),
            reverse=True,
        )

        print_table(
            squad_sorted,
            args.top,
        )

        print()

    # ------------------------------------------------------------------
    # Differential mode
    # ------------------------------------------------------------------

    if args.differentials:

        differentials = find_differentials(
            rows,
            max_ownership=args.max_ownership,
            top_n=args.top,
        )

        print()
        print(
            f"DIFFERENTIALS — "
            f"≤{args.max_ownership:.1f}% ownership"
        )
        print()

        print_table(
            differentials,
            args.top,
        )

        print()

    # ------------------------------------------------------------------
    # Transfer mode
    # ------------------------------------------------------------------

    if args.transfers:

        bank = 0.0

        if squad_rows:

            # The public manager endpoint provides bank information.
            from fpl_common import (
                fetch_manager_overview,
            )

            manager = fetch_manager_overview(
                args.team_id
            )

            bank = (
                manager.get(
                    "bank",
                    0.0,
                )
                if manager
                else 0.0
            )

        swaps = suggest_transfers(
            squad_rows,
            rows,
            bank,
            top_n=args.top,
            metric="xp",
        )

        print()
        print(
            f"TRANSFER RECOMMENDATIONS — "
            f"next {args.lookahead} GWs"
        )
        print()

        print_transfers(
            swaps,
            args.top,
        )

        print()

    # ------------------------------------------------------------------
    # Standard player ranking
    # ------------------------------------------------------------------

    if (
        not args.differentials
        and not args.transfers
        and not args.squad
    ):

        candidates = []

        for row in rows:

            if args.position:
                if row["position"] != args.position:
                    continue

            if (
                args.max_price is not None
                and row["price"] > args.max_price
            ):
                continue

            if row["price"] < args.min_price:
                continue

            if (
                row["expected_minutes"]
                < args.min_minutes
            ):
                continue

            if not row["status_ok"]:
                continue

            if row["is_owned"]:
                continue

            candidates.append(row)

        candidates.sort(
            key=lambda row: row.get(
                "xp",
                0,
            ),
            reverse=True,
        )

        print()
        print(
            f"TOP TRANSFER TARGETS — "
            f"GW{current_gw}, "
            f"next {args.lookahead} GWs"
        )
        print()

        print_table(
            candidates,
            args.top,
        )

        print()


if __name__ == "__main__":
    main()
