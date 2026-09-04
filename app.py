import streamlit as st
import pandas as pd
import plotly.express as px

from fpl_common import (
    DEFAULT_TEAM_ID, Weights, build_chip_hints, build_player_rows, build_xp,
    fetch_manager_overview, fetch_squad_by_team_id, find_differentials,
    get_current_gameweek, get_team_upcoming_fixtures, load_fpl_data,
    pick_starting_xi, price_change_watch, score_rows, suggest_transfers,
)

st.set_page_config(page_title="FPL Analytics Dashboard", layout="wide")
st.title("⚽ FPL Advisor")
st.caption("Projected points (xP), not just past form — see the fpl_common.py docstring for how the model works.")


@st.cache_data(ttl=3600)
def cached_load():
    return load_fpl_data()


@st.cache_data(ttl=3600)
def cached_squad(team_id, current_gw):
    return fetch_squad_by_team_id(team_id, current_gw)


@st.cache_data(ttl=3600)
def cached_manager(team_id):
    return fetch_manager_overview(team_id)


bootstrap, fixtures = cached_load()
teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
current_gw = get_current_gameweek(bootstrap["events"])

st.sidebar.header("Settings")
team_id = st.sidebar.number_input("Your FPL Team ID", value=DEFAULT_TEAM_ID, step=1)
lookahead = st.sidebar.slider("Fixture lookahead (GWs)", 1, 8, 5)
position = st.sidebar.multiselect("Position", ["GKP", "DEF", "MID", "FWD"], default=["MID", "FWD"])
max_price = st.sidebar.slider("Max Price (£M)", 4.0, 15.0, 12.5, 0.5)
max_ownership = st.sidebar.slider("Differentials: max ownership %", 1.0, 20.0, 10.0, 0.5)

manager = cached_manager(team_id)
owned_picks = cached_squad(team_id, current_gw)
owned_ids = set(owned_picks.keys())

rows = build_player_rows(bootstrap, fixtures, lookahead=lookahead)
rows = score_rows(rows, Weights())
rows = build_xp(rows, fixtures, teams, current_gw, lookahead)
for r in rows:
    r["is_owned"] = r["id"] in owned_ids
df = pd.DataFrame(rows)
squad_rows = [r for r in rows if r["is_owned"]]
bank = manager.get("bank", 0.0) if manager else 0.0

if manager:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Team", manager.get("team_name", "—"))
    c2.metric("Overall Rank", f"{manager['overall_rank']:,}" if manager.get("overall_rank") else "—")
    c3.metric("Total Points", manager.get("overall_points", "—"))
    c4.metric("Bank", f"£{bank:.1f}m")

# ---------------------------------------------------------------- chip hints
hints = build_chip_hints(rows, squad_rows, current_gw, lookahead, bank=bank)
if hints:
    for h in hints:
        st.info(h)

st.divider()

# ------------------------------------------------------------- starting XI
st.subheader(f"🧠 Optimal Starting XI — Gameweek {current_gw}")
if squad_rows:
    xi = pick_starting_xi(list(squad_rows), current_gw)
    if xi["starting_xi"]:
        cols = st.columns([2, 1])
        with cols[0]:
            xi_df = pd.DataFrame([{
                "Player": p["name"], "Pos": p["position"], "Team": p["team_short"],
                "This GW xP": p["_this_gw_xp"],
                "C/VC": "C" if xi["captain"] and p["id"] == xi["captain"]["id"]
                        else ("VC" if xi["vice_captain"] and p["id"] == xi["vice_captain"]["id"] else ""),
            } for p in xi["starting_xi"]])
            st.dataframe(xi_df, hide_index=True, use_container_width=True)
        with cols[1]:
            st.metric("Projected XI points", xi["projected_points"])
            if xi["captain"]:
                st.write(f"**Captain:** {xi['captain']['name']} ({xi['captain']['_this_gw_xp']} xP)")
            if xi["vice_captain"]:
                st.write(f"**Vice:** {xi['vice_captain']['name']} ({xi['vice_captain']['_this_gw_xp']} xP)")
        st.caption("Bench: " + ", ".join(f"{p['name']} ({p['_this_gw_xp']})" for p in xi["bench"]))
    else:
        st.write("Couldn't build a valid XI from your squad data.")
else:
    st.write("Couldn't load your squad — check the Team ID in the sidebar.")

st.divider()

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Top Transfer Candidates (Projected Points)")
    filtered_df = df[
        (df["position"].isin(position)) & (df["price"] <= max_price)
        & (df["minutes"] > 180) & (~df["is_owned"]) & (df["status_ok"])
    ].sort_values(by="xp", ascending=False)
    fig = px.scatter(
        filtered_df.head(25), x="price", y="xp", size="total_points", color="position",
        hover_name="name", hover_data=["form", "xg", "xa", "ownership"], text="name",
        title=f"Price vs Projected Points over next {lookahead} GWs",
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Your Current Squad")
    squad_df = df[df["is_owned"]][["name", "position", "price", "form", "xp", "news"]].sort_values("xp")
    st.dataframe(squad_df, hide_index=True, use_container_width=True)

st.divider()

st.subheader("🔄 Suggested Transfers")
if squad_rows:
    swaps = suggest_transfers(squad_rows, rows, bank, top_n=5, metric="xp")
    if swaps:
        swap_df = pd.DataFrame([{
            "Out": s["out"]["name"], "In": s["in"]["name"], "Position": s["out"]["position"],
            "Cost delta (£m)": round(s["cost_delta"], 1),
            f"xP gain (next {lookahead} GWs)": round(s["gain"], 2),
        } for s in swaps])
        st.dataframe(swap_df, hide_index=True, use_container_width=True)
    else:
        st.write("No clear upgrades found within your bank at current filters.")
else:
    st.write("Couldn't load your squad.")

st.divider()

st.subheader("💎 Differentials")
st.caption(f"Low ownership (≤{max_ownership}%), ranked by projected points — could separate you from your mini-league.")
diffs = find_differentials(rows, max_ownership=max_ownership, top_n=10)
if diffs:
    diff_df = pd.DataFrame([{
        "Player": p["name"], "Pos": p["position"], "Team": p["team_short"], "Price": p["price"],
        "Own%": p["ownership"], "xP": p["xp"],
        "Set piece": "PEN" if p["is_penalty_taker"] else ("Corners/FK" if (p["is_corner_taker"] or p["is_freekick_taker"]) else ""),
    } for p in diffs])
    st.dataframe(diff_df, hide_index=True, use_container_width=True)
else:
    st.write("No differentials found at this ownership threshold.")

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
        dgw_tag = " 🟢DGW" if r["dgw_gws"] else ""
        bgw_tag = " 🔴BGW" if r["bgw_gws"] else ""
        news_tag = f" — ⚠ {r['news']}" if r["news"] else ""
        st.write(f"**{r['name']}** ({r['position']}, {r['team_short']}){dgw_tag}{bgw_tag}: {fx_str}{news_tag}")
