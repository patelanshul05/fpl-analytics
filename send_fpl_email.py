import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import pandas as pd

TEAM_ID = 152146

def get_fpl_data():
    base_url = "https://fantasy.premierleague.com/api/"
    bootstrap = requests.get(f"{base_url}bootstrap-static/").json()
    my_team = requests.get(f"{base_url}my-team/{TEAM_ID}/").json() if TEAM_ID else None
    
    # Process market targets (Top 5 Transferred In)
    elements_df = pd.DataFrame(bootstrap['elements'])
    elements_df['now_cost'] = elements_df['now_cost'] / 10.0
    elements_df['form'] = pd.to_numeric(elements_df['form'])
    
    top_targets = elements_df.sort_values(by='transfers_in_event', ascending=False).head(5)
    
    target_rows = ""
    for _, player in top_targets.iterrows():
        target_rows += f"<tr><td><b>{player['web_name']}</b></td><td>£{player['now_cost']}m</td><td>{player['form']}</td><td>+{player['transfers_in_event']:,}</td></tr>"
        
    return target_rows

def send_email():
    email_user = os.getenv('EMAIL_USER')
    email_pass = os.getenv('EMAIL_PASS')
    recipient = os.getenv('RECIPIENT_EMAIL')
    
    if not email_user or not email_pass or not recipient:
        raise ValueError("Missing email environment secrets.")
        
    target_rows = get_fpl_data()
    
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333;">
        <h2>⚽ Weekly FPL Briefing (Team {TEAM_ID})</h2>
        <p>Here is your weekly transfer and market briefing:</p>
        
        <h3>🔥 Top Market Targets (Most Transferred In)</h3>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
          <tr style="background-color: #f2f2f2;">
            <th>Player</th><th>Price</th><th>Form</th><th>Transfers In</th>
          </tr>
          {target_rows}
        </table>
        
        <p style="margin-top: 20px; font-size: 12px; color: #777;">Generated automatically via GitHub Actions.</p>
      </body>
    </html>
    """
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"FPL Gameweek Report - Team {TEAM_ID}"
    msg['From'] = email_user
    msg['To'] = recipient
    msg.attach(MIMEText(html, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(email_user, email_pass)
        server.sendmail(email_user, recipient, msg.as_string())

if __name__ == "__main__":
    send_email()
