import streamlit as st
import pandas as pd
import plotly.express as px

from fpl_common import (
    DEFAULT_TEAM_ID,
    Weights,
    build_chip_hints,
    build_player_rows,
    build_xp,
    fetch_manager_overview,
    fetch_squad_state,
    find_differentials,
    get_current_gameweek,
    get_team_upcoming_fixtures,
    load_fpl_data,
    pick_starting_xi,
    price_change_watch,
    score_rows,
    suggest_transfers,
)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FPL Analytics Dashboard",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ FPL Advisor")
st.caption(
    "Live FPL data + fixture-adjusted expected points "
    "for team selection, transfers and captaincy."
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def cached_load():
    return load_fpl_data()

@st.cache_data(ttl=60, show_spinner=False)
def cached_squad_state(team_id, gw):
    return fetch_squad_state(
        team_id,
    )

@st.cache_data(ttl=300)
def cached_manager(team_id):
    return fetch_manager_overview(team_id)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.header("Settings")

team_id = st.sidebar.number_input(
    "Your FPL Team ID",
    min_value=1,
    value=DEFAULT_TEAM_ID,
    step=1,
)

lookahead = st.sidebar.slider(
    "Projection window (GWs)",
    min_value=1,
    max_value=8,
    value=5,
)

position = st.sidebar.multiselect(
    "Positions",
    ["GKP", "DEF", "MID", "FWD"],
    default=["MID", "FWD"],
)

max_price = st.sidebar.slider(
    "Maximum price (£m)",
    min_value=4.0,
    max_value=15.0,
    value=12.5,
    step=0.1,
)

max_ownership = st.sidebar.slider(
    "Differential ownership ceiling (%)",
    min_value=1.0,
    max_value=30.0,
    value=10.0,
    step=0.5,
)

if st.sidebar.button(
    "🔄 Refresh FPL data",
    use_container_width=True,
):
    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

bootstrap, fixtures = cached_load()

teams = {
    team["id"]: team["name"]
    for team in bootstrap["teams"]
}

team_short = {
    team["id"]: team["short_name"]
    for team in bootstrap["teams"]
}

current_gw = get_current_gameweek(
    bootstrap["events"],
    prefer_next=True,
)

manager = cached_manager(team_id)

squad_state = cached_squad_state(
    team_id,
    current_gw,
)
owned_picks = squad_state["picks"]

if squad_state["latest_transfer_time"]:
    st.caption(
        f"Squad source: GW{squad_state['gameweek']} · "
        f"latest transfer: {squad_state['latest_transfer_time']}"
    )

owned_ids = set(
    owned_picks.keys()
)


# ---------------------------------------------------------------------------
# Build model
# ---------------------------------------------------------------------------

rows = build_player_rows(
    bootstrap,
    fixtures,
    lookahead=lookahead,
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
    lookahead,
)

for row in rows:
    row["is_owned"] = (
        row["id"] in owned_ids
    )

df = pd.DataFrame(rows)

squad_rows = [
    row
    for row in rows
    if row["is_owned"]
]

bank = (
    manager.get("bank", 0.0)
    if manager
    else 0.0
)


# ---------------------------------------------------------------------------
# Header metrics
# ---------------------------------------------------------------------------

if manager:

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "Team",
        manager.get(
            "team_name",
            "—",
        ),
    )

    c2.metric(
        "Planning GW",
        current_gw,
    )

    c3.metric(
        "Overall Rank",
        (
            f"{manager['overall_rank']:,}"
            if manager.get("overall_rank")
            else "—"
        ),
    )

    c4.metric(
        "Total Points",
        manager.get(
            "overall_points",
            "—",
        ),
    )

    c5.metric(
        "Bank",
        f"£{bank:.1f}m",
    )


# ---------------------------------------------------------------------------
# Chip hints
# ---------------------------------------------------------------------------

hints = build_chip_hints(
    rows,
    squad_rows,
    current_gw,
    lookahead,
    bank=bank,
)

for hint in hints:
    st.info(hint)


# ---------------------------------------------------------------------------
# Starting XI
# ---------------------------------------------------------------------------

st.divider()

st.subheader(
    f"🧠 Optimal Starting XI — GW{current_gw}"
)

