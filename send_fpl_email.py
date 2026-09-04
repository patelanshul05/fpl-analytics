import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fpl_common import (
    DEFAULT_TEAM_ID, Weights, build_chip_hints, build_player_rows, build_xp,
    fetch_manager_overview, fetch_squad_by_team_id, find_differentials,
    get_current_gameweek, get_team_upcoming_fixtures, load_fpl_data,
    pick_starting_xi, price_change_watch, score_rows, suggest_transfers,
)

TEAM_ID = int(os.getenv("FPL_TEAM_ID", str(DEFAULT_TEAM_ID)))
LOOKAHEAD = int(os.getenv("FPL_LOOKAHEAD", "5"))

STATUS_MAP = {"a": "Available", "d": "75% / Doubtful", "i": "Injured", "s": "Suspended", "u": "Unavailable"}


def row(cells):
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def table(header_cells, rows_html, empty_message=None):
    if not rows_html and empty_message:
        return f"<p style='color:#777;'>{empty_message}</p>"
    header = "".join(f"<th>{h}</th>" for h in header_cells)
    return (
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse: collapse; width: 100%; margin-bottom: 25px;'>"
        f"<tr style='background-color: #f2f2f2;'>{header}</tr>{''.join(rows_html)}</table>"
    )


def hints_html(hints):
    if not hints:
        return ""
    items = "".join(f"<li style='margin-bottom:4px;'>{h}</li>" for h in hints)
    return f"""
    <div style="background-color: #fff8e1; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #f9a825; margin-bottom: 20px;">
        <b>🃏 Chip timing worth a look</b>
        <ul style="margin: 8px 0 0 0; padding-left: 18px;">{items}</ul>
    </div>
    """


