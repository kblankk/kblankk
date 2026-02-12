"""
Fetches real GitHub contributions and generates a drift car SVG animation.
Usage: python generate_drift.py <github_username> <output_path>
"""

import json
import os
import re
import sys
import urllib.request


def fetch_contributions_graphql(username, token):
    """Fetch contribution data from GitHub GraphQL API (requires token)."""
    query = """
    query($userName: String!) {
      user(login: $userName) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
                color
              }
            }
          }
        }
      }
    }
    """

    payload = json.dumps({
        "query": query,
        "variables": {"userName": username}
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "drift-car-generator",
            "Authorization": f"bearer {token}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def fetch_contributions_public(username):
    """Fetch contribution data from the public contributions page (no token needed)."""
    from datetime import datetime, timedelta

    url = f"https://github.com/users/{username}/contributions"
    req = urllib.request.Request(url, headers={"User-Agent": "drift-car-generator"})

    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")

    # Parse the contribution cells from HTML
    # IMPORTANT: GitHub HTML is organized by ROW (all Sundays, then all Mondays, etc.)
    # NOT by column (week). We must use dates to compute correct grid positions.
    pattern = r'data-date="([^"]+)"[^>]*data-level="(\d)"'
    matches = re.findall(pattern, html)

    if not matches:
        raise ValueError("Could not parse contribution data from GitHub page")

    level_colors = {
        "0": "#ebedf0",
        "1": "#9be9a8",
        "2": "#40c463",
        "3": "#30a14e",
        "4": "#216e39",
    }

    # Find the earliest date to use as grid origin (should be a Sunday)
    all_dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in matches]
    first_date = min(all_dates)
    # Ensure first_date is a Sunday (weekday 6 in Python)
    # GitHub weeks start on Sunday
    first_sunday = first_date - timedelta(days=(first_date.weekday() + 1) % 7)

    # Build a dict: (week_col, day_row) -> cell data
    grid = {}
    total = 0
    num_weeks = 0
    for date_str, level in matches:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days_diff = (dt - first_sunday).days
        week_col = days_diff // 7
        day_row = days_diff % 7  # 0=Sunday, 1=Monday, ..., 6=Saturday
        level_int = int(level)
        if level_int > 0:
            total += level_int
        grid[(week_col, day_row)] = {
            "contributionCount": level_int,
            "date": date_str,
            "color": level_colors.get(level, "#ebedf0"),
        }
        num_weeks = max(num_weeks, week_col + 1)

    # Build weeks array in correct column order
    weeks = []
    for c in range(num_weeks):
        days = []
        for r in range(7):
            if (c, r) in grid:
                days.append(grid[(c, r)])
            else:
                days.append({
                    "contributionCount": 0,
                    "date": "",
                    "color": "#ebedf0",
                })
        weeks.append({"contributionDays": days})

    print(f"  Grid: {num_weeks} weeks x 7 days, {total} total contributions")
    # Debug: show contribution positions
    for (wc, dr), cell in sorted(grid.items()):
        if cell["contributionCount"] > 0:
            print(f"  Contrib: week={wc}, day={dr}, date={cell['date']}, count={cell['contributionCount']}")

    return {"totalContributions": total, "weeks": weeks}


def fetch_contributions(username, token=None):
    """Fetch contributions, trying GraphQL first then falling back to public page."""
    if token:
        try:
            print("Trying GraphQL API...")
            return fetch_contributions_graphql(username, token)
        except Exception as e:
            print(f"GraphQL failed: {e}, falling back to public page...")

    print("Fetching from public contributions page...")
    return fetch_contributions_public(username)


# Map GitHub colors to hacker green theme
COLOR_MAP = {
    "#ebedf0": "#161b22",  # no contributions (dark mode empty)
    "#9be9a8": "#003d00",  # level 1
    "#40c463": "#006600",  # level 2
    "#30a14e": "#009900",  # level 3
    "#216e39": "#00ff00",  # level 4
    # Dark mode colors
    "#161b22": "#161b22",  # no contributions
    "#0e4429": "#003d00",  # level 1
    "#006d32": "#006600",  # level 2
    "#26a641": "#009900",  # level 3
    "#39d353": "#00ff00",  # level 4
}


def map_color(github_color):
    """Map GitHub contribution color to hacker green theme."""
    return COLOR_MAP.get(github_color, "#161b22")


def generate_svg(calendar, username):
    """Car goes L→R picking up contributions, floor falls behind the car."""

    weeks = calendar["weeks"]
    total = calendar["totalContributions"]

    CELL = 11
    GAP = 2
    STRIDE = CELL + GAP
    ROWS = 7
    COLS = len(weeks)
    GRID_W = COLS * STRIDE - GAP
    GRID_H = ROWS * STRIDE - GAP

    MARGIN = 40
    W = GRID_W + MARGIN * 2
    H = GRID_H + 70
    GX = MARGIN
    GY = 30
    mid_y = GY + GRID_H / 2

    # ── Find contribution cells ──
    contrib_set = set()
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            if day["contributionCount"] > 0:
                contrib_set.add((c, r))

    # ── Car path: simple L→R straight line ──
    path_d = f"M -30,{mid_y:.1f} L {W + 40:.1f},{mid_y:.1f}"

    # ── Timing ──
    DUR = 12  # seconds for one full pass

    # Column hit percentage (when car center reaches column center)
    def col_pct(c):
        col_x = GX + c * STRIDE + CELL / 2
        # car goes from x=-30 to x=W+40
        frac = (col_x + 30) / (W + 70)
        return max(0, min(frac, 1)) * 90  # 90% = car exits right, 10% pause

    # ══════ BUILD SVG ══════
    L = []
    L.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">')

    # ── Styles ──
    L.append("<style>")

    # Non-contribution cells: fall when car passes their column
    for c in range(COLS):
        hp = col_pct(c)
        L.append(
            f"  @keyframes fall-{c} {{"
            f" 0%,{hp:.1f}% {{ transform:translateY(0); opacity:1; }}"
            f" {min(hp + 5, 95):.1f}% {{ transform:translateY(80px); opacity:0; }}"
            f" 100% {{ transform:translateY(80px); opacity:0; }}"
            f" }}")

    # Contribution cells: glow + collect when car passes their column
    for c, r in contrib_set:
        hp = col_pct(c)
        L.append(
            f"  @keyframes cc-{c}-{r} {{"
            f" 0%,{max(0, hp - 0.5):.1f}% {{ filter:brightness(1); transform:scale(1); opacity:1; }}"
            f" {hp:.1f}% {{ filter:brightness(3); transform:scale(1.6); opacity:1; }}"
            f" {min(hp + 3, 95):.1f}% {{ filter:brightness(4); transform:scale(0); opacity:0; }}"
            f" 100% {{ transform:scale(0); opacity:0; }}"
            f" }}")

    # Car visibility
    L.append(
        f"  @keyframes car-vis {{"
        f" 0% {{ opacity:1; }}"
        f" 92% {{ opacity:1; }}"
        f" 95%,100% {{ opacity:0; }}"
        f" }}")

    L.append("</style>")

    # ── Defs ──
    L.append('<defs>')
    L.append('  <filter id="gl"><feGaussianBlur stdDeviation="1.5" result="b"/>')
    L.append('    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    L.append(f'  <path id="carpath" d="{path_d}" fill="none"/>')
    L.append('</defs>')

    # ── Background ──
    L.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#0d1117"/>')

    # ── Contribution Grid ──
    L.append("<g>")
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            x = GX + c * STRIDE
            y = GY + r * STRIDE
            color = map_color(day["color"])
            ox = x + CELL / 2
            oy = y + CELL / 2
            if (c, r) in contrib_set:
                anim = f"cc-{c}-{r}"
            else:
                anim = f"fall-{c}"
            L.append(
                f'  <rect x="{x:.0f}" y="{y:.0f}" width="{CELL}" height="{CELL}" '
                f'rx="2" fill="{color}" style="animation:{anim} {DUR}s linear infinite;'
                f'transform-origin:{ox:.0f}px {oy:.0f}px"/>')
    L.append("</g>")

    # ── Top-down drift car ──
    L.append(f'<g filter="url(#gl)" style="animation:car-vis {DUR}s linear infinite">')
    L.append(f'  <animateMotion dur="{DUR}s" calcMode="paced" '
             f'repeatCount="indefinite" rotate="auto">')
    L.append(f'    <mpath href="#carpath"/>')
    L.append(f'  </animateMotion>')
    L.append("""  <ellipse cx="0" cy="1" rx="14" ry="7" fill="#000" opacity="0.3"/>
  <path d="M 15,0 Q 14,-3.5 11,-4.5 L 7,-5.5 L 2,-6 L -4,-6 L -9,-5.5 L -12,-5
    Q -15,-4 -15,-1 L -15,1 Q -15,4 -12,5
    L -9,5.5 L -4,6 L 2,6 L 7,5.5 L 11,4.5 Q 14,3.5 15,0 Z
  " fill="#12161f" stroke="#00ff00" stroke-width="0.8"/>
  <line x1="9" y1="-3.5" x2="14" y2="0" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>
  <line x1="9" y1="3.5" x2="14" y2="0" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>
  <path d="M 8,-2 Q 10,0 8,2" fill="none" stroke="#00ff00" stroke-width="0.3" opacity="0.3"/>
  <rect x="7" y="-1.5" width="4" height="3" rx="1" fill="#0d1117" stroke="#00ff00" stroke-width="0.3" opacity="0.5"/>
  <path d="M 4,-5 L 7,-4.5 L 7,4.5 L 4,5 Z" fill="#0a2040" stroke="#00ff00" stroke-width="0.5" opacity="0.7"/>
  <rect x="-5" y="-4.5" width="9" height="9" rx="2" fill="#0d1520" stroke="#00ff00" stroke-width="0.4" opacity="0.6"/>
  <path d="M -7,-4.5 L -5,-5 L -5,5 L -7,4.5 Z" fill="#0a2040" stroke="#00ff00" stroke-width="0.3" opacity="0.5"/>
  <line x1="-14" y1="-7" x2="-14" y2="7" stroke="#00ff00" stroke-width="1.5" opacity="0.8"/>
  <line x1="-14" y1="-6.5" x2="-12" y2="-5" stroke="#00ff00" stroke-width="0.6" opacity="0.5"/>
  <line x1="-14" y1="6.5" x2="-12" y2="5" stroke="#00ff00" stroke-width="0.6" opacity="0.5"/>
  <rect x="8" y="-7.5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>
  <rect x="8" y="5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="-7.5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>
  <circle cx="15" cy="-3.5" r="1.5" fill="#00ff00" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="15" cy="3.5" r="1.5" fill="#00ff00" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <rect x="-15.5" y="-4" width="2" height="2.5" rx="0.5" fill="#ff0033" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite"/>
  </rect>
  <rect x="-15.5" y="1.5" width="2" height="2.5" rx="0.5" fill="#ff0033" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
  </rect>
  <ellipse cx="5" cy="-7" rx="1.8" ry="1" fill="#161b22" stroke="#00ff00" stroke-width="0.3"/>
  <ellipse cx="5" cy="7" rx="1.8" ry="1" fill="#161b22" stroke="#00ff00" stroke-width="0.3"/>
  <circle r="2" fill="#00ff00" opacity="0">
    <animate attributeName="cx" values="-17;-25;-35" dur="0.6s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="0;-1;-2" dur="0.6s" repeatCount="indefinite"/>
    <animate attributeName="r" values="1.5;4;7" dur="0.6s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.1;0.04;0" dur="0.6s" repeatCount="indefinite"/>
  </circle>""")
    L.append("</g>")

    # Footer
    L.append(
        f'<text x="{W / 2:.0f}" y="{H - 4:.0f}" text-anchor="middle" '
        f'font-family="monospace" font-size="10" fill="#00ff00" opacity="0.35">'
        f'{username} // {total} contributions</text>')

    L.append("</svg>")
    return "\n".join(L)


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "kblankk"
    output = sys.argv[2] if len(sys.argv) > 2 else "dist/drift-car.svg"

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("Warning: No GITHUB_TOKEN found. Trying without auth...")

    print(f"Fetching contributions for {username}...")
    calendar = fetch_contributions(username, token)
    print(f"Found {calendar['totalContributions']} contributions in {len(calendar['weeks'])} weeks")

    svg = generate_svg(calendar, username)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"SVG saved to {output}")


if __name__ == "__main__":
    main()