if squad_rows:

    xi = pick_starting_xi(
        list(squad_rows),
        current_gw,
    )

    if xi["starting_xi"]:

        left, right = st.columns(
            [2.5, 1]
        )

        with left:

            xi_df = pd.DataFrame(
                [
                    {
                        "Player": player["name"],
                        "Pos": player["position"],
                        "Team": player["team_short"],
                        "GW xP": round(
                            player["_this_gw_xp"],
                            2,
                        ),
                        "C/VC": (
                            "C"
                            if (
                                xi["captain"]
                                and player["id"]
                                == xi["captain"]["id"]
                            )
                            else (
                                "VC"
                                if (
                                    xi["vice_captain"]
                                    and player["id"]
                                    == xi["vice_captain"]["id"]
                                )
                                else ""
                            )
                        ),
                    }
                    for player
                    in xi["starting_xi"]
                ]
            )

            st.dataframe(
                xi_df,
                hide_index=True,
                use_container_width=True,
            )

        with right:

            st.metric(
                "Projected XI",
                f"{xi['projected_points']:.2f}",
            )

            if xi["captain"]:
                st.metric(
                    "Captain",
                    xi["captain"]["name"],
                    f"{xi['captain']['_this_gw_xp']:.2f} xP",
                )

            if xi["vice_captain"]:
                st.metric(
                    "Vice-Captain",
                    xi["vice_captain"]["name"],
                    f"{xi['vice_captain']['_this_gw_xp']:.2f} xP",
                )

        if xi["bench"]:

            st.caption(
                "Bench order: "
                + " → ".join(
                    (
                        f"{p['name']} "
                        f"({p['_this_gw_xp']:.2f})"
                    )
                    for p in xi["bench"]
                )
            )

    else:
        st.warning(
            "Couldn't build a valid starting XI."
        )

else:

    st.warning(
        "Couldn't load your current squad. "
        "Check the FPL Team ID."
    )


# ---------------------------------------------------------------------------
# Squad analysis
# ---------------------------------------------------------------------------

st.divider()

st.subheader("📋 Your Squad")