def build_report():
    bootstrap, fixtures = load_fpl_data()
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    current_gw = get_current_gameweek(bootstrap["events"])

    manager = fetch_manager_overview(TEAM_ID)
    team_name = manager.get("team_name", f"Team {TEAM_ID}")
    overall_rank = manager.get("overall_rank")
    overall_pts = manager.get("overall_points", "N/A")
    bank = manager.get("bank", 0.0)
    rank_str = f"{overall_rank:,}" if isinstance(overall_rank, int) else "N/A"

    rows = build_player_rows(bootstrap, fixtures, lookahead=LOOKAHEAD)
    rows = score_rows(rows, Weights())
    rows = build_xp(rows, fixtures, teams, current_gw, LOOKAHEAD)
    by_id = {r["id"]: r for r in rows}

    owned_picks = fetch_squad_by_team_id(TEAM_ID, current_gw)
    squad_rows = [by_id[eid] for eid in owned_picks if eid in by_id]

    overview_html = f"""
    <div style="background-color: #f8f9fa; padding: 14px; border-radius: 8px; border-left: 4px solid #37003c; margin-bottom: 20px;">
        <p style="margin: 4px 0; font-size: 15px;"><b>Manager / Team:</b> {team_name}</p>
        <p style="margin: 4px 0; font-size: 15px;"><b>Gameweek:</b> {current_gw} | <b>Total Points:</b> {overall_pts} | <b>Overall Rank:</b> {rank_str}</p>
        <p style="margin: 4px 0; font-size: 15px;"><b>Money in the bank:</b> £{bank:.1f}m</p>
    </div>
    """

    chips_html = hints_html(build_chip_hints(rows, squad_rows, current_gw, LOOKAHEAD, bank=bank))

    # --- Optimal Starting XI + Captain ---
    xi_html = ""
    if squad_rows:
        xi = pick_starting_xi(list(squad_rows), current_gw)
        if xi["starting_xi"]:
            xi_rows = [
                row([f"<b>{p['name']}</b>", p['position'],
                     "👑 C" if xi["captain"] and p["id"] == xi["captain"]["id"]
                     else ("VC" if xi["vice_captain"] and p["id"] == xi["vice_captain"]["id"] else ""),
                     f"{p['_this_gw_xp']:.2f}"])
                for p in xi["starting_xi"]
            ]
            bench_str = ", ".join(f"{p['name']} ({p['_this_gw_xp']:.1f})" for p in xi["bench"])
            xi_html = f"""
            <h3 style="color: #37003c;">🧠 Optimal Starting XI — GW{current_gw} (projected {xi['projected_points']} pts)</h3>
            {table(['Player', 'Pos', 'C/VC', 'xP'], xi_rows)}
            <p style="font-size: 13px; color: #666;"><b>Bench:</b> {bench_str}</p>
            """

    # --- Squad Watchlist, with next fixture + news ---
    watchlist_html = ""
    if squad_rows:
        watchlist = [r for r in squad_rows if r["form"] < 3.0 or not r["status_ok"]][:5]
        if watchlist:
            watch_rows = []
            for p in watchlist:
                fx = get_team_upcoming_fixtures(fixtures, teams, p["team_id"], current_gw, 3)
                next_fx = ", ".join(f"{f['opponent']}({'H' if f['home'] else 'A'})" for f in fx[:2]) or "—"
                news = p["news"] or "—"
                watch_rows.append(row([
                    f"<b>{p['name']}</b> ({p['team_short']})", STATUS_MAP.get(p['status'], p['status']),
                    p['form'], f"£{p['price']:.1f}m", next_fx, news,
                ]))
            watchlist_html = f"""
            <h3 style="color: #b02a37;">⚠️ Squad Watchlist</h3>
            {table(['Player', 'Status', 'Form', 'Price', 'Next fixtures', 'News'], watch_rows)}
            """

    # --- Suggested Transfers, by xP gain ---
    transfers_html = ""
    if squad_rows:
        swaps = suggest_transfers(squad_rows, rows, bank, top_n=5, metric="xp")
        swap_rows = [
            row([f"<b>{s['out']['name']}</b> → <b>{s['in']['name']}</b>", s['out']['position'],
                 f"£{s['cost_delta']:+.1f}m", f"{s['gain']:+.2f}",
                 f"{s['in']['fixture_score']:.1f}"])
            for s in swaps
        ]
        transfers_html = f"""
        <h3 style="color: #37003c;">🔄 Suggested Transfers</h3>
        {table(['Swap', 'Pos', 'Cost delta', f'xP gain ({LOOKAHEAD} GWs)', "In's fixture ease"], swap_rows,
               "No upgrades found within your bank right now.")}
        """

    # --- Top Targets, by xP ---
    top_targets = sorted(
        [r for r in rows if r["id"] not in owned_picks and r["status_ok"] and r["meets_minutes_floor"]],
        key=lambda r: r["xp"], reverse=True,
    )[:5]
    target_rows = [
        row([f"<b>{p['name']}</b> ({p['team_short']})", p['position'], f"£{p['price']:.1f}m",
             p['form'], f"{p['xp']:.2f}",
             "PEN" if p["is_penalty_taker"] else ("SP" if (p["is_corner_taker"] or p["is_freekick_taker"]) else "")])
        for p in top_targets
    ]
    targets_table = table(["Player", "Pos", "Price", "Form", f"xP ({LOOKAHEAD} GWs)", "Set piece"], target_rows)

    # --- Differentials ---
    diffs = find_differentials(rows, max_ownership=10.0, top_n=5)
    diff_rows = [
        row([f"<b>{p['name']}</b> ({p['team_short']})", p['position'], f"£{p['price']:.1f}m",
             f"{p['ownership']:.1f}%", f"{p['xp']:.2f}"])
        for p in diffs
    ]
    diffs_table = table(["Player", "Pos", "Price", "Own%", f"xP ({LOOKAHEAD} GWs)"], diff_rows,
                         "None found under 10% ownership.")

    # --- Price Change Watch ---
    watch = price_change_watch(rows)
    rising_rows = [row([f"{p['name']} ({p['team_short']})", f"£{p['price']:.1f}m", p['net_transfers']])
                   for p in watch["rising_soon"]]
    falling_rows = [row([f"{p['name']} ({p['team_short']})", f"£{p['price']:.1f}m", p['net_transfers']])
                    for p in watch["falling_soon"]]
    price_watch_html = f"""
    <h3 style="color: #37003c;">📈 Price Change Watch</h3>
    <table style="width:100%;"><tr>
      <td style="vertical-align:top; width:50%; padding-right:10px;">
        <b>Rising soon</b>{table(['Player', 'Price', 'Net transfers'], rising_rows, 'None flagged.')}
      </td>
      <td style="vertical-align:top; width:50%; padding-left:10px;">
        <b>Falling soon</b>{table(['Player', 'Price', 'Net transfers'], falling_rows, 'None flagged.')}
      </td>
    </tr></table>
    <p style="font-size:11px; color:#999;">Heuristic based on today's net transfer momentum — not an exact predictor.</p>
    """

    return {
        "current_gw": current_gw, "overview_html": overview_html, "chips_html": chips_html,
        "xi_html": xi_html, "watchlist_html": watchlist_html, "transfers_html": transfers_html,
        "targets_table": targets_table, "diffs_table": diffs_table, "price_watch_html": price_watch_html,
    }


def send_email():
    email_user = os.getenv("EMAIL_USER")
    email_pass = os.getenv("EMAIL_PASS")
    recipient = os.getenv("RECIPIENT_EMAIL")
    if not email_user or not email_pass or not recipient:
        raise ValueError("Missing email environment secrets.")

    r = build_report()

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; max-width: 650px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #37003c; border-bottom: 2px solid #37003c; padding-bottom: 8px;">⚽ Gameweek {r['current_gw']} FPL Briefing</h2>
        {r['overview_html']}
        {r['chips_html']}
        {r['xi_html']}
        {r['watchlist_html']}
        {r['transfers_html']}
        <h3 style="color: #37003c;">🎯 Top Targets (projected points)</h3>
        {r['targets_table']}
        <h3 style="color: #37003c;">💎 Differentials (≤10% owned)</h3>
        {r['diffs_table']}
        {r['price_watch_html']}
        <p style="margin-top: 30px; font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 10px;">
            Automated weekly briefing generated via GitHub Actions for Team ID {TEAM_ID}.
        </p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 FPL Gameweek {r['current_gw']} Briefing - Team {TEAM_ID}"
    msg["From"] = email_user
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(email_user, email_pass)
        server.sendmail(email_user, recipient, msg.as_string())


if __name__ == "__main__":
    send_email()
