import os
import smtplib
import requests
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TEAM_ID = 152146
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

def get_fpl_data():
    bootstrap = requests.get(BOOTSTRAP_URL).json()
    fixtures = requests.get(FIXTURES_URL).json()
    return bootstrap, fixtures

def get_user_squad(current_gw):
    for gw in range(current_gw, 0, -1):
        res = requests.get(f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/event/{gw}/picks/")
        if res.status_code == 200:
            return res.json().get("picks", [])
    return []

def generate_report():
    bootstrap, fixtures = get_fpl_data()
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    
    current_gw = next((e["id"] for e in bootstrap["events"] if e.get("is_next")), 1)
    squad_picks = get_user_squad(current_gw)
    squad_ids = {p["element"] for p in squad_picks}
    
    elements = pd.DataFrame(bootstrap["elements"])
    elements["position"] = elements["element_type"].map(pos_map)
    elements["price"] = elements["now_cost"] / 10.0
    elements["team_name"] = elements["team"].map(teams)
    elements["form_float"] = pd.to_numeric(elements["form"])

    # Analyze Active Squad
    squad_df = elements[elements["id"].isin(squad_ids)].copy()
    
    # Captaincy Recommendations (Highest form in squad)
    capt_candidates = squad_df.sort_values(by="form_float", ascending=False).head(2)
    c_name = capt_candidates.iloc[0]["web_name"]
    vc_name = capt_candidates.iloc[1]["web_name"]

    # Underperformers in Squad
    underperformers = squad_df.sort_values(by="form_float", ascending=True).head(3)
    
    # Blank / Double Gameweek & Fixture Check for Next GW
    next_gw_fixtures = [f for f in fixtures if f.get("event") == current_gw]
    team_fix_count = {t: 0 for t in teams.keys()}
    for f in next_gw_fixtures:
        team_fix_count[f["team_h"]] += 1
        team_fix_count[f["team_a"]] += 1
        
    squad_df["gw_fixtures"] = squad_df["team"].map(team_fix_count)
    blanks = squad_df[squad_df["gw_fixtures"] == 0]["web_name"].tolist()
    doubles = squad_df[squad_df["gw_fixtures"] > 1]["web_name"].tolist()

    # Top Transfer Suggestions
    targets = elements[~elements["id"].isin(squad_ids) & (elements["minutes"] > 200)]
    top_targets = targets.sort_values(by="form_float", ascending=False).groupby("position").head(2)

    # HTML Email Assembly
    html = f"""
    <h2>Gameweek {current_gw} Transfer & Squad Briefing</h2>
    
    <h3>👑 Captaincy Recommendations</h3>
    <ul>
        <li><b>Captain:</b> {c_name} (Form: {capt_candidates.iloc[0]['form']})</li>
        <li><b>Vice-Captain:</b> {vc_name} (Form: {capt_candidates.iloc[1]['form']})</li>
    </ul>

    <h3>🚨 Fixture Alerts for GW{current_gw}</h3>
    <p><b>Blank Gameweek Players:</b> {', '.join(blanks) if blanks else 'None'}</p>
    <p><b>Double Gameweek Players:</b> {', '.join(doubles) if doubles else 'None'}</p>

    <h3>⚠️ Squad Underperformers (Sell Candidates)</h3>
    <ul>
    """
    for _, row in underperformers.iterrows():
        html += f"<li><b>{row['web_name']}</b> ({row['position']}) - Form: {row['form']} | Price: £{row['price']}M</li>"
    html += "</ul>"

    html += "<h3>🔥 Top Market Targets (Buy Candidates)</h3><ul>"
    for _, row in top_targets.iterrows():
        html += f"<li><b>{row['web_name']}</b> ({row['team_name']} {row['position']}) - Form: {row['form']} | £{row['price']}M</li>"
    html += "</ul>"

    return html, current_gw

def send_email():
    html_content, gw = generate_report()
    sender_email = os.environ["EMAIL_USER"]
    sender_password = os.environ["EMAIL_PASS"]
    recipient_email = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"FPL GW{gw} Briefing - Team 152146"
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())

if __name__ == "__main__":
    send_email()