if squad_rows:

    squad_df = pd.DataFrame(
        [
            {
                "Player": r["name"],
                "Pos": r["position"],
                "Team": r["team_short"],
                "Price": r["price"],
                "GW xP": r["xp_next"],
                f"{lookahead}GW xP": r["xp"],
                "xP/£m": r["xp_per_million"],
                "xMins": round(
                    r["expected_minutes"],
                    0,
                ),
                "Own%": r["ownership"],
                "Form": r["form"],
                "Status": r["status"],
            }
            for r in squad_rows
        ]
    )

    st.dataframe(
        squad_df.sort_values(
            "GW xP",
            ascending=False,
        ),
        hide_index=True,
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Transfer targets
# ---------------------------------------------------------------------------

st.divider()

st.subheader(
    f"🎯 Best Transfer Targets — next {lookahead} GWs"
)

filtered_df = df[
    df["position"].isin(position)
    & (df["price"] <= max_price)
    & (df["expected_minutes"] >= 45)
    & df["status_ok"]
    & ~df["is_owned"]
].copy()

filtered_df = filtered_df.sort_values(
    "xp",
    ascending=False,
)

if not filtered_df.empty:

    fig = px.scatter(
        filtered_df.head(40),
        x="price",
        y="xp",
        size="total_points",
        color="position",
        hover_name="name",
        hover_data=[
            "team_short",
            "xp_next",
            "xp_per_million",
            "expected_minutes",
            "ownership",
            "form",
        ],
        title=(
            f"Price vs projected points "
            f"over next {lookahead} GWs"
        ),
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )

    target_df = filtered_df.head(20)[
        [
            "name",
            "team_short",
            "position",
            "price",
            "xp_next",
            "xp",
            "xp_per_million",
            "expected_minutes",
            "ownership",
            "form",
        ]
    ].copy()

    target_df.columns = [
        "Player",
        "Team",
        "Pos",
        "Price",
        "GW xP",
        f"{lookahead}GW xP",
        "xP/£m",
        "xMins",
        "Own%",
        "Form",
    ]

    st.dataframe(
        target_df,
        hide_index=True,
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Transfer suggestions
# ---------------------------------------------------------------------------

st.divider()

st.subheader("🔄 Recommended Transfers")

if squad_rows:

    swaps = suggest_transfers(
        squad_rows,
        rows,
        bank,
        top_n=10,
        metric="xp",
    )

    if swaps:

        swap_df = pd.DataFrame(
            [
                {
                    "Sell": s["out"]["name"],
                    "Buy": s["in"]["name"],
                    "Pos": s["out"]["position"],
                    "Cost Δ": round(
                        s["cost_delta"],
                        1,
                    ),
                    f"{lookahead}GW xP Gain": round(
                        s["gain"],
                        2,
                    ),
                    "Value Gain": round(
                        s["value_gain"],
                        2,
                    ),
                }
                for s in swaps
            ]
        )

        st.dataframe(
            swap_df,
            hide_index=True,
            use_container_width=True,
        )

        st.caption(
            "Transfer gains are projected point differences "
            "within the selected lookahead window. They do not "
            "currently subtract transfer-hit costs."
        )

    else:

        st.success(
            "No clear positive-xP upgrades found "
            "within your available budget."
        )


# ---------------------------------------------------------------------------
# Differentials
# ---------------------------------------------------------------------------

st.divider()

st.subheader("💎 Differential Picks")

st.caption(
    f"Players owned by ≤{max_ownership:.1f}% of managers, "
    "ranked by projected upside."
)

diffs = find_differentials(
    rows,
    max_ownership=max_ownership,
    top_n=15,
)

if diffs:

    diff_df = pd.DataFrame(
        [
            {
                "Player": p["name"],
                "Pos": p["position"],
                "Team": p["team_short"],
                "Price": p["price"],
                "Own%": p["ownership"],
                "GW xP": p["xp_next"],
                f"{lookahead}GW xP": p["xp"],
                "xP/£m": p["xp_per_million"],
                "Differential Score": round(
                    p["differential_score"],
                    2,
                ),
            }
            for p in diffs
        ]
    )

    st.dataframe(
        diff_df,
        hide_index=True,
        use_container_width=True,
    )

else:

    st.write(
        "No suitable differentials found."
    )


# ---------------------------------------------------------------------------
# Price changes
# ---------------------------------------------------------------------------

st.divider()

st.subheader("📈 Price Change Watch")

watch = price_change_watch(rows)

left, right = st.columns(2)

with left:

    st.markdown("### 🟢 Rising")

    if watch["rising_soon"]:

        st.dataframe(
            pd.DataFrame(
                watch["rising_soon"]
            )[
                [
                    "name",
                    "team_short",
                    "price",
                    "net_transfers",
                    "xp",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

    else:
        st.write("None flagged.")

with right:

    st.markdown("### 🔴 Falling")

    if watch["falling_soon"]:

        st.dataframe(
            pd.DataFrame(
                watch["falling_soon"]
            )[
                [
                    "name",
                    "team_short",
                    "price",
                    "net_transfers",
                    "xp",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

    else:
        st.write("None flagged.")

st.caption(
    "This is a transfer-momentum watchlist, not an exact "
    "prediction of the FPL price-change threshold."
)


# ---------------------------------------------------------------------------
# Fixture outlook
# ---------------------------------------------------------------------------

if squad_rows:

    st.divider()

    st.subheader(
        f"🗓️ Squad Fixture Outlook — next {lookahead} GWs"
    )

    for player in sorted(
        squad_rows,
        key=lambda x: (
            x["position"],
            -x["xp"],
        ),
    ):

        fixtures_for_team = (
            get_team_upcoming_fixtures(
                fixtures,
                teams,
                player["team_id"],
                current_gw,
                lookahead,
            )
        )

        if fixtures_for_team:

            fixture_text = "  ".join(
                (
                    f"GW{fixture['gw']} "
                    f"{fixture['opponent']} "
                    f"({'H' if fixture['home'] else 'A'}) "
                    f"FDR{fixture['difficulty']}"
                )
                for fixture
                in fixtures_for_team
            )

        else:

            fixture_text = "No fixtures"

        tags = []

        if player["dgw_gws"]:
            tags.append(
                "🟢 DGW "
                + ",".join(
                    str(gw)
                    for gw in player["dgw_gws"]
                )
            )

        if player["bgw_gws"]:
            tags.append(
                "🔴 BGW "
                + ",".join(
                    str(gw)
                    for gw in player["bgw_gws"]
                )
            )

        tag_text = (
            " | ".join(tags)
            if tags
            else ""
        )

        st.write(
            f"**{player['name']}** "
            f"({player['position']}, "
            f"{player['team_short']}) "
            f"— {fixture_text} "
            f"{tag_text}"
        )

        if player["news"]:
            st.caption(
                f"⚠ {player['news']}"
            )


# ---------------------------------------------------------------------------
# Model explanation
# ---------------------------------------------------------------------------

st.divider()

with st.expander("ℹ️ How the xP model works"):

    st.write(
        """
        The model estimates points fixture-by-fixture rather than simply
        multiplying a player's form by FDR.

        It considers:

        • expected minutes / start probability
        • FPL expected goals (xG)
        • FPL expected assists (xA)
        • fixture difficulty
        • clean-sheet probability
        • goalkeeper saves
        • defensive-contribution points
        • expected bonus
        • goals-conceded penalty
        • a small card allowance

        Double Gameweeks automatically contribute multiple fixtures while
        Blank Gameweeks contribute none.

        xP should be treated as a decision-support metric rather than a
        guaranteed prediction.
        """
    )
