import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import pandas as pd

TEAM_ID = 152146

def fetch_fpl_data():
    base_url = "https://fantasy.premierleague.com/api/"
    
    # 1. Fetch general FPL data
    bootstrap = requests.get(f"{base_url}bootstrap-static/").json()
    elements = pd.DataFrame(bootstrap['elements'])
    teams = {t['id']: t['short_name'] for t in bootstrap['teams']}
    events = bootstrap['events']
    
    # Identify current Gameweek
    current_gw = next((e['id'] for e in events if e['is_current']), 1)
    
    elements['team_name'] = elements['team'].map(teams)
    elements['now_cost'] = elements['now_cost'] / 10.0
    elements['form'] = pd.to_numeric(elements['form'], errors='coerce').fillna(0)
    elements['selected_by_percent'] = pd.to_numeric(elements['selected_by_percent'], errors='coerce').fillna(0)
    
    # 2. Fetch Manager Overview
    manager_res = requests.get(f"{base_url}entry/{TEAM_ID}/")
    manager_data = manager_res.json() if manager_res.status_code == 200 else {}
    team_name = manager_data.get('name', f'Team {TEAM_ID}')
    overall_rank = manager_data.get('summary_overall_rank', 'N/A')
    overall_pts = manager_data.get('summary_overall_points', 'N/A')
    rank_str = f"{overall_rank:,}" if isinstance(overall_rank, int) else str(overall_rank)
    
    # 3. Fetch User's Squad Picks
    picks_res = requests.get(f"{base_url}entry/{TEAM_ID}/event/{current_gw}/picks/")
    my_player_ids = []
    if picks_res.status_code == 200:
        picks_data = picks_res.json().get('picks', [])
        my_player_ids = [p['element'] for p in picks_data]
        
    my_squad = elements[elements['id'].isin(my_player_ids)].copy() if my_player_ids else pd.DataFrame()
    
    # --- Section A: Team Overview HTML ---
    overview_html = f"""
    <div style="background-color: #f8f9fa; padding: 14px; border-radius: 8px; border-left: 4px solid #37003c; margin-bottom: 20px;">
        <p style="margin: 4px 0; font-size: 15px;"><b>Manager / Team:</b> {team_name}</p>
        <p style="margin: 4px 0; font-size: 15px;"><b>Gameweek:</b> {current_gw} | <b>Total Points:</b> {overall_pts} | <b>Overall Rank:</b> {rank_str}</p>
    </div>
    """
    
    # --- Section B: Captaincy Candidates (Top Form in League) ---
    top_captains = elements.sort_values(by=['form', 'total_points'], ascending=False).head(3)
    cap_rows = "".join([
        f"<tr><td><b>{p['web_name']}</b> ({p['team_name']})</td><td>£{p['now_cost']}m</td><td>{p['form']}</td><td>{p['total_points']} pts</td></tr>"
        for _, p in top_captains.iterrows()
    ])
    
    # --- Section C: Squad Watchlist (Low Form or Flagged) ---
    underperformers_html = ""
    if not my_squad.empty:
        watchlist = my_squad[(my_squad['form'] < 3.0) | (my_squad['status'] != 'a')].head(5)
        if not watchlist.empty:
            status_map = {'a': 'Available', 'd': '75% / Doubtful', 'i': 'Injured', 's': 'Suspended', 'u': 'Unavailable'}
            under_rows = "".join([
                f"<tr><td><b>{p['web_name']}</b> ({p['team_name']})</td><td>{status_map.get(p['status'], p['status'])}</td><td>{p['form']}</td><td>£{p['now_cost']}m</td></tr>"
                for _, p in watchlist.iterrows()
            ])
            underperformers_html = f"""
            <h3 style="color: #b02a37;">⚠️ Squad Watchlist (Flags / Low Form)</h3>
            <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; margin-bottom: 25px;">
                <tr style="background-color: #f8d7da;"><th>Player</th><th>Status</th><th>Form</th><th>Price</th></tr>
                {under_rows}
            </table>
            """
    
    # --- Section D: Top Market Targets ---
    top_targets = elements.sort_values(by='transfers_in_event', ascending=False).head(5)
    target_rows = "".join([
        f"<tr><td><b>{p['web_name']}</b> ({p['team_name']})</td><td>£{p['now_cost']}m</td><td>{p['form']}</td><td>+{p['transfers_in_event']:,}</td></tr>"
        for _, p in top_targets.iterrows()
    ])
    
    return overview_html, cap_rows, underperformers_html, target_rows, current_gw

def send_email():
    email_user = os.getenv('EMAIL_USER')
    email_pass = os.getenv('EMAIL_PASS')
    recipient = os.getenv('RECIPIENT_EMAIL')
    
    if not email_user or not email_pass or not recipient:
        raise ValueError("Missing email environment secrets.")
        
    overview_html, cap_rows, underperformers_html, target_rows, current_gw = fetch_fpl_data()
    
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; max-width: 650px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #37003c; border-bottom: 2px solid #37003c; padding-bottom: 8px;">⚽ Gameweek {current_gw} FPL Briefing</h2>
        
        {overview_html}
        
        <h3 style="color: #37003c;">👑 Top Captaincy Candidates</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; margin-bottom: 25px;">
          <tr style="background-color: #f2f2f2;"><th>Player</th><th>Price</th><th>Form</th><th>Total Pts</th></tr>
          {cap_rows}
        </table>
        
        {underperformers_html}
        
        <h3 style="color: #37003c;">🔥 Top Market Targets (Transferred In)</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; margin-bottom: 25px;">
          <tr style="background-color: #f2f2f2;"><th>Player</th><th>Price</th><th>Form</th><th>Transfers In</th></tr>
          {target_rows}
        </table>
        
        <p style="margin-top: 30px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px;">
            Automated weekly briefing generated via GitHub Actions for Team ID {TEAM_ID}.
        </p>
      </body>
    </html>
    """
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"📊 FPL Gameweek {current_gw} Briefing - Team {TEAM_ID}"
    msg['From'] = email_user
    msg['To'] = recipient
    msg.attach(MIMEText(html, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(email_user, email_pass)
        server.sendmail(email_user, recipient, msg.as_string())

if __name__ == "__main__":
    send_email()
