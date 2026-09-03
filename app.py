import streamlit as st
import requests
import pandas as pd
import plotly.express as px

TEAM_ID = 152146
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

st.set_page_config(page_title="FPL Analytics Dashboard", layout="wide")
st.title("⚽ FPL Transfer & Squad Analyzer")

@st.cache_data(ttl=3600)
def load_fpl_data():
    bootstrap = requests.get(BOOTSTRAP_URL).json()
    fixtures = requests.get(FIXTURES_URL).json()
    return bootstrap, fixtures

@st.cache_data(ttl=3600)
def load_user_squad(current_gw):
    for gw in range(current_gw, 0, -1):
        url = f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/event/{gw}/picks/"
        res = requests.get(url)
        if res.status_code == 200:
            return {p["element"] for p in res.json().get("picks", [])}
    return set()

bootstrap, fixtures = load_fpl_data()
teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

current_gw = next((e["id"] for e in bootstrap["events"] if e.get("is_next")), 1)
user_squad_ids = load_user_squad(current_gw - 1)

# Sidebar Filters
st.sidebar.header("Filter Settings")
position = st.sidebar.multiselect("Position", ["GKP", "DEF", "MID", "FWD"], default=["MID", "FWD"])
max_price = st.sidebar.slider("Max Price (£M)", 4.0, 15.0, 12.5, 0.5)

# Data Processing
df = pd.DataFrame(bootstrap["elements"])
df["position"] = df["element_type"].map(pos_map)
df["price"] = df["now_cost"] / 10.0
df["team_name"] = df["team"].map(teams)
df["xGI_90"] = (pd.to_numeric(df["expected_goal_involvements"]) / df["minutes"].replace(0, 1)) * 90
df["is_owned"] = df["id"].isin(user_squad_ids)

filtered_df = df[
    (df["position"].isin(position)) & 
    (df["price"] <= max_price) & 
    (df["minutes"] > 180)
].sort_values(by="xGI_90", ascending=False)

# Dashboard Layout
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Top Transfer Candidates (xGI per 90)")
    fig = px.scatter(
        filtered_df.head(25),
        x="price",
        y="xGI_90",
        size="total_points",
        color="position",
        hover_name="web_name",
        text="web_name",
        title="Price vs underlying Threat (xGI/90)"
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Your Current Squad")
    squad_df = df[df["is_owned"]][["web_name", "position", "price", "form", "total_points"]]
    st.dataframe(squad_df, hide_index=True, use_container_width=True)
