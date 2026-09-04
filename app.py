import streamlit as st
import pandas as pd
import plotly.express as px

from fpl_common import (
    DEFAULT_TEAM_ID, Weights, build_player_rows, fetch_manager_overview,
    fetch_squad_by_team_id, get_current_gameweek, get_team_upcoming_fixtures,
    load_fpl_data, price_change_watch, score_rows, suggest_transfers,
)

st.set_page_config(page_title="FPL Analytics Dashboard", layout="wide")
st.title("⚽ FPL Transfer & Squad Analyzer")


@st.cache_data(ttl=3600)
def cached_load():
    bootstrap, fixtures = load_fpl_data()
    return bootstrap, fixtures


@st.cache_data(ttl=3600)
def cached_squad(team_id, current_gw):
    return fetch_squad_by_team_id(team_id, current_gw)


@st.cache_data(ttl=3600)
def cached_manager(team_id):
    return fetch_manager_overview(team_id)


bootstrap, fixtures = cached_load()
teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
current_gw = get_current_gameweek(bootstrap["events"])

# Sidebar
st.sidebar.header("Settings")
team_id = st.sidebar.number_input("Your FPL Team ID", value=DEFAULT_TEAM_ID, step=1)
lookahead = st.sidebar.slider("Fixture lookahead (GWs)", 1, 8, 5)
position = st.sidebar.multiselect("Position", ["GKP", "DEF", "MID", "FWD"], default=["MID", "FWD"])
max_price = st.sidebar.slider("Max Price (£M)", 4.0, 15.0, 12.5, 0.5)

manager = cached_manager(team_id)
owned_picks = cached_squad(team_id, current_gw)
owned_ids = set(owned_picks.keys())

rows = build_player_rows(bootstrap, fixtures, lookahead=lookahead)
rows = score_rows(rows, Weights())
for r in rows:
    r["is_owned"] = r["id"] in owned_ids
df = pd.DataFrame(rows)

if manager:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Team", manager.get("team_name", "—"))
    c2.metric("Overall Rank", f"{manager['overall_rank']:,}" if manager.get("overall_rank") else "—")
    c3.metric("Total Points", manager.get("overall_points", "—"))
    c4.metric("Bank", f"£{manager.get('bank', 0):.1f}m")

filtered_df = df[
    (df["position"].isin(position))
    & (df["price"] <= max_price)
    & (df["minutes"] > 180)
    & (~df["is_owned"])
].sort_values(by="score", ascending=False)

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Top Transfer Candidates (Composite Score)")
    fig = px.scatter(
        filtered_df.head(25),
        x="price",
        y="score",
        size="total_points",
        color="position",
        hover_name="name",
        hover_data=["form", "xgi_per90", "fixture_score", "ownership"],
        text="name",
        title="Price vs Composite Score (value + form + underlying + fixtures - ownership)",
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Your Current Squad")
    squad_df = df[df["is_owned"]][["name", "position", "price", "form", "total_points", "score"]] \
        .sort_values("score")
    st.dataframe(squad_df, hide_index=True, use_container_width=True)

st.divider()

st.subheader("🔄 Suggested Transfers")
squad_rows = [r for r in rows if r["is_owned"]]
bank = manager.get("bank", 0.0) if manager else 0.0
if squad_rows:
    swaps = suggest_transfers(squad_rows, rows, bank, top_n=5)
    if swaps:
        swap_df = pd.DataFrame([{
            "Out": s["out"]["name"],
            "In": s["in"]["name"],
            "Position": s["out"]["position"],
            "Cost delta (£m)": round(s["cost_delta"], 1),
            "Score gain": round(s["score_gain"], 3),
        } for s in swaps])
        st.dataframe(swap_df, hide_index=True, use_container_width=True)
    else:
        st.write("No clear upgrades found within your bank at current filters.")
else:
    st.write("Couldn't load your squad — check the Team ID in the sidebar.")

st.divider()

st.subheader("📈 Price Change Watch")
watch = price_change_watch(rows)
pc1, pc2 = st.columns(2)
with pc1:
    st.markdown("**Rising soon**")
    if watch["rising_soon"]:
        st.dataframe(pd.DataFrame(watch["rising_soon"])[["name", "team_short", "price", "net_transfers"]],
                     hide_index=True, use_container_width=True)
    else:
        st.write("None flagged.")
with pc2:
    st.markdown("**Falling soon**")
    if watch["falling_soon"]:
        st.dataframe(pd.DataFrame(watch["falling_soon"])[["name", "team_short", "price", "net_transfers"]],
                     hide_index=True, use_container_width=True)
    else:
        st.write("None flagged.")
st.caption("Heuristic based on today's net transfer momentum — not an exact predictor.")

if squad_rows:
    st.divider()
    st.subheader("🗓️ Squad Fixture Outlook")
    for r in sorted(squad_rows, key=lambda x: x["position"]):
        fx = get_team_upcoming_fixtures(fixtures, teams, r["team_id"], current_gw, lookahead)
        fx_str = "  ".join(
            f"{f['opponent']}({'H' if f['home'] else 'A'}) FDR{f['difficulty']}" for f in fx
        ) or "No fixtures in range"
        st.write(f"**{r['name']}** ({r['position']}, {r['team_short']}): {fx_str}")
