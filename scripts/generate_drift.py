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


# Map GitHub colors to hacker red theme
COLOR_MAP = {
    "#ebedf0": "#161b22",  # no contributions (dark mode empty)
    "#9be9a8": "#3d0000",  # level 1
    "#40c463": "#660000",  # level 2
    "#30a14e": "#990000",  # level 3
    "#216e39": "#ff0000",  # level 4
    # Dark mode colors
    "#161b22": "#161b22",  # no contributions
    "#0e4429": "#3d0000",  # level 1
    "#006d32": "#660000",  # level 2
    "#26a641": "#990000",  # level 3
    "#39d353": "#ff0000",  # level 4
}


def map_color(github_color):
    """Map GitHub contribution color to hacker red theme."""
    return COLOR_MAP.get(github_color, "#161b22")


def generate_svg(calendar, username):
    """Car goes L→R targeting contributions, floor falls behind car."""
    import math

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

    # ── Find contribution cells sorted L→R, then top→bottom ──
    contrib_set = set()
    contrib_cells = []
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            if day["contributionCount"] > 0:
                cx = GX + c * STRIDE + CELL / 2
                cy = GY + r * STRIDE + CELL / 2
                contrib_cells.append((c, r, cx, cy))
                contrib_set.add((c, r))
    # Already sorted by column then row due to enumeration order

    # ── Car path: L→R through each contribution cell ──
    # Waypoints: enter left → each contribution → exit right
    wp = [(-30, mid_y)]
    for _, _, cx, cy in contrib_cells:
        wp.append((cx, cy))
    wp.append((W + 40, wp[-1][1] if contrib_cells else mid_y))

    # Compute cumulative arc lengths for timing
    def dist(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])
    seg = [dist(wp[i - 1], wp[i]) for i in range(1, len(wp))]
    total_len = sum(seg)
    cum = [0]
    for s in seg:
        cum.append(cum[-1] + s)

    # Percentage of total path at each waypoint
    # calcMode="paced" uses 100% of DUR for 100% of path length
    def wp_pct(idx):
        return cum[idx] / total_len * 100

    # Build path
    path_d = f"M {wp[0][0]:.1f},{wp[0][1]:.1f}"
    for i in range(1, len(wp)):
        path_d += f" L {wp[i][0]:.1f},{wp[i][1]:.1f}"

    # ── Column timing: use the LAST time the car passes each column ──
    col_time = {}
    for c in range(COLS):
        col_x = GX + c * STRIDE + CELL / 2
        latest = -1
        for i in range(1, len(wp)):
            x0, x1 = wp[i - 1][0], wp[i][0]
            if min(x0, x1) <= col_x <= max(x0, x1) and x0 != x1:
                frac = (col_x - x0) / (x1 - x0)
                t = (cum[i - 1] + frac * seg[i - 1]) / total_len * 100
                latest = max(latest, t)
            elif abs(x0 - col_x) < STRIDE and abs(x1 - col_x) < STRIDE:
                t = cum[i] / total_len * 100
                latest = max(latest, t)
        if latest < 0:
            latest = (col_x + 30) / (W + 70) * 100
        # +2% delay so floor falls AFTER car passes
        col_time[c] = min(latest + 2, 99)

    # Contribution hit times (exact waypoint times)
    contrib_time = {}
    for j, (c, r, _, _) in enumerate(contrib_cells):
        contrib_time[(c, r)] = wp_pct(j + 1)

    DUR = 10

    # ══════ BUILD SVG ══════
    L = []
    L.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">')

    # ── Styles ──
    L.append("<style>")

    # Non-contribution cells: fall AFTER car passes their column
    for c in range(COLS):
        hp = col_time.get(c, 0)
        L.append(
            f"  @keyframes fall-{c} {{"
            f" 0%,{hp:.1f}% {{ transform:translateY(0); opacity:1; }}"
            f" {min(hp + 4, 99.5):.1f}% {{ transform:translateY(80px); opacity:0; }}"
            f" 100% {{ transform:translateY(80px); opacity:0; }}"
            f" }}")

    # Contribution cells: glow + vanish when car reaches them
    for (c, r), hp in contrib_time.items():
        L.append(
            f"  @keyframes cc-{c}-{r} {{"
            f" 0%,{max(0, hp - 0.5):.1f}% {{ filter:brightness(1); transform:scale(1); opacity:1; }}"
            f" {hp:.1f}% {{ filter:brightness(3); transform:scale(1.6); opacity:1; }}"
            f" {min(hp + 2.5, 99.5):.1f}% {{ filter:brightness(4); transform:scale(0); opacity:0; }}"
            f" 100% {{ transform:scale(0); opacity:0; }}"
            f" }}")

    # ── Trail drawing (tire marks) ──
    L.append(
        f"  @keyframes trail-draw {{"
        f" 0% {{ stroke-dashoffset:1; }}"
        f" 100% {{ stroke-dashoffset:0; }}"
        f" }}")

    # ── Finish line celebration ──
    finish_pct = col_time.get(COLS - 1, 95)
    L.append(
        f"  @keyframes finish-flash {{"
        f" 0%,{finish_pct:.1f}% {{ opacity:0; }}"
        f" {min(finish_pct + 0.5, 99):.1f}% {{ opacity:1; }}"
        f" {min(finish_pct + 4, 99.5):.1f}% {{ opacity:0; }}"
        f" 100% {{ opacity:0; }}"
        f" }}")
    # Confetti particles at finish
    import random
    random.seed(42)
    for i in range(12):
        dx = random.uniform(-100, 100)
        dy = random.uniform(-80, 20)
        L.append(
            f"  @keyframes confetti-{i} {{"
            f" 0%,{finish_pct:.1f}% {{ opacity:0; transform:translate(0,0) rotate(0deg); }}"
            f" {min(finish_pct + 0.5, 99):.1f}% {{ opacity:1; transform:translate(0,0) rotate(0deg); }}"
            f" {min(finish_pct + 5, 99.5):.1f}% {{ opacity:0; transform:translate({dx:.0f}px,{dy:.0f}px) rotate({random.randint(180, 720)}deg); }}"
            f" 100% {{ opacity:0; }}"
            f" }}")

    # ── Sparkle on contribution collect ──
    for (c, r), hp in contrib_time.items():
        for si in range(3):
            angle = si * 120
            sdx = math.cos(math.radians(angle)) * 20
            sdy = math.sin(math.radians(angle)) * 20
            L.append(
                f"  @keyframes spark-{c}-{r}-{si} {{"
                f" 0%,{max(0, hp - 0.2):.1f}% {{ opacity:0; transform:translate(0,0) scale(1); }}"
                f" {hp:.1f}% {{ opacity:1; transform:translate(0,0) scale(1); }}"
                f" {min(hp + 2, 99.5):.1f}% {{ opacity:0; transform:translate({sdx:.0f}px,{sdy:.0f}px) scale(0); }}"
                f" 100% {{ opacity:0; }}"
                f" }}")

    # ── Finish line flag wave ──
    L.append(
        f"  @keyframes flag-wave {{"
        f" 0%,100% {{ transform:skewX(0deg); }}"
        f" 25% {{ transform:skewX(3deg); }}"
        f" 75% {{ transform:skewX(-3deg); }}"
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

    # ── Finish line (checkered flag) at right edge ──
    fl_x = GX + GRID_W + 8  # just after last column
    fl_y = GY - 5
    fl_h = GRID_H + 10
    sq = 6  # checker square size
    L.append(f'<g style="animation:flag-wave 1.5s ease-in-out infinite;'
             f'transform-origin:{fl_x + sq}px {fl_y + fl_h / 2:.0f}px">')
    for row in range(int(fl_h / sq) + 1):
        for col in range(2):
            fx = fl_x + col * sq
            fy = fl_y + row * sq
            if fy + sq > fl_y + fl_h:
                continue
            is_dark = (row + col) % 2 == 0
            fill = "#ff0000" if is_dark else "#0d1117"
            opacity = "0.6" if is_dark else "0.3"
            L.append(
                f'  <rect x="{fx}" y="{fy}" width="{sq}" height="{sq}" '
                f'fill="{fill}" opacity="{opacity}" stroke="#ff0000" stroke-width="0.3"/>')
    L.append('</g>')

    # ── Trail / tire marks ──
    L.append(
        f'<path d="{path_d}" fill="none" stroke="#ff0000" stroke-width="1" '
        f'opacity="0.15" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1" '
        f'style="animation:trail-draw {DUR}s linear infinite"/>')
    # Second trail (faint, wider)
    L.append(
        f'<path d="{path_d}" fill="none" stroke="#ff0000" stroke-width="3" '
        f'opacity="0.05" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1" '
        f'style="animation:trail-draw {DUR}s linear infinite"/>')

    # ── Sparkles on contribution collect ──
    for (c, r), hp in contrib_time.items():
        sx = GX + c * STRIDE + CELL / 2
        sy = GY + r * STRIDE + CELL / 2
        for si in range(3):
            L.append(
                f'  <circle cx="{sx:.0f}" cy="{sy:.0f}" r="1.5" fill="#ff0000" '
                f'filter="url(#gl)" '
                f'style="animation:spark-{c}-{r}-{si} {DUR}s linear infinite"/>')

    # ── Finish line celebration (confetti + flash) ──
    fin_x = fl_x + sq
    fin_y = mid_y
    L.append(
        f'<circle cx="{fin_x:.0f}" cy="{fin_y:.0f}" r="30" fill="#ff0000" '
        f'filter="url(#gl)" '
        f'style="animation:finish-flash {DUR}s linear infinite"/>')
    confetti_colors = ["#ff0000", "#cc0000", "#ff3333", "#ff0066", "#ff6666", "#ff0000"]
    for i in range(12):
        cc = confetti_colors[i % len(confetti_colors)]
        L.append(
            f'<rect x="{fin_x:.0f}" y="{fin_y:.0f}" width="4" height="4" rx="1" '
            f'fill="{cc}" '
            f'style="animation:confetti-{i} {DUR}s linear infinite;'
            f'transform-origin:{fin_x:.0f}px {fin_y:.0f}px"/>')

    # ── Top-down drift car ──
    L.append(f'<g filter="url(#gl)">')
    L.append(f'  <animateMotion dur="{DUR}s" calcMode="paced" '
             f'repeatCount="indefinite" rotate="auto">')
    L.append(f'    <mpath href="#carpath"/>')
    L.append(f'  </animateMotion>')
    L.append("""  <ellipse cx="0" cy="1" rx="14" ry="7" fill="#000" opacity="0.3"/>
  <path d="M 15,0 Q 14,-3.5 11,-4.5 L 7,-5.5 L 2,-6 L -4,-6 L -9,-5.5 L -12,-5
    Q -15,-4 -15,-1 L -15,1 Q -15,4 -12,5
    L -9,5.5 L -4,6 L 2,6 L 7,5.5 L 11,4.5 Q 14,3.5 15,0 Z
  " fill="#12161f" stroke="#ff0000" stroke-width="0.8"/>
  <line x1="9" y1="-3.5" x2="14" y2="0" stroke="#ff0000" stroke-width="0.4" opacity="0.5"/>
  <line x1="9" y1="3.5" x2="14" y2="0" stroke="#ff0000" stroke-width="0.4" opacity="0.5"/>
  <path d="M 8,-2 Q 10,0 8,2" fill="none" stroke="#ff0000" stroke-width="0.3" opacity="0.3"/>
  <rect x="7" y="-1.5" width="4" height="3" rx="1" fill="#0d1117" stroke="#ff0000" stroke-width="0.3" opacity="0.5"/>
  <path d="M 4,-5 L 7,-4.5 L 7,4.5 L 4,5 Z" fill="#2a0a0a" stroke="#ff0000" stroke-width="0.5" opacity="0.7"/>
  <rect x="-5" y="-4.5" width="9" height="9" rx="2" fill="#0d1520" stroke="#ff0000" stroke-width="0.4" opacity="0.6"/>
  <path d="M -7,-4.5 L -5,-5 L -5,5 L -7,4.5 Z" fill="#2a0a0a" stroke="#ff0000" stroke-width="0.3" opacity="0.5"/>
  <line x1="-14" y1="-7" x2="-14" y2="7" stroke="#ff0000" stroke-width="1.5" opacity="0.8"/>
  <line x1="-14" y1="-6.5" x2="-12" y2="-5" stroke="#ff0000" stroke-width="0.6" opacity="0.5"/>
  <line x1="-14" y1="6.5" x2="-12" y2="5" stroke="#ff0000" stroke-width="0.6" opacity="0.5"/>
  <rect x="8" y="-7.5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#ff0000" stroke-width="0.4" opacity="0.8"/>
  <rect x="8" y="5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#ff0000" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="-7.5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#ff0000" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#ff0000" stroke-width="0.4" opacity="0.8"/>
  <circle cx="15" cy="-3.5" r="1.5" fill="#ff0000" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="15" cy="3.5" r="1.5" fill="#ff0000" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <rect x="-15.5" y="-4" width="2" height="2.5" rx="0.5" fill="#ffaa00" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite"/>
  </rect>
  <rect x="-15.5" y="1.5" width="2" height="2.5" rx="0.5" fill="#ffaa00" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
  </rect>
  <ellipse cx="5" cy="-7" rx="1.8" ry="1" fill="#161b22" stroke="#ff0000" stroke-width="0.3"/>
  <ellipse cx="5" cy="7" rx="1.8" ry="1" fill="#161b22" stroke="#ff0000" stroke-width="0.3"/>
  <!-- NITRO FLAMES -->
  <!-- Core flame (bright, tight) -->
  <ellipse cx="-20" cy="0" rx="6" ry="2.5" fill="#ff0000" opacity="0">
    <animate attributeName="rx" values="4;7;5;8;4" dur="0.15s" repeatCount="indefinite"/>
    <animate attributeName="ry" values="2;3;1.5;3.5;2" dur="0.15s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.6;0.9;0.5;0.8;0.6" dur="0.15s" repeatCount="indefinite"/>
  </ellipse>
  <!-- Inner flame glow -->
  <ellipse cx="-22" cy="0" rx="4" ry="1.5" fill="#ff6666" opacity="0">
    <animate attributeName="rx" values="3;5;4;6;3" dur="0.12s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.4;0.7;0.3;0.6;0.4" dur="0.12s" repeatCount="indefinite"/>
  </ellipse>
  <!-- Nitro particle stream 1 (center) -->
  <circle r="1.5" fill="#ff0000" opacity="0">
    <animate attributeName="cx" values="-18;-30;-45" dur="0.4s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="0;-0.5;-1" dur="0.4s" repeatCount="indefinite"/>
    <animate attributeName="r" values="1.5;3;5" dur="0.4s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.5;0.2;0" dur="0.4s" repeatCount="indefinite"/>
  </circle>
  <!-- Nitro particle stream 2 (upper) -->
  <circle r="1" fill="#ff0000" opacity="0">
    <animate attributeName="cx" values="-18;-28;-40" dur="0.35s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="-2;-4;-6" dur="0.35s" repeatCount="indefinite"/>
    <animate attributeName="r" values="1;2.5;4" dur="0.35s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.4;0.15;0" dur="0.35s" repeatCount="indefinite"/>
  </circle>
  <!-- Nitro particle stream 3 (lower) -->
  <circle r="1" fill="#ff0000" opacity="0">
    <animate attributeName="cx" values="-18;-28;-40" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="cy" values="2;4;6" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="r" values="1;2.5;4" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="opacity" values="0.4;0.15;0" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
  </circle>
  <!-- Nitro sparks (tiny fast particles) -->
  <circle r="0.8" fill="#ff6666" opacity="0">
    <animate attributeName="cx" values="-17;-35;-50" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="1;3;5" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="r" values="0.8;1.2;0.3" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.7;0.3;0" dur="0.25s" repeatCount="indefinite"/>
  </circle>
  <circle r="0.8" fill="#ff6666" opacity="0">
    <animate attributeName="cx" values="-17;-33;-48" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
    <animate attributeName="cy" values="-1;-3;-4" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
    <animate attributeName="r" values="0.8;1;0.2" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
    <animate attributeName="opacity" values="0.6;0.25;0" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
  </circle>
  <circle r="0.5" fill="#ff3333" opacity="0">
    <animate attributeName="cx" values="-17;-40;-55" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
    <animate attributeName="cy" values="0;-2;-3" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
    <animate attributeName="r" values="0.5;1.5;0.2" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
    <animate attributeName="opacity" values="0.5;0.15;0" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
  </circle>
  <!-- Nitro glow halo behind car -->
  <ellipse cx="-18" cy="0" rx="10" ry="8" fill="#ff0000" opacity="0">
    <animate attributeName="opacity" values="0.05;0.12;0.05;0.1;0.05" dur="0.2s" repeatCount="indefinite"/>
    <animate attributeName="rx" values="10;13;10" dur="0.3s" repeatCount="indefinite"/>
  </ellipse>""")
    L.append("</g>")

    # Footer
    L.append(
        f'<text x="{W / 2:.0f}" y="{H - 4:.0f}" text-anchor="middle" '
        f'font-family="monospace" font-size="10" fill="#ff0000" opacity="0.35">'
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
