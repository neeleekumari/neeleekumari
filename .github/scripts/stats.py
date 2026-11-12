#!/usr/bin/env python3
"""Generate self-hosted profile SVGs (stats, languages, activity) from the GitHub API.

Usage:  python stats.py <out_dir>
Env:    GITHUB_TOKEN  (provided automatically inside GitHub Actions)
        GH_LOGIN      (defaults to the repo owner)
        MOCK=1        (render with fake data, for local testing only)
No third-party packages needed.
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.request
from html import escape

LOGIN = os.environ.get("GH_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "neeleekumari"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = sys.argv[1] if len(sys.argv) > 1 else "dist"

BG, BORDER, AMBER = "#0d1117", "#30363d", "#ffb000"
TEXT, MUTED, PANEL = "#c9d1d9", "#8b949e", "#161b22"
SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace"
LANG_COLORS = ["#ffb000", "#ff7a00", "#ff4d4d", "#f2d06b", "#4fd1c5", "#7aa2f7", "#c792ea"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def esc(s):
    return escape(str(s), quote=True)


def fetch():
    body = json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("errors") or not payload.get("data", {}).get("user"):
        raise SystemExit(f"GitHub API error: {payload.get('errors') or 'user not found'}")
    return payload["data"]["user"]


def mock():
    import random

    random.seed(7)
    today = dt.date.today()
    start = today - dt.timedelta(days=370)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday
    weeks, d = [], start
    while d <= today:
        days = []
        for _ in range(7):
            if d <= today:
                c = random.choice([0, 0, 0, 1, 2, 3, 5, 8]) if d < today - dt.timedelta(days=3) else 2
                days.append({"date": d.isoformat(), "contributionCount": c})
            d += dt.timedelta(days=1)
        weeks.append({"contributionDays": days})
    total = sum(x["contributionCount"] for w in weeks for x in w["contributionDays"])
    langs = [("Python", 52000), ("TypeScript", 41000), ("JavaScript", 18000), ("CSS", 9000), ("HTML", 5000), ("Java", 3000), ("C", 1500), ("SQL", 900)]
    return {
        "followers": {"totalCount": 4},
        "contributionsCollection": {
            "totalPullRequestContributions": 3,
            "contributionCalendar": {"totalContributions": total, "weeks": weeks},
        },
        "repositories": {
            "totalCount": 5,
            "nodes": [
                {"stargazerCount": 2, "languages": {"edges": [{"size": s, "node": {"name": n}} for n, s in langs]}}
            ],
        },
    }


def parse_days(user):
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = []
    for w in weeks:
        for x in w["contributionDays"]:
            days.append((dt.date.fromisoformat(x["date"]), x["contributionCount"]))
    days.sort()
    return weeks, days


def streaks(days):
    i = len(days) - 1
    if i >= 0 and days[i][1] == 0:  # today has no contribution yet: streak may still be alive
        i -= 1
    cur, cur_end = 0, (days[i][0] if i >= 0 else None)
    while i >= 0 and days[i][1] > 0:
        cur += 1
        i -= 1
    cur_start = days[i + 1][0] if cur else None
    if not cur:
        cur_end = None
    best = run = 0
    run_start = best_start = best_end = None
    for d, c in days:
        if c > 0:
            if run == 0:
                run_start = d
            run += 1
            if run > best:
                best, best_start, best_end = run, run_start, d
        else:
            run = 0
    return cur, (cur_start, cur_end), best, (best_start, best_end)


def fmt_range(r):
    s, e = r
    if not s or not e:
        return "-"
    return f"{s:%b} {s.day} - {e:%b} {e.day}"


def card_open(w, h, title, right=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">'
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="12" fill="{BG}" stroke="{BORDER}"/>'
        f'<rect x="0.5" y="0.5" width="{w-1}" height="38" rx="12" fill="{PANEL}"/>'
        f'<rect x="0.5" y="26" width="{w-1}" height="13" fill="{PANEL}"/>'
        f'<line x1="0" y1="38.5" x2="{w}" y2="38.5" stroke="{BORDER}"/>'
        f'<circle cx="20" cy="19.5" r="5" fill="#ff5f56"/><circle cx="38" cy="19.5" r="5" fill="#ffbd2e"/><circle cx="56" cy="19.5" r="5" fill="#27c93f"/>'
        f'<text x="76" y="24" font-family="{MONO}" font-size="13" fill="{AMBER}" font-weight="600">{esc(title)}</text>'
        f'<text x="{w-18}" y="24" text-anchor="end" font-family="{MONO}" font-size="11" fill="{MUTED}">{esc(right)}</text>'
    )


def stats_svg(user, days):
    total = user["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    cur, cur_r, best, best_r = streaks(days)
    repos = user["repositories"]["totalCount"]
    stars = sum(n["stargazerCount"] for n in user["repositories"]["nodes"])
    followers = user["followers"]["totalCount"]
    prs = user["contributionsCollection"]["totalPullRequestContributions"]
    W, H = 560, 250
    circ = 2 * math.pi * 38
    s = card_open(W, H, "~/stats", "last 12 months")
    # columns
    cols = [(100, f"{total:,}", "Total Contributions", "past year"), (280, None, "Current Streak", fmt_range(cur_r)), (460, f"{best:,}", "Longest Streak", fmt_range(best_r))]
    for x, big, label, sub in cols:
        if big is not None:
            s += f'<text x="{x}" y="122" text-anchor="middle" font-family="{SANS}" font-size="38" font-weight="700" fill="{TEXT}">{big}</text>'
        s += f'<text x="{x}" y="{168 if big is None else 158}" text-anchor="middle" font-family="{SANS}" font-size="15" font-weight="600" fill="{AMBER if big is None else TEXT}">{label}</text>'
        s += f'<text x="{x}" y="{188 if big is None else 178}" text-anchor="middle" font-family="{MONO}" font-size="11" fill="{MUTED}">{esc(sub)}</text>'
    # streak ring
    frac = min(cur / 30, 1) if cur else 0
    s += f'<circle cx="280" cy="108" r="38" fill="none" stroke="{PANEL}" stroke-width="6"/>'
    if frac:
        arc = circ * max(frac, 0.08)
        s += (
            f'<circle cx="280" cy="108" r="38" fill="none" stroke="{AMBER}" stroke-width="6" stroke-linecap="round" '
            f'stroke-dasharray="{arc:.1f} {circ:.1f}" transform="rotate(-90 280 108)">'
            f'<animate attributeName="stroke-dasharray" from="0 {circ:.1f}" to="{arc:.1f} {circ:.1f}" dur="1.2s" fill="freeze"/></circle>'
        )
    s += f'<text x="280" y="120" text-anchor="middle" font-family="{SANS}" font-size="34" font-weight="700" fill="{AMBER}">{cur}</text>'
    s += f'<line x1="190" y1="62" x2="190" y2="196" stroke="{BORDER}"/><line x1="370" y1="62" x2="370" y2="196" stroke="{BORDER}"/>'
    # bottom strip
    s += f'<line x1="20" y1="208" x2="{W-20}" y2="208" stroke="{BORDER}"/>'
    items = [("repos", repos), ("stars", stars), ("followers", followers), ("PRs", prs)]
    step = (W - 40) / len(items)
    for i, (k, v) in enumerate(items):
        cx = 20 + step * i + step / 2
        s += (
            f'<text x="{cx:.0f}" y="235" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">'
            f'{k} <tspan fill="{AMBER}" font-weight="700">{v}</tspan></text>'
        )
    return s + "</svg>"


def langs_svg(user):
    totals = {}
    for repo in user["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            totals[e["node"]["name"]] = totals.get(e["node"]["name"], 0) + e["size"]
    W, H = 340, 250
    s = card_open(W, H, "~/top-languages", "by code size")
    grand = sum(totals.values())
    if not grand:
        return s + f'<text x="{W/2}" y="140" text-anchor="middle" font-family="{MONO}" font-size="13" fill="{MUTED}">no language data yet</text></svg>'
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top, rest = ranked[:6], sum(v for _, v in ranked[6:])
    rows = [(n, v, LANG_COLORS[i]) for i, (n, v) in enumerate(top)]
    if rest:
        rows.append(("Other", rest, MUTED))
    bx, bw = 20, W - 40
    s += f'<clipPath id="bar"><rect x="{bx}" y="56" width="{bw}" height="10" rx="5"/></clipPath><g clip-path="url(#bar)">'
    x = bx
    for _, v, c in rows:
        w = bw * v / grand
        s += f'<rect x="{x:.2f}" y="56" width="{w+0.5:.2f}" height="10" fill="{c}"/>'
        x += w
    s += "</g>"
    for i, (n, v, c) in enumerate(rows):
        y = 94 + i * 22
        s += (
            f'<circle cx="26" cy="{y-4}" r="5" fill="{c}"/>'
            f'<text x="40" y="{y}" font-family="{SANS}" font-size="13" fill="{TEXT}">{esc(n)}</text>'
            f'<text x="{W-20}" y="{y}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{MUTED}">{100*v/grand:.1f}%</text>'
        )
    return s + "</svg>"


def nice_ceiling(n):
    if n <= 5:
        return 5
    mag = 10 ** int(math.log10(n))
    for m in (1, 2, 2.5, 5, 10):
        if n <= m * mag:
            return m * mag
    return 10 * mag


def activity_svg(weeks):
    sums = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks]
    firsts = [dt.date.fromisoformat(w["contributionDays"][0]["date"]) for w in weeks]
    n = len(sums)
    W, H = 900, 250
    x0, x1, yt, yb = 60, 872, 66, 206
    top = nice_ceiling(max(sums) if sums else 1)

    def X(i):
        return x0 + i * (x1 - x0) / max(n - 1, 1)

    def Y(v):
        return yb - (v / top) * (yb - yt)

    s = card_open(W, H, "~/contribution-activity", "weekly contributions, past year")
    s += (
        f'<defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{AMBER}" stop-opacity="0.45"/><stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></linearGradient></defs>'
    )
    for frac in (0, 0.5, 1):
        v, y = top * frac, Y(top * frac)
        label = f"{v:g}"
        s += f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{BORDER}" stroke-dasharray="3 5"/>'
        s += f'<text x="{x0-10}" y="{y+4:.1f}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{MUTED}">{label}</text>'
    if n:
        d = f"M{X(0):.1f} {Y(sums[0]):.1f}"
        for i in range(1, n):
            mx = (X(i - 1) + X(i)) / 2
            d += f" C{mx:.1f} {Y(sums[i-1]):.1f} {mx:.1f} {Y(sums[i]):.1f} {X(i):.1f} {Y(sums[i]):.1f}"
        s += f'<path d="{d} L{X(n-1):.1f} {yb} L{X(0):.1f} {yb} Z" fill="url(#fill)"><animate attributeName="opacity" from="0" to="1" dur="1.4s" fill="freeze"/></path>'
        s += (
            f'<path d="{d}" fill="none" stroke="{AMBER}" stroke-width="2.5" stroke-linecap="round" pathLength="1" '
            f'stroke-dasharray="1" stroke-dashoffset="1"><animate attributeName="stroke-dashoffset" from="1" to="0" dur="1.6s" fill="freeze"/></path>'
        )
        s += f'<circle cx="{X(n-1):.1f}" cy="{Y(sums[-1]):.1f}" r="4" fill="{AMBER}"/><circle cx="{X(n-1):.1f}" cy="{Y(sums[-1]):.1f}" r="9" fill="none" stroke="{AMBER}" stroke-opacity="0.5"><animate attributeName="r" values="4;11;4" dur="2.4s" repeatCount="indefinite"/></circle>'
        last_m, last_i = None, -10
        for i, f in enumerate(firsts):
            if f.month != last_m and i - last_i >= 3:
                s += f'<text x="{X(i):.1f}" y="{yb+22}" text-anchor="middle" font-family="{MONO}" font-size="11" fill="{MUTED}">{f:%b}</text>'
                last_i = i
            last_m = f.month
    return s + "</svg>"


def main():
    user = mock() if os.environ.get("MOCK") else fetch()
    weeks, days = parse_days(user)
    os.makedirs(OUT, exist_ok=True)
    for name, svg in (("stats.svg", stats_svg(user, days)), ("languages.svg", langs_svg(user)), ("activity.svg", activity_svg(weeks))):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
            fh.write(svg)
        print("wrote", os.path.join(OUT, name))


if __name__ == "__main__":
    main()
