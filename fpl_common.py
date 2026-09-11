"""
fpl_common.py
=============

Shared FPL data, squad synchronisation, expected-points and team-selection
engine.

IMPORTANT SQUAD LOGIC
---------------------
The manager squad is NOT inferred from the next Gameweek.

Instead we:
1. Determine the active and next Gameweek.
2. Fetch the manager's transfer history.
3. Fetch the latest available GW picks.
4. Identify the latest GW for which picks are actually available.
5. Expose squad metadata so the UI can show exactly which GW/source was used.

This prevents the common problem where transfers made after the previous
deadline are invisible to the dashboard.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

import requests


# ============================================================================
# API
# ============================================================================

BASE_URL = "https://fantasy.premierleague.com/api"

BOOTSTRAP_URL = f"{BASE_URL}/bootstrap-static/"
FIXTURES_URL = f"{BASE_URL}/fixtures/"
ENTRY_URL = f"{BASE_URL}/entry/{{team_id}}/"
HISTORY_URL = f"{BASE_URL}/entry/{{team_id}}/history/"
TRANSFERS_URL = f"{BASE_URL}/entry/{{team_id}}/transfers/"
PICKS_URL = f"{BASE_URL}/entry/{{team_id}}/event/{{gw}}/picks/"

POSITION_MAP = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}

DEFAULT_TEAM_ID = int(
    os.getenv(
        "FPL_TEAM_ID",
        "152146",
    )
)

USER_AGENT = "fpl-analytics/5.0"

GOAL_POINTS = {
    "GKP": 10,
    "DEF": 6,
    "MID": 5,
    "FWD": 4,
}

CLEAN_SHEET_POINTS = {
    "GKP": 4,
    "DEF": 4,
    "MID": 1,
    "FWD": 0,
}

ASSIST_POINTS = 3


@dataclass
class Weights:
    value: float = 0.15
    form: float = 0.20
    underlying: float = 0.30
    fixtures: float = 0.25
    ownership_penalty: float = 0.10


# ============================================================================
# BASIC HELPERS
# ============================================================================

def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp(
    value: float,
    low: float,
    high: float,
) -> float:
    return max(
        low,
        min(high, value),
    )


def normalize(
    values: list[float],
) -> list[float]:

    if not values:
        return []

    low = min(values)
    high = max(values)

    if high - low < 1e-9:
        return [0.5] * len(values)

    return [
        (value - low) / (high - low)
        for value in values
    ]


# ============================================================================
# HTTP
# ============================================================================

def fetch_json(
    url: str,
    timeout: int = 20,
):
    """
    Fetch JSON from the public FPL API.

    We deliberately do not use a long-lived cache here. The dashboard
    controls caching and can force a refresh.
    """

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    return response.json()


# ============================================================================
# CORE FPL DATA
# ============================================================================

def load_fpl_data() -> tuple[dict, list]:

    bootstrap = fetch_json(
        BOOTSTRAP_URL
    )

    fixtures = fetch_json(
        FIXTURES_URL
    )

    return bootstrap, fixtures


# ============================================================================
# GAMEWEEK HANDLING
# ============================================================================

def get_active_gameweek(
    events: list,
) -> int:
    """
    Return the Gameweek currently being played / most recently active.

    This is different from the planning Gameweek.
    """

    for event in events:

        if event.get("is_current"):

            return safe_int(
                event.get("id"),
                1,
            )

    # If there isn't an explicitly current GW, find the most recent
    # unfinished/started event.
    unfinished = [
        event
        for event in events
        if not event.get("finished")
    ]

    if unfinished:

        return safe_int(
            unfinished[0].get("id"),
            1,
        )

    if events:

        return safe_int(
            events[-1].get("id"),
            1,
        )

    return 1


def get_next_gameweek(
    events: list,
) -> int:
    """
    Return the next Gameweek for which planning is required.
    """

    for event in events:

        if event.get("is_next"):

            return safe_int(
                event.get("id"),
                1,
            )

    # Fallback: first unfinished event.
    for event in events:

        if not event.get("finished"):

            return safe_int(
                event.get("id"),
                1,
            )

    return get_active_gameweek(events)


def get_current_gameweek(
    events: list,
    prefer_next: bool = True,
) -> int:
    """
    Backwards-compatible helper.

    Existing app.py expects this function.

    For FPL team-selection purposes, prefer_next=True returns the upcoming
    planning Gameweek.
    """

    if prefer_next:

        return get_next_gameweek(
            events
        )

    return get_active_gameweek(
        events
    )


# ============================================================================
# MANAGER PROFILE
# ============================================================================

def fetch_manager_overview(
    team_id: int,
) -> dict:

    try:

        data = fetch_json(
            ENTRY_URL.format(
                team_id=team_id
            )
        )

        return {
            "team_name": data.get(
                "name",
                f"Team {team_id}",
            ),
            "manager_name": (
                f"{data.get('player_first_name', '')} "
                f"{data.get('player_last_name', '')}"
            ).strip(),
            "overall_rank": data.get(
                "summary_overall_rank"
            ),
            "overall_points": data.get(
                "summary_overall_points"
            ),
            "bank": (
                safe_float(
                    data.get(
                        "last_deadline_bank"
                    )
                )
                / 10.0
            ),
            "team_value": (
                safe_float(
                    data.get(
                        "last_deadline_value"
                    )
                )
                / 10.0
            ),
            "current_event": data.get(
                "current_event"
            ),
        }

    except requests.RequestException:

        return {}


# ============================================================================
# MANAGER HISTORY
# ============================================================================

def fetch_manager_history(
    team_id: int,
) -> dict:

    try:

        return fetch_json(
            HISTORY_URL.format(
                team_id=team_id
            )
        )

    except requests.RequestException:

        return {}


# ============================================================================
# TRANSFER HISTORY
# ============================================================================

def fetch_transfer_history(
    team_id: int,
) -> list:
    """
    Return the manager's current-season transfer history.

    Each transfer normally contains:

        element_in
        element_out
        event
        time
    """

    try:
        data = fetch_json(
            TRANSFERS_URL.format(
                team_id=team_id
            )
        )
    except (requests.RequestException, ValueError):
        return []

    return data if isinstance(data, list) else []


def get_latest_transfer_event(
    transfers: list,
) -> Optional[int]:

    if not transfers:
        return None

    events = [
        safe_int(
            transfer.get("event")
        )
        for transfer in transfers
        if transfer.get("event") is not None
    ]

    if not events:
        return None

    return max(events)


# ============================================================================
# GAMEWEEK PICKS
# ============================================================================

def fetch_picks_for_gameweek(
    team_id: int,
    gw: int,
) -> Optional[dict]:
    """
    Fetch picks for a specific Gameweek.

    Returns the complete API response rather than only the player dictionary.
    This is important because we need entry_history and pick positions.
    """

    if gw < 1:
        return None

    try:
        data = fetch_json(
            PICKS_URL.format(
                team_id=team_id,
                gw=gw,
            )
        )
    except (requests.RequestException, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    picks = data.get("picks")

    if not isinstance(picks, list) or not picks:
        return None

    return data


def _extract_pick_map(
    picks_response: dict,
) -> dict:

    picks = picks_response.get(
        "picks",
        []
    )

    return {
        pick["element"]: pick
        for pick in picks
        if pick.get("element") is not None
    }


# ============================================================================
# ROBUST CURRENT SQUAD SYNCHRONISATION
# ============================================================================

def fetch_squad_state(
    team_id: int,
    events: Optional[list] = None,
    max_gw_search: int = 38,
) -> dict:
    """
    Return the manager's most current 15-player squad.

    FPL exposes squads as gameweek snapshots.  Transfers may appear in the
    transfer history before the corresponding picks endpoint is refreshed.
    Candidate snapshots are therefore checked against transfer history and,
    when necessary, completed transfers are applied to the newest usable
    snapshot.  This prevents the caller receiving a knowingly stale squad.

    Returned dictionary:

        {
            "picks": {element_id: pick},
            "gameweek": int | None,
            "source": str,
            "active_gameweek": int,
            "next_gameweek": int,
            "latest_transfer_event": int | None,
            "latest_transfer_time": str | None,
            "transfers": [...],
            "entry_history": {...},
            "active_chip": ...,
            "pick_count": 15,
            "squad_is_current": bool,
            "squad_reconstructed": bool,
        }
    """

    if events is None:

        try:

            bootstrap = fetch_json(
                BOOTSTRAP_URL
            )

            events = bootstrap.get(
                "events",
                []
            )

        except requests.RequestException:

            events = []

    active_gw = get_active_gameweek(
        events
    )

    next_gw = get_next_gameweek(
        events
    )

    transfers = sorted(
        fetch_transfer_history(team_id),
        key=lambda transfer: (
            safe_int(transfer.get("event")),
            str(transfer.get("time", "")),
        ),
    )

    latest_transfer_event = (
        get_latest_transfer_event(
            transfers
        )
    )

    latest_transfer_time = None

    if transfers:

        transfers_sorted = sorted(
            transfers,
            key=lambda transfer: (
                transfer.get(
                    "time",
                    "",
                )
            ),
            reverse=True,
        )

        latest_transfer_time = (
            transfers_sorted[0].get(
                "time"
            )
        )

    # Check planning GWs first, then recent fallbacks.  Do not scan an entire
    # season: an endpoint that has never existed is not a better candidate.
    candidate_gws = []

    for gw in (next_gw, active_gw, latest_transfer_event):
        gw = safe_int(gw)

        if 1 <= gw <= max_gw_search and gw not in candidate_gws:
            candidate_gws.append(gw)

    highest_gw = max(candidate_gws, default=1)

    for gw in range(highest_gw - 1, max(highest_gw - 5, 0), -1):
        if gw not in candidate_gws:
            candidate_gws.append(gw)

    snapshots = {}

    for gw in candidate_gws:
        response = fetch_picks_for_gameweek(team_id, gw)

        if response is not None:
            snapshots[gw] = response

    # ------------------------------------------------------------------
    # No squad found.
    # ------------------------------------------------------------------

    if not snapshots:

        return {
            "picks": {},
            "gameweek": None,
            "source": "none",
            "active_gameweek": active_gw,
            "next_gameweek": next_gw,
            "latest_transfer_event": latest_transfer_event,
            "latest_transfer_time": latest_transfer_time,
            "transfers": transfers,
            "entry_history": {},
            "active_chip": None,
            "pick_count": 0,
            "squad_is_current": False,
            "squad_reconstructed": False,
        }

    transfers_by_gw = {}

    for transfer in transfers:
        gw = safe_int(transfer.get("event"))

        if gw >= 1:
            transfers_by_gw[gw] = transfers_by_gw.get(gw, 0) + 1

    # Prefer a snapshot whose own transfer count accounts for its event,
    # while retaining the natural preference for the next/current GW.
    selected_gw = None
    selected_response = None
    selected_score = -10 ** 9

    for gw, response in snapshots.items():
        entry_history = response.get("entry_history") or {}
        snapshot_transfers = safe_int(entry_history.get("event_transfers"))
        known_transfers = transfers_by_gw.get(gw, 0)
        score = gw

        if snapshot_transfers >= known_transfers:
            score += 100
        if gw == next_gw:
            score += 50
        if gw == active_gw:
            score += 25

        if score > selected_score:
            selected_gw = gw
            selected_response = response
            selected_score = score

    raw_picks = selected_response.get("picks", [])
    picks = _extract_pick_map(selected_response)
    reconstructed = False

    # Apply transfers that the chosen snapshot demonstrably does not include.
    # Working chronologically preserves multi-transfer sequences in one GW.
    for transfer in transfers:
        transfer_gw = safe_int(transfer.get("event"))
        element_in = safe_int(transfer.get("element_in"))
        element_out = safe_int(transfer.get("element_out"))

        if transfer_gw < selected_gw or not element_in or not element_out:
            continue

        if element_in in picks and element_out not in picks:
            continue

        outgoing_pick = picks.pop(element_out, None)

        if outgoing_pick is None:
            continue

        replacement_pick = dict(outgoing_pick)
        replacement_pick["element"] = element_in
        picks[element_in] = replacement_pick
        reconstructed = True

    entry_history = selected_response.get("entry_history") or {}
    snapshot_transfer_count = safe_int(entry_history.get("event_transfers"))
    known_transfer_count = transfers_by_gw.get(selected_gw, 0)
    squad_is_current = (
        len(picks) == 15
        and (latest_transfer_event is None or selected_gw >= latest_transfer_event or reconstructed)
        and (snapshot_transfer_count >= known_transfer_count or reconstructed)
    )

    source = f"entry/{team_id}/event/{selected_gw}/picks"

    return {
        "picks": picks,
        "gameweek": selected_gw,
        "source": source,
        "active_gameweek": active_gw,
        "next_gameweek": next_gw,
        "latest_transfer_event": latest_transfer_event,
        "latest_transfer_time": latest_transfer_time,
        "transfers": transfers,
        "entry_history": entry_history,
        "active_chip": selected_response.get("active_chip"),
        "pick_count": len(picks),
        "squad_is_current": squad_is_current,
        "squad_reconstructed": reconstructed,
        "snapshot_transfer_count": snapshot_transfer_count,
        "known_transfer_count": known_transfer_count,
        "raw_picks": raw_picks,
    }


def fetch_squad_by_team_id(
    team_id: int,
    current_gw: Optional[int] = None,
    force_previous: bool = False,
) -> dict:
    """
    Backwards-compatible wrapper used by app.py and the CLI.

    IMPORTANT:
    The argument called current_gw is retained for compatibility, but the
    actual squad GW is determined from the FPL manager's latest available
    picks/transfer state.

    Returns the player->pick mapping expected by the existing application.
    """

    # current_gw and force_previous are retained for callers using the older
    # public signature.  Fresh event data is intentionally used instead.
    # Fetch bootstrap directly: squad synchronisation must not fail merely
    # because the unrelated fixtures endpoint is temporarily unavailable.
    try:
        bootstrap = fetch_json(BOOTSTRAP_URL)
        events = bootstrap.get("events", [])
    except (requests.RequestException, ValueError):
        events = None

    state = fetch_squad_state(
        team_id,
        events=events,
    )

    return state.get("picks", {})


# ============================================================================
# FIXTURE HELPERS
# ============================================================================

def fixture_difficulty_multiplier(
    difficulty: float,
    attacking: bool = True,
) -> float:

    difficulty = clamp(
        difficulty,
        1.0,
        5.0,
    )

    if attacking:

        mapping = {
            1: 1.18,
            2: 1.08,
            3: 1.00,
            4: 0.90,
            5: 0.80,
        }

    else:

        mapping = {
            1: 0.78,
            2: 0.88,
            3: 1.00,
            4: 1.12,
            5: 1.25,
        }

    return mapping.get(
        int(round(difficulty)),
        1.0,
    )


def calculate_fixture_score(
    fixtures: list,
    teams: dict,
    current_gw: int,
    lookahead: int,
) -> dict:

    scores = {
        team_id: 0.0
        for team_id in teams
    }

    for fixture in fixtures:

        gw = fixture.get(
            "event"
        )

        if not gw:
            continue

        if not (
            current_gw
            <= gw
            < current_gw + lookahead
        ):
            continue

        home = fixture.get(
            "team_h"
        )

        away = fixture.get(
            "team_a"
        )

        home_difficulty = safe_float(
            fixture.get(
                "team_h_difficulty"
            ),
            3.0,
        )

        away_difficulty = safe_float(
            fixture.get(
                "team_a_difficulty"
            ),
            3.0,
        )

        if home in scores:

            scores[home] += (
                6.0
                - home_difficulty
            )

        if away in scores:

            scores[away] += (
                6.0
                - away_difficulty
            )

    return scores


def get_team_upcoming_fixtures(
    fixtures: list,
    teams: dict,
    team_id: int,
    current_gw: int,
    lookahead: int = 5,
) -> list:

    upcoming = []

    for fixture in fixtures:

        gw = fixture.get(
            "event"
        )

        if not gw:
            continue

        if not (
            current_gw
            <= gw
            < current_gw + lookahead
        ):
            continue

        if (
            fixture.get("team_h")
            != team_id
            and fixture.get("team_a")
            != team_id
        ):
            continue

        is_home = (
            fixture.get("team_h")
            == team_id
        )

        opponent_id = (
            fixture.get("team_a")
            if is_home
            else fixture.get("team_h")
        )

        difficulty = (
            fixture.get(
                "team_h_difficulty"
            )
            if is_home
            else fixture.get(
                "team_a_difficulty"
            )
        )

        upcoming.append(
            {
                "gw": gw,
                "opponent": teams.get(
                    opponent_id,
                    "?",
                ),
                "opponent_id": opponent_id,
                "home": is_home,
                "difficulty": int(
                    safe_float(
                        difficulty,
                        3,
                    )
                ),
                "fixture_id": fixture.get(
                    "id"
                ),
            }
        )

    upcoming.sort(
        key=lambda x: (
            x["gw"],
            x["fixture_id"] or 0,
        )
    )

    return upcoming


def detect_dgw_bgw(
    fixtures: list,
    teams: dict,
    current_gw: int,
    lookahead: int,
) -> dict:

    window = list(
        range(
            current_gw,
            current_gw + lookahead,
        )
    )

    result = {}

    for team_id in teams:

        counts = {
            gw: 0
            for gw in window
        }

        for fixture in fixtures:

            gw = fixture.get(
                "event"
            )

            if gw not in counts:
                continue

            if (
                fixture.get("team_h")
                == team_id
                or fixture.get("team_a")
                == team_id
            ):

                counts[gw] += 1

        result[team_id] = {
            "dgw_gws": [
                gw
                for gw, count
                in counts.items()
                if count > 1
            ],
            "bgw_gws": [
                gw
                for gw, count
                in counts.items()
                if count == 0
            ],
        }

    return result


# ============================================================================
# PLAYER ROWS
# ============================================================================

def _chance_probability(
    element: dict,
) -> float:

    status = element.get(
        "status",
        "a",
    )

    chance = element.get(
        "chance_of_playing_next_round"
    )

    if status == "a":
        return 1.0

    if status in (
        "i",
        "s",
        "u",
    ):

        if chance is not None:

            return clamp(
                safe_float(chance) / 100.0,
                0.0,
                1.0,
            )

        return 0.0

    if chance is not None:

        return clamp(
            safe_float(chance) / 100.0,
            0.0,
            1.0,
        )

    return 1.0


def _expected_minutes(
    element: dict,
    elapsed_gws: int,
) -> float:

    minutes = safe_float(
        element.get("minutes")
    )

    starts = safe_float(
        element.get("starts")
    )

    if starts > 0:

        mins_per_start = (
            minutes / starts
        )

    elif minutes > 0:

        mins_per_start = min(
            minutes,
            75.0,
        )

    else:

        mins_per_start = 0.0

    starts_per_90 = safe_float(
        element.get("starts_per_90")
    )

    if starts_per_90 > 0:

        start_probability = clamp(
            starts_per_90,
            0.0,
            1.0,
        )

    else:

        appearances = safe_float(
            element.get(
                "appearances"
            )
        )

        if (
            elapsed_gws > 0
            and appearances > 0
        ):

            start_probability = clamp(
                starts
                / max(
                    appearances,
                    1.0,
                ),
                0.0,
                1.0,
            )

        else:

            start_probability = 0.5

    if (
        starts >= 3
        and minutes > 180
    ):

        start_probability = max(
            start_probability,
            0.70,
        )

    return clamp(
        start_probability
        * mins_per_start,
        0.0,
        90.0,
    )


def build_player_rows(
    bootstrap: dict,
    fixtures: list,
    lookahead: int = 5,
    min_avg_minutes: float = 45.0,
) -> list:

    teams = {
        team["id"]: team["name"]
        for team in bootstrap.get(
            "teams",
            [],
        )
    }

    team_short = {
        team["id"]: team.get(
            "short_name",
            team["name"],
        )
        for team in bootstrap.get(
            "teams",
            [],
        )
    }

    events = bootstrap.get(
        "events",
        []
    )

    current_gw = get_current_gameweek(
        events,
        prefer_next=True,
    )

    elapsed_gws = max(
        current_gw - 1,
        1,
    )

    fixture_scores = calculate_fixture_score(
        fixtures,
        teams,
        current_gw,
        lookahead,
    )

    dgw_bgw = detect_dgw_bgw(
        fixtures,
        teams,
        current_gw,
        lookahead,
    )

    rows = []

    for element in bootstrap.get(
        "elements",
        [],
    ):

        position = POSITION_MAP.get(
            element.get(
                "element_type"
            )
        )

        if not position:
            continue

        team_id = element.get(
            "team"
        )

        price = (
            safe_float(
                element.get(
                    "now_cost"
                )
            )
            / 10.0
        )

        minutes = safe_float(
            element.get("minutes")
        )

        starts = safe_float(
            element.get("starts")
        )

        xg = safe_float(
            element.get(
                "expected_goals"
            )
        )

        xa = safe_float(
            element.get(
                "expected_assists"
            )
        )

        xgi = safe_float(
            element.get(
                "expected_goal_involvements"
            )
        )

        xgc = safe_float(
            element.get(
                "expected_goals_conceded"
            )
        )

        xg_per90 = safe_float(
            element.get(
                "expected_goals_per_90"
            )
        )

        xa_per90 = safe_float(
            element.get(
                "expected_assists_per_90"
            )
        )

        xgi_per90 = safe_float(
            element.get(
                "expected_goal_involvements_per_90"
            )
        )

        xgc_per90 = safe_float(
            element.get(
                "expected_goals_conceded_per_90"
            )
        )

        if (
            xg_per90 == 0
            and minutes > 0
        ):

            xg_per90 = (
                xg
                / minutes
                * 90
            )

        if (
            xa_per90 == 0
            and minutes > 0
        ):

            xa_per90 = (
                xa
                / minutes
                * 90
            )

        if xgi_per90 == 0:

            xgi_per90 = (
                xg_per90
                + xa_per90
            )

        if (
            xgc_per90 == 0
            and minutes > 0
        ):

            xgc_per90 = (
                xgc
                / minutes
                * 90
            )

        expected_minutes = _expected_minutes(
            element,
            elapsed_gws,
        )

        availability_probability = (
            _chance_probability(
                element
            )
        )

        expected_minutes *= (
            availability_probability
        )

        total_points = safe_float(
            element.get(
                "total_points"
            )
        )

        ownership = safe_float(
            element.get(
                "selected_by_percent"
            )
        )

        value = (
            total_points / price
            if price > 0
            else 0.0
        )

        defensive_contribution = safe_float(
            element.get(
                "defensive_contribution"
            )
        )

        defensive_contribution_per90 = (
            safe_float(
                element.get(
                    "defensive_contribution_per_90"
                )
            )
        )

        saves_per90 = safe_float(
            element.get(
                "saves_per90"
            )
        )

        goals_conceded_per90 = safe_float(
            element.get(
                "goals_conceded_per90"
            )
        )

        bonus_per90 = (
            safe_float(
                element.get(
                    "bonus"
                )
            )
            / max(
                minutes,
                1.0,
            )
            * 90
        )

        form = safe_float(
            element.get("form")
        )

        row = {
            "id": element.get("id"),
            "name": element.get(
                "web_name",
                "Unknown",
            ),
            "first_name": element.get(
                "first_name",
                "",
            ),
            "second_name": element.get(
                "second_name",
                "",
            ),
            "team": teams.get(
                team_id,
                "?",
            ),
            "team_short": team_short.get(
                team_id,
                "?",
            ),
            "team_id": team_id,
            "position": position,
            "price": price,
            "total_points": total_points,
            "form": form,
            "ownership": ownership,
            "minutes": minutes,
            "starts": starts,
            "expected_minutes": expected_minutes,
            "availability_probability": availability_probability,
            "xg": xg,
            "xa": xa,
            "xgi": xgi,
            "xgc": xgc,
            "xg_per90": xg_per90,
            "xa_per90": xa_per90,
            "xgi_per90": xgi_per90,
            "xgc_per90": xgc_per90,
            "defensive_contribution": defensive_contribution,
            "defensive_contribution_per90": (
                defensive_contribution_per90
            ),
            "saves_per90": saves_per90,
            "goals_conceded_per90": (
                goals_conceded_per90
            ),
            "bonus_per90": bonus_per90,
            "fixture_score": fixture_scores.get(
                team_id,
                0.0,
            ),
            "value": value,
            "status": element.get(
                "status",
                "a",
            ),
            "status_ok": (
                availability_probability > 0
            ),
            "news": element.get(
                "news",
                "",
            )
            or "",
            "chance_of_playing_next_round": (
                element.get(
                    "chance_of_playing_next_round"
                )
            ),
            "cost_change_event": safe_float(
                element.get(
                    "cost_change_event"
                )
            ),
            "cost_change_start": safe_float(
                element.get(
                    "cost_change_start"
                )
            ),
            "transfers_in_event": safe_int(
                element.get(
                    "transfers_in_event"
                )
            ),
            "transfers_out_event": safe_int(
                element.get(
                    "transfers_out_event"
                )
            ),
            "is_penalty_taker": (
                safe_int(
                    element.get(
                        "penalties_order"
                    )
                )
                == 1
            ),
            "is_corner_taker": (
                safe_int(
                    element.get(
                        "corners_and_indirect_freekicks_order"
                    )
                )
                == 1
            ),
            "is_freekick_taker": (
                safe_int(
                    element.get(
                        "direct_freekicks_order"
                    )
                )
                == 1
            ),
            "ep_next": safe_float(
                element.get("ep_next")
            ),
            "ep_this": safe_float(
                element.get("ep_this")
            ),
            "dgw_gws": dgw_bgw.get(
                team_id,
                {},
            ).get(
                "dgw_gws",
                [],
            ),
            "bgw_gws": dgw_bgw.get(
                team_id,
                {},
            ).get(
                "bgw_gws",
                [],
            ),
        }

        row["meets_minutes_floor"] = (
            row["expected_minutes"]
            >= min_avg_minutes
        )

        if position in (
            "GKP",
            "DEF",
        ):

            row["underlying_metric"] = (
                xgi_per90
                - 0.25 * xgc_per90
                + 0.05
                * defensive_contribution_per90
            )

        else:

            row["underlying_metric"] = (
                xgi_per90
                + 0.05
                * defensive_contribution_per90
            )

        rows.append(row)

    return rows


# ============================================================================
# COMPOSITE SCORE
# ============================================================================

def score_rows(
    rows: list,
    weights: Optional[Weights] = None,
) -> list:

    weights = weights or Weights()

    positions = set(
        row["position"]
        for row in rows
    )

    for position in positions:

        indices = [
            index
            for index, row in enumerate(rows)
            if row["position"] == position
        ]

        if not indices:
            continue

        value_n = normalize([
            rows[i]["value"]
            for i in indices
        ])

        form_n = normalize([
            rows[i]["form"]
            for i in indices
        ])

        underlying_n = normalize([
            rows[i]["underlying_metric"]
            for i in indices
        ])

        fixture_n = normalize([
            rows[i]["fixture_score"]
            for i in indices
        ])

        ownership_n = normalize([
            rows[i]["ownership"]
            for i in indices
        ])

        for j, i in enumerate(indices):

            rows[i]["score"] = (
                weights.value
                * value_n[j]
                + weights.form
                * form_n[j]
                + weights.underlying
                * underlying_n[j]
                + weights.fixtures
                * fixture_n[j]
                - weights.ownership_penalty
                * ownership_n[j]
            )

    return rows


# ============================================================================
# EXPECTED POINTS
# ============================================================================

def _appearance_points(
    expected_minutes: float,
) -> float:

    p60 = clamp(
        (
            expected_minutes
            - 45.0
        )
        / 20.0,
        0.0,
        1.0,
    )

    p_appearance = clamp(
        expected_minutes / 90.0,
        0.0,
        1.0,
    )

    return (
        p60 * 2.0
        + (1.0 - p60)
        * p_appearance
    )


def _clean_sheet_probability(
    difficulty: float,
    position: str,
    expected_minutes: float,
) -> float:

    if position not in (
        "GKP",
        "DEF",
        "MID",
    ):

        return 0.0

    if expected_minutes < 45:
        return 0.0

    base = {
        "GKP": 0.34,
        "DEF": 0.34,
        "MID": 0.12,
    }.get(
        position,
        0.0,
    )

    difficulty_factor = {
        1: 1.40,
        2: 1.18,
        3: 1.00,
        4: 0.78,
        5: 0.60,
    }.get(
        int(
            round(
                clamp(
                    difficulty,
                    1.0,
                    5.0,
                )
            )
        ),
        1.0,
    )

    minutes_factor = clamp(
        expected_minutes / 75.0,
        0.0,
        1.0,
    )

    return clamp(
        base
        * difficulty_factor
        * minutes_factor,
        0.0,
        0.85,
    )


def _expected_defensive_contribution_points(
    row: dict,
    expected_minutes: float,
) -> float:

    dc90 = row.get(
        "defensive_contribution_per90",
        0.0,
    )

    if dc90 <= 0:
        return 0.0

    expected_dc = (
        dc90
        * expected_minutes
        / 90.0
    )

    if row["position"] == "DEF":
        threshold = 10.0

    elif row["position"] in (
        "MID",
        "FWD",
    ):
        threshold = 12.0

    else:
        return 0.0

    probability = clamp(
        expected_dc / threshold,
        0.0,
        0.82,
    )

    return 2.0 * probability


def _expected_save_points(
    row: dict,
    expected_minutes: float,
) -> float:

    if row["position"] != "GKP":
        return 0.0

    saves_per90 = row.get(
        "saves_per90",
        0.0,
    )

    expected_saves = (
        saves_per90
        * expected_minutes
        / 90.0
    )

    return (
        expected_saves / 3.0
    )


def _expected_goals_conceded_penalty(
    row: dict,
    expected_minutes: float,
) -> float:

    if row["position"] not in (
        "GKP",
        "DEF",
    ):
        return 0.0

    gc_per90 = row.get(
        "goals_conceded_per90",
        0.0,
    )

    expected_gc = (
        gc_per90
        * expected_minutes
        / 90.0
    )

    return -0.5 * expected_gc


def _expected_bonus_points(
    row: dict,
    expected_minutes: float,
) -> float:

    bonus_per90 = row.get(
        "bonus_per90",
        0.0,
    )

    return (
        bonus_per90
        * expected_minutes
        / 90.0
    )


def _expected_card_penalty(
    row: dict,
    expected_minutes: float,
) -> float:

    return -0.03 * (
        expected_minutes / 90.0
    )


def _fixture_xp(
    row: dict,
    fixture: dict,
) -> dict:

    expected_minutes = row[
        "expected_minutes"
    ]

    if fixture.get("team_h") == row["team_id"]:

        difficulty = safe_float(
            fixture.get(
                "team_h_difficulty"
            ),
            3.0,
        )

    else:

        difficulty = safe_float(
            fixture.get(
                "team_a_difficulty"
            ),
            3.0,
        )

    attacking_multiplier = (
        fixture_difficulty_multiplier(
            difficulty,
            attacking=True,
        )
    )

    defensive_multiplier = (
        fixture_difficulty_multiplier(
            difficulty,
            attacking=False,
        )
    )

    xg = (
        row["xg_per90"]
        * expected_minutes
        / 90.0
        * attacking_multiplier
    )

    xa = (
        row["xa_per90"]
        * expected_minutes
        / 90.0
        * attacking_multiplier
    )

    if row.get(
        "is_penalty_taker"
    ):

        xg *= 1.08

    goal_points = (
        xg
        * GOAL_POINTS[
            row["position"]
        ]
    )

    assist_points = (
        xa
        * ASSIST_POINTS
    )

    cs_probability = (
        _clean_sheet_probability(
            difficulty,
            row["position"],
            expected_minutes,
        )
        * defensive_multiplier
    )

    cs_points = (
        cs_probability
        * CLEAN_SHEET_POINTS[
            row["position"]
        ]
    )

    appearance_points = (
        _appearance_points(
            expected_minutes
        )
    )

    save_points = (
        _expected_save_points(
            row,
            expected_minutes,
        )
    )

    dc_points = (
        _expected_defensive_contribution_points(
            row,
            expected_minutes,
        )
    )

    gc_penalty = (
        _expected_goals_conceded_penalty(
            row,
            expected_minutes,
        )
    )

    bonus_points = (
        _expected_bonus_points(
            row,
            expected_minutes,
        )
    )

    card_penalty = (
        _expected_card_penalty(
            row,
            expected_minutes,
        )
    )

    total = (
        appearance_points
        + goal_points
        + assist_points
        + cs_points
        + save_points
        + dc_points
        + gc_penalty
        + bonus_points
        + card_penalty
    )

    return {
        "appearance": appearance_points,
        "goals": goal_points,
        "assists": assist_points,
        "clean_sheet": cs_points,
        "saves": save_points,
        "defensive_contribution": dc_points,
        "goals_conceded": gc_penalty,
        "bonus": bonus_points,
        "cards": card_penalty,
        "xp": max(
            total,
            0.0,
        ),
        "expected_minutes": expected_minutes,
        "difficulty": difficulty,
    }


def build_xp(
    rows: list,
    fixtures: list,
    teams: dict,
    current_gw: int,
    lookahead: int,
) -> list:

    for row in rows:

        team_id = row[
            "team_id"
        ]

        team_fixtures = []

        for fixture in fixtures:

            gw = fixture.get(
                "event"
            )

            if not gw:
                continue

            if not (
                current_gw
                <= gw
                < current_gw + lookahead
            ):
                continue

            if (
                fixture.get("team_h")
                == team_id
                or fixture.get("team_a")
                == team_id
            ):

                team_fixtures.append(
                    fixture
                )

        team_fixtures.sort(
            key=lambda fixture: (
                fixture.get(
                    "event",
                    999,
                ),
                fixture.get(
                    "id",
                    999999,
                ),
            )
        )

        breakdown = []

        for fixture in team_fixtures:

            result = _fixture_xp(
                row,
                fixture,
            )

            result["gw"] = fixture.get(
                "event"
            )

            result["fixture_id"] = (
                fixture.get("id")
            )

            result["home"] = (
                fixture.get(
                    "team_h"
                )
                == team_id
            )

            opponent_id = (
                fixture.get("team_a")
                if result["home"]
                else fixture.get("team_h")
            )

            result["opponent"] = teams.get(
                opponent_id,
                "?",
            )

            breakdown.append(
                result
            )

        total_xp = sum(
            item["xp"]
            for item in breakdown
        )

        next_gw = [
            item
            for item in breakdown
            if item["gw"] == current_gw
        ]

        next_gw_xp = sum(
            item["xp"]
            for item in next_gw
        )

        row["xp"] = round(
            total_xp,
            3,
        )

        row["xp_next"] = round(
            next_gw_xp,
            3,
        )

        row["xp_per_gw"] = round(
            total_xp
            / max(
                lookahead,
                1,
            ),
            3,
        )

        row["xp_per_million"] = round(
            total_xp / row["price"]
            if row["price"] > 0
            else 0.0,
            3,
        )

        row["xp_breakdown"] = (
            breakdown
        )

        row["captain_score"] = round(
            next_gw_xp
            * (
                1.0
                + 0.15
                * min(
                    row["xgi_per90"],
                    1.5,
                )
            ),
            3,
        )

    return rows


# ============================================================================
# STARTING XI
# ============================================================================

def pick_starting_xi(
    squad_rows: list,
    current_gw: int,
) -> dict:

    for row in squad_rows:

        row["_this_gw_xp"] = row.get(
            "xp_next",
            row.get(
                "xp",
                0.0,
            ),
        )

    goalkeepers = sorted(
        [
            row
            for row in squad_rows
            if row["position"] == "GKP"
        ],
        key=lambda row: row[
            "_this_gw_xp"
        ],
        reverse=True,
    )

    defenders = sorted(
        [
            row
            for row in squad_rows
            if row["position"] == "DEF"
        ],
        key=lambda row: row[
            "_this_gw_xp"
        ],
        reverse=True,
    )

    midfielders = sorted(
        [
            row
            for row in squad_rows
            if row["position"] == "MID"
        ],
        key=lambda row: row[
            "_this_gw_xp"
        ],
        reverse=True,
    )

    forwards = sorted(
        [
            row
            for row in squad_rows
            if row["position"] == "FWD"
        ],
        key=lambda row: row[
            "_this_gw_xp"
        ],
        reverse=True,
    )

    if not goalkeepers:

        return {
            "starting_xi": [],
            "bench": squad_rows,
            "captain": None,
            "vice_captain": None,
            "projected_points": 0.0,
        }

    best = None

    for defender_count in range(
        3,
        min(
            5,
            len(defenders),
        )
        + 1,
    ):

        for midfielder_count in range(
            2,
            min(
                5,
                len(midfielders),
            )
            + 1,
        ):

            for forward_count in range(
                1,
                min(
                    3,
                    len(forwards),
                )
                + 1,
            ):

                if (
                    defender_count
                    + midfielder_count
                    + forward_count
                    != 10
                ):
                    continue

                selected = (
                    [goalkeepers[0]]
                    + defenders[
                        :defender_count
                    ]
                    + midfielders[
                        :midfielder_count
                    ]
                    + forwards[
                        :forward_count
                    ]
                )

                points = sum(
                    player[
                        "_this_gw_xp"
                    ]
                    for player in selected
                )

                if (
                    best is None
                    or points > best[0]
                ):

                    best = (
                        points,
                        selected,
                    )

    if best is None:

        return {
            "starting_xi": [],
            "bench": squad_rows,
            "captain": None,
            "vice_captain": None,
            "projected_points": 0.0,
        }

    projected_points, starting_xi = (
        best
    )

    starting_ids = {
        player["id"]
        for player in starting_xi
    }

    bench = sorted(
        [
            player
            for player in squad_rows
            if player["id"]
            not in starting_ids
        ],
        key=lambda player: player[
            "_this_gw_xp"
        ],
        reverse=True,
    )

    captain_candidates = sorted(
        starting_xi,
        key=lambda player: player[
            "_this_gw_xp"
        ],
        reverse=True,
    )

    captain = (
        captain_candidates[0]
        if captain_candidates
        else None
    )

    vice_captain = (
        captain_candidates[1]
        if len(
            captain_candidates
        ) > 1
        else None
    )

    return {
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "projected_points": round(
            projected_points,
            2,
        ),
    }


# ============================================================================
# TRANSFER RECOMMENDATIONS
# ============================================================================

def suggest_transfers(
    squad_rows: list,
    all_rows: list,
    bank: float,
    top_n: int = 10,
    metric: str = "xp",
) -> list:

    suggestions = []

    for out_player in squad_rows:

        for in_player in all_rows:

            if (
                in_player["id"]
                == out_player["id"]
            ):
                continue

            if (
                in_player["position"]
                != out_player["position"]
            ):
                continue

            if not in_player[
                "status_ok"
            ]:
                continue

            cost_delta = (
                in_player["price"]
                - out_player["price"]
            )

            if cost_delta > (
                bank + 1e-9
            ):
                continue

            current_value = out_player.get(
                metric,
                out_player.get(
                    "xp",
                    0.0,
                ),
            )

            new_value = in_player.get(
                metric,
                in_player.get(
                    "xp",
                    0.0,
                ),
            )

            gain = (
                new_value
                - current_value
            )

            if gain <= 0:
                continue

            suggestions.append(
                {
                    "out": out_player,
                    "in": in_player,
                    "cost_delta": round(
                        cost_delta,
                        2,
                    ),
                    "gain": round(
                        gain,
                        3,
                    ),
                    "value_gain": round(
                        in_player.get(
                            "xp_per_million",
                            0.0,
                        )
                        - out_player.get(
                            "xp_per_million",
                            0.0,
                        ),
                        3,
                    ),
                }
            )

    suggestions.sort(
        key=lambda suggestion: (
            suggestion["gain"],
            suggestion["value_gain"],
        ),
        reverse=True,
    )

    return suggestions[:top_n]


# ============================================================================
# DIFFERENTIALS
# ============================================================================

def find_differentials(
    rows: list,
    max_ownership: float = 10.0,
    top_n: int = 10,
) -> list:

    candidates = [
        row
        for row in rows
        if (
            row["ownership"]
            <= max_ownership
            and row["status_ok"]
            and row["expected_minutes"]
            >= 45
        )
    ]

    for row in candidates:

        ownership_factor = clamp(
            1.0
            - (
                row["ownership"]
                / max(
                    max_ownership,
                    0.1,
                )
            ),
            0.0,
            1.0,
        )

        row[
            "differential_score"
        ] = (
            row.get(
                "xp",
                0.0,
            )
            * (
                0.65
                + 0.35
                * ownership_factor
            )
        )

    candidates.sort(
        key=lambda row: row[
            "differential_score"
        ],
        reverse=True,
    )

    return candidates[:top_n]


# ============================================================================
# PRICE CHANGE WATCH
# ============================================================================

def price_change_watch(
    rows: list,
) -> dict:

    rising = []
    falling = []

    for row in rows:

        net_transfers = (
            row.get(
                "transfers_in_event",
                0,
            )
            - row.get(
                "transfers_out_event",
                0,
            )
        )

        item = {
            "name": row["name"],
            "team_short": row[
                "team_short"
            ],
            "price": row["price"],
            "net_transfers": (
                net_transfers
            ),
            "xp": row.get(
                "xp",
                0.0,
            ),
            "ownership": row[
                "ownership"
            ],
        }

        if net_transfers > 0:

            rising.append(item)

        elif net_transfers < 0:

            falling.append(item)

    rising.sort(
        key=lambda item: item[
            "net_transfers"
        ],
        reverse=True,
    )

    falling.sort(
        key=lambda item: item[
            "net_transfers"
        ]
    )

    return {
        "rising_soon": rising[:10],
        "falling_soon": falling[:10],
    }


# ============================================================================
# CHIP HINTS
# ============================================================================

def build_chip_hints(
    rows: list,
    squad_rows: list,
    current_gw: int,
    lookahead: int,
    bank: float = 0.0,
) -> list:

    hints = []

    squad_dgw_count = sum(
        bool(
            row.get(
                "dgw_gws"
            )
        )
        for row in squad_rows
    )

    squad_bgw_count = sum(
        bool(
            row.get(
                "bgw_gws"
            )
        )
        for row in squad_rows
    )

    if squad_dgw_count >= 6:

        hints.append(
            f"🟢 Your squad has "
            f"{squad_dgw_count} players "
            "with a Double Gameweek "
            "in the current planning window."
        )

    if squad_bgw_count >= 4:

        hints.append(
            f"🔴 Your squad has "
            f"{squad_bgw_count} players "
            "affected by a Blank Gameweek "
            "in the current planning window."
        )

    high_xp = sorted(
        [
            row
            for row in squad_rows
            if row.get(
                "xp_next",
                0,
            ) > 0
        ],
        key=lambda row: row[
            "xp_next"
        ],
        reverse=True,
    )

    if high_xp:

        captain = high_xp[0]

        hints.append(
            f"🎯 Captaincy watch: "
            f"{captain['name']} "
            f"projects for "
            f"{captain['xp_next']:.2f} "
            "xP this GW."
        )

    return hints
    
