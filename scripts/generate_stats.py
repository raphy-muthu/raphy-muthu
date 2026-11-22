#!/usr/bin/env python3
"""Build the dark stats card and the yearly contribution heatmap for the profile README.

Needs only the Python standard library.

    GITHUB_TOKEN=...  python scripts/generate_stats.py          # in CI
    python scripts/generate_stats.py                            # locally; falls back to `gh auth token`

Writes:
    assets/stats/stats-dark.svg     totals card
    assets/stats/heatmap-dark.svg   contribution calendar, last 52 weeks

Optional env vars:
    STATS_USER   GitHub login to report on (default: the repo owner, else "raphy-muthu")
    STATS_TITLE  Card title (default: "<display name>'s GitHub Stats")
"""
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "stats"
USER = os.environ.get("STATS_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "raphy-muthu"
DAYS = 365  # length of the heatmap window

# Palette: Sky Blue / White / Hot Pink on GitHub's dark background
C = dict(bg="#0D1117", border="#30363D", grid="#21262D", title="#0593C6", text="#E6EDF3", muted="#8B949E",
         icon="#D83995", line_a="#0593C6", line_b="#D83995",
         levels=["#161B22", "#0F4C6B", "#0877A6", "#2FB3E8", "#D83995"])
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"


def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception:
        sys.exit("No token found. Set GITHUB_TOKEN, or log in with `gh auth login`.")


def graphql(query, tok):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json", "User-Agent": "profile-stats"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "errors" in data:
        sys.exit("GitHub API error: " + json.dumps(data["errors"]))
    return data["data"]


def collect(tok):
    head = graphql('query { user(login: "%s") { name createdAt pullRequests { totalCount } } }' % USER, tok)["user"]
    created = dt.datetime.fromisoformat(head["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)

    parts, y = [], created.year
    while y <= now.year:
        start = max(created, dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(y, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        parts.append(
            'y%d: contributionsCollection(from: "%s", to: "%s") { totalCommitContributions '
            "contributionCalendar { totalContributions } }" % (y, start.isoformat(), end.isoformat())
        )
        y += 1
    last_year = (now - dt.timedelta(days=365)).isoformat()
    parts.append(
        'recent: contributionsCollection(from: "%s", to: "%s") { '
        "commitContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } } "
        "pullRequestContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } } "
        "issueContributionsByRepository(maxRepositories: 100) { repository { nameWithOwner } } }" % (last_year, now.isoformat())
    )
    chart_from = (now - dt.timedelta(days=DAYS)).isoformat()
    parts.append(
        'chart: contributionsCollection(from: "%s", to: "%s") { contributionCalendar { weeks { contributionDays { date contributionCount weekday } } } }'
        % (chart_from, now.isoformat())
    )
    u = graphql('query { user(login: "%s") { %s } }' % (USER, " ".join(parts)), tok)["user"]

    years = [v for k, v in u.items() if k.startswith("y")]
    recent = u["recent"]
    repos = set()
    for key in ("commitContributionsByRepository", "pullRequestContributionsByRepository", "issueContributionsByRepository"):
        repos.update(x["repository"]["nameWithOwner"] for x in recent[key])

    days = {}
    for wk in u["chart"]["contributionCalendar"]["weeks"]:
        for d in wk["contributionDays"]:
            days[d["date"]] = (d["contributionCount"], d["weekday"])
    cutoff = (now - dt.timedelta(days=DAYS - 1)).date()
    series = sorted((dt.date.fromisoformat(k), v[0], v[1]) for k, v in days.items() if dt.date.fromisoformat(k) >= cutoff)

    return {
        "name": head["name"] or USER,
        "contributions": sum(c["contributionCalendar"]["totalContributions"] for c in years),
        "commits": sum(c["totalCommitContributions"] for c in years),
        "prs": head["pullRequests"]["totalCount"],
        "repos": len(repos),
        "series": series,
    }


esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace("'", "&#39;")
stamp = lambda: dt.datetime.now(dt.timezone.utc).strftime("%b %d, %Y").replace(" 0", " ")

# --- tiny hand-drawn icons, 16x16, drawn in the accent color --------------------------------
ICONS = {
    "contributions": '<path d="M2 14V9M6 14V3M10 14V7M14 14V5" />',
    "commits": '<circle cx="8" cy="8" r="3" /><path d="M1 8h4M11 8h4" />',
    "prs": '<circle cx="4" cy="3.5" r="1.8" /><circle cx="4" cy="12.5" r="1.8" /><circle cx="12" cy="12.5" r="1.8" /><path d="M4 5.3v5.4M12 10.7V6a2.5 2.5 0 0 0-2.5-2.5H7.5M9 2l-1.8 1.5L9 5" />',
    "repos": '<path d="M3 2.5h9.5v11H4.5A1.5 1.5 0 0 1 3 12V2.5z" /><path d="M3 12a1.5 1.5 0 0 1 1.5-1.5h8" />',
}


def render_card(stats):
    title = os.environ.get("STATS_TITLE") or f"{stats['name']}'s GitHub Stats"
    rows = [
        ("contributions", "Total Contributions", stats["contributions"]),
        ("commits", "Total Commits", stats["commits"]),
        ("prs", "Total PRs", stats["prs"]),
        ("repos", "Contributed to (last year)", stats["repos"]),
    ]
    w, top, step = 440, 86, 32
    h = top + step * len(rows) + 22
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">',
        f"<title>{esc(title)}</title>",
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="10" fill="{C["bg"]}" stroke="{C["border"]}" />',
        f'<text x="28" y="46" font-family="{FONT}" font-size="19" font-weight="700" fill="{C["title"]}">{esc(title)}</text>',
    ]
    for i, (key, label, value) in enumerate(rows):
        y = top + step * i
        out.append(
            f'<g transform="translate(28 {y - 8})" fill="none" stroke="{C["icon"]}" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS[key]}</g>'
        )
        out.append(f'<text x="56" y="{y + 5}" font-family="{FONT}" font-size="14" font-weight="600" fill="{C["text"]}">{label}:</text>')
        out.append(f'<text x="300" y="{y + 5}" font-family="{FONT}" font-size="14" font-weight="700" fill="{C["text"]}">{value:,}</text>')
    out.append(f'<text x="{w - 28}" y="{h - 14}" text-anchor="end" font-family="{FONT}" font-size="10" fill="{C["muted"]}">Updated {stamp()}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def level(count, peak):
    """0 for no activity; 1-4 split evenly up to the busiest day (which gets the pink top level)."""
    if count <= 0:
        return 0
    return max(1, min(4, -(-4 * count // max(peak, 1))))


def streaks(series):
    """(current, longest) run of days with at least one contribution."""
    longest = run = 0
    for _, n, _ in series:
        run = run + 1 if n > 0 else 0
        longest = max(longest, run)
    cur, rows = 0, list(series)
    if rows and rows[-1][1] == 0:   # today not done yet: the streak is still alive through yesterday
        rows = rows[:-1]
    for _, n, _ in reversed(rows):
        if n > 0:
            cur += 1
        else:
            break
    return cur, longest


def render_heatmap(stats):
    series = stats["series"]
    cell, gap = 13, 3
    pitch = cell + gap
    first_wd = series[0][2]                      # weekday (0 = Sunday) of the first day
    cols = (len(series) + first_wd + 6) // 7
    left, top = 56, 92
    w = left + cols * pitch + 28 - gap
    h = top + 7 * pitch + 74
    peak = max(n for _, n, _ in series)
    total = sum(n for _, n, _ in series)
    cur, longest = streaks(series)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Contribution calendar for the last year">',
        "<title>Contribution calendar, last 52 weeks</title>",
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="14" fill="{C["bg"]}" stroke="{C["border"]}" />',
        f'<text x="30" y="46" font-family="{MONO}" font-size="20" font-weight="700" fill="{C["title"]}"><tspan fill="{C["icon"]}">&gt; </tspan>github activity</text>',
        f'<text x="{w - 30}" y="46" text-anchor="end" font-family="{MONO}" font-size="12" fill="{C["muted"]}">auto-refreshed daily</text>',
    ]
    # month labels
    last_month = None
    for i, (d, _, wd) in enumerate(series):
        col = (i + first_wd) // 7
        if d.month != last_month and (d.day <= 7 or i == 0):
            if not (i == 0 and d.day > 20):   # skip a cramped first label
                out.append(f'<text x="{left + col * pitch}" y="{top - 12}" font-family="{MONO}" font-size="11" fill="{C["muted"]}">{d.strftime("%b")}</text>')
            last_month = d.month
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(f'<text x="{left - 12}" y="{top + row * pitch + cell - 2}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{C["muted"]}">{name}</text>')
    # cells
    for i, (d, n, wd) in enumerate(series):
        col, row = (i + first_wd) // 7, wd
        out.append(
            f'<rect x="{left + col * pitch}" y="{top + row * pitch}" width="{cell}" height="{cell}" rx="3" '
            f'fill="{C["levels"][level(n, peak)]}"><title>{n} contribution{"s" if n != 1 else ""} on {d.strftime("%b %d, %Y").replace(" 0", " ")}</title></rect>'
        )
    # footer
    fy = h - 26
    lx = w - 30 - 5 * pitch - 34
    out.append(f'<text x="{lx - 10}" y="{fy}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{C["muted"]}">Less</text>')
    for k, col in enumerate(C["levels"]):
        out.append(f'<rect x="{lx + k * pitch}" y="{fy - 11}" width="{cell}" height="{cell}" rx="3" fill="{col}" />')
    out.append(f'<text x="{lx + 5 * pitch + 4}" y="{fy}" font-family="{MONO}" font-size="11" fill="{C["muted"]}">More</text>')
    out.append(f'<text x="30" y="{h - 10}" font-family="{MONO}" font-size="9" fill="{C["muted"]}">Updated {stamp()}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    stats = collect(token())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stats-dark.svg").write_text(render_card(stats), encoding="utf-8")
    (OUT / "heatmap-dark.svg").write_text(render_heatmap(stats), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "series"}, indent=2))
    print(f"heatmap: {len(stats['series'])} days, {sum(n for _, n, _ in stats['series'])} contributions")


if __name__ == "__main__":
    main()
