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

    # Each cell carries data-date + data-level + an id, in any attribute order.
    # The actual count lives in a sibling <tool-tip for="id">N contributions on …</tool-tip>,
    # so we join by id to recover real counts (level alone is just a 0–4 bucket).
    td_pattern = r'<td\b([^>]*\bclass="ContributionCalendar-day"[^>]*)>'
    attr = lambda s, name: (re.search(rf'{name}="([^"]+)"', s) or [None, None])[1]
    cells = []
    for tag_attrs in re.findall(td_pattern, html):
        date = attr(tag_attrs, "data-date")
        level = attr(tag_attrs, "data-level")
        cell_id = attr(tag_attrs, "id")
        if date and level and cell_id:
            cells.append((date, level, cell_id))

    if not cells:
        raise ValueError("Could not parse contribution data from GitHub page")

    tip_pattern = r'<tool-tip[^>]*for="(contribution-day-component-[^"]+)"[^>]*>([^<]+)</tool-tip>'
    tips = dict(re.findall(tip_pattern, html))

    def real_count(cell_id, level_int):
        text = tips.get(cell_id, "")
        m = re.match(r"(\d+)\s+contribution", text)
        if m:
            return int(m.group(1))
        return level_int  # fallback if tooltip is missing

    level_colors = {
        "0": "#ebedf0",
        "1": "#9be9a8",
        "2": "#40c463",
        "3": "#30a14e",
        "4": "#216e39",
    }

    # Find the earliest date to use as grid origin (should be a Sunday)
    all_dates = [datetime.strptime(d, "%Y-%m-%d") for d, _, _ in cells]
    first_date = min(all_dates)
    # Ensure first_date is a Sunday (weekday 6 in Python)
    # GitHub weeks start on Sunday
    first_sunday = first_date - timedelta(days=(first_date.weekday() + 1) % 7)

    # Build a dict: (week_col, day_row) -> cell data
    grid = {}
    total = 0
    num_weeks = 0
    for date_str, level, cell_id in cells:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days_diff = (dt - first_sunday).days
        week_col = days_diff // 7
        day_row = days_diff % 7  # 0=Sunday, 1=Monday, ..., 6=Saturday
        level_int = int(level)
        count = real_count(cell_id, level_int)
        total += count
        grid[(week_col, day_row)] = {
            "contributionCount": count,
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


# Map GitHub colors to blue theme
COLOR_MAP = {
    "#ebedf0": "#161b22",  # no contributions (dark mode empty)
    "#9be9a8": "#002d5e",  # level 1
    "#40c463": "#004a99",  # level 2
    "#30a14e": "#006bd6",  # level 3
    "#216e39": "#0096ff",  # level 4
    # Dark mode colors
    "#161b22": "#161b22",  # no contributions
    "#0e4429": "#002d5e",  # level 1
    "#006d32": "#004a99",  # level 2
    "#26a641": "#006bd6",  # level 3
    "#39d353": "#0096ff",  # level 4
}


def map_color(github_color):
    """Map GitHub contribution color to blue theme."""
    return COLOR_MAP.get(github_color, "#161b22")




# ══════════════════════════════════════════════════════════════════════════
#  Timeline helpers
# ══════════════════════════════════════════════════════════════════════════

def mono(pcts, gap=0.05):
    """Return keyframe percentages guaranteed to be strictly increasing.

    Duplicated @keyframes offsets are silently destructive in CSS: the later
    declaration wins, so `0%,99% {opacity:0} 99% {opacity:1}` collapses into a
    99%-long fade instead of a flash. Every percentage sequence goes through
    here so that class of bug cannot come back.
    """
    out = []
    for p in pcts:
        p = max(0.0, min(100.0, float(p)))
        if out and p <= out[-1]:
            p = out[-1] + gap
        out.append(min(p, 100.0))
    for i in range(len(out) - 1, 0, -1):
        if out[i] <= out[i - 1]:
            out[i - 1] = out[i] - gap
    return out


def generate_svg(calendar, username):
    """Car drives L->R collecting contributions while the floor falls behind it.
    The moment it crosses the finish line the whole scene detonates, then the
    grid rebuilds and the loop starts over.
    """
    import bisect
    import math
    import random

    rnd = random.Random(7)

    # Debris decelerates like real ejecta instead of drifting linearly.
    EASE = "animation-timing-function:cubic-bezier(.08,.82,.28,1);"

    weeks = calendar["weeks"]
    total = calendar["totalContributions"]

    CELL = 14
    GAP = 3
    STRIDE = CELL + GAP
    ROWS = 7
    COLS = len(weeks)
    GRID_W = COLS * STRIDE - GAP
    GRID_H = ROWS * STRIDE - GAP

    MARGIN = 50
    W = GRID_W + MARGIN * 2
    H = GRID_H + 90
    GX = MARGIN
    GY = 40
    mid_y = GY + GRID_H / 2

    # ── Loop timeline (percent of one cycle) ──────────────────────────────
    DUR = 12          # seconds per loop
    BOOM = 82.0       # car reaches the finish line -> detonation
    BLAST_MAX = 97.0  # everything is gone by here; the tail is the reset beat

    # ── Finish line geometry ──────────────────────────────────────────────
    sq = 6
    fl_x = GX + GRID_W + 8
    fl_y = GY - 5
    fl_h = GRID_H + 10
    fin_x = float(fl_x + sq)
    fin_y = float(mid_y)

    # ── Contribution cells, L->R then top->bottom ─────────────────────────
    contrib_set = set()
    contrib_cells = []
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            if day["contributionCount"] > 0:
                cx = GX + c * STRIDE + CELL / 2
                cy = GY + r * STRIDE + CELL / 2
                contrib_cells.append((c, r, cx, cy))
                contrib_set.add((c, r))

    # ── Car path: enter left -> every contribution -> finish line ─────────
    wp = [(-30.0, float(mid_y))]
    for _, _, cx, cy in contrib_cells:
        wp.append((float(cx), float(cy)))
    wp.append((fin_x, fin_y))

    seg = [math.hypot(wp[i][0] - wp[i - 1][0], wp[i][1] - wp[i - 1][1])
           for i in range(1, len(wp))]
    total_len = sum(seg) or 1.0
    cum = [0.0]
    for s in seg:
        cum.append(cum[-1] + s)

    path_d = "M %.1f,%.1f" % wp[0] + "".join(" L %.1f,%.1f" % p for p in wp[1:])

    def x_at(frac):
        """X coordinate at `frac` of the path arc length (0..1)."""
        target = frac * total_len
        i = min(max(bisect.bisect_left(cum, target), 1), len(cum) - 1)
        span = seg[i - 1] or 1.0
        t = (target - cum[i - 1]) / span
        return wp[i - 1][0] + (wp[i][0] - wp[i - 1][0]) * t

    def pass_pct(col_x):
        """Loop percentage at which the car clears a column.

        X along the path is non-decreasing (contributions are visited in column
        order), so a binary search finds the crossing exactly.
        """
        lo, hi = 0.0, 1.0
        for _ in range(34):
            m = (lo + hi) / 2
            if x_at(m) < col_x:
                lo = m
            else:
                hi = m
        return hi * BOOM

    # Floor drops a beat after the car has cleared the column.
    col_fall = {}
    for c in range(COLS):
        t = pass_pct(GX + c * STRIDE + CELL / 2)
        fs = min(t + 1.2, BOOM - 3.4)
        fe = min(fs + 3.5, BOOM - 0.9)
        col_fall[c] = (fs, fe)

    # Contribution collect times = exact waypoint arrival times.
    contrib_time = {}
    for j, (c, r, _, _) in enumerate(contrib_cells):
        contrib_time[(c, r)] = cum[j + 1] / total_len * BOOM

    def spawn_pct(c):
        """Grid rebuilds left-to-right right after the loop restarts."""
        return 0.6 + (c / max(COLS - 1, 1)) * 2.2

    def blast(ox, oy):
        """Outward vector from the detonation point, with a bit of lift."""
        vx, vy = ox - fin_x, oy - fin_y
        d = math.hypot(vx, vy) or 1.0
        near = 1.0 - min(d / (W * 0.85), 1.0)
        power = (250.0 + 430.0 * near) * rnd.uniform(0.75, 1.35)
        return (vx / d * power,
                vy / d * power - rnd.uniform(25, 95),
                rnd.uniform(-540, 540))

    # ══════════════════ BUILD SVG ══════════════════
    L = []
    L.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">')

    L.append("<style>")
    L.append("  * { will-change: transform, opacity; }")

    # ── Per-cell life cycle: spawn -> (collect | fall) -> detonate ────────
    cell_anim = {}
    for c, week in enumerate(weeks):
        for r, _day in enumerate(week["contributionDays"]):
            ox = GX + c * STRIDE + CELL / 2
            oy = GY + r * STRIDE + CELL / 2
            dx, dy, rot = blast(ox, oy)
            be = min(BOOM + rnd.uniform(6.0, 11.0), BLAST_MAX)
            sp = spawn_pct(c)
            name = f"k{c}-{r}"
            cell_anim[(c, r)] = name
            out = (f"translate({dx:.0f}px,{dy:.0f}px) "
                   f"rotate({rot:.0f}deg) scale(.12)")

            if (c, r) in contrib_set:
                hp = contrib_time[(c, r)]
                p = mono([0, sp, hp - 0.5, hp, min(hp + 2.2, BOOM - 1.4),
                          BOOM - 0.45, BOOM, be, 100])
                L.append(
                    f"  @keyframes {name} {{"
                    f" 0% {{ transform:translate(0,0) rotate(0deg) scale(.2); opacity:0; }}"
                    f" {p[1]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1); opacity:1; }}"
                    f" {p[2]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1); opacity:1; filter:brightness(1); }}"
                    f" {p[3]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1.7); opacity:1; filter:brightness(3.5); }}"
                    f" {p[4]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(0); opacity:0; filter:brightness(4); }}"
                    f" {p[5]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(0); opacity:0; }}"
                    f" {p[6]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1.15); opacity:1; {EASE} }}"
                    f" {p[7]:.2f}% {{ transform:{out}; opacity:0; }}"
                    f" 100% {{ transform:{out}; opacity:0; }}"
                    f" }}")
            else:
                fs, fe = col_fall[c]
                p = mono([0, sp, fs, fe, BOOM - 0.45, BOOM, be, 100])
                tilt = f"rotate({rot * 0.12:.0f}deg)"
                L.append(
                    f"  @keyframes {name} {{"
                    f" 0% {{ transform:translate(0,0) rotate(0deg) scale(.2); opacity:0; }}"
                    f" {p[1]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1); opacity:1; }}"
                    f" {p[2]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1); opacity:1; }}"
                    f" {p[3]:.2f}% {{ transform:translate(0,86px) {tilt} scale(1); opacity:0; }}"
                    f" {p[4]:.2f}% {{ transform:translate(0,86px) {tilt} scale(1); opacity:0; }}"
                    f" {p[5]:.2f}% {{ transform:translate(0,0) rotate(0deg) scale(1.15); opacity:1; {EASE} }}"
                    f" {p[6]:.2f}% {{ transform:{out}; opacity:0; }}"
                    f" 100% {{ transform:{out}; opacity:0; }}"
                    f" }}")

    # ── Tire trail: drawn while driving, wiped by the blast ───────────────
    tp = mono([0, BOOM, BOOM + 2.5, 100])
    L.append(
        f"  @keyframes trail-draw {{"
        f" 0% {{ stroke-dashoffset:1; opacity:1; }}"
        f" {tp[1]:.2f}% {{ stroke-dashoffset:0; opacity:1; }}"
        f" {tp[2]:.2f}% {{ stroke-dashoffset:0; opacity:0; }}"
        f" 100% {{ stroke-dashoffset:0; opacity:0; }}"
        f" }}")

    # ── Sparkles when a contribution is collected ────────────────────────
    for (c, r), hp in contrib_time.items():
        for si in range(3):
            angle = si * 120
            sdx = math.cos(math.radians(angle)) * 20
            sdy = math.sin(math.radians(angle)) * 20
            p = mono([0, hp - 0.2, hp, min(hp + 2, BOOM - 0.5), 100])
            L.append(
                f"  @keyframes spark-{c}-{r}-{si} {{"
                f" 0%,{p[1]:.2f}% {{ opacity:0; transform:translate(0,0) scale(1); }}"
                f" {p[2]:.2f}% {{ opacity:1; transform:translate(0,0) scale(1); }}"
                f" {p[3]:.2f}% {{ opacity:0; transform:translate({sdx:.0f}px,{sdy:.0f}px) scale(0); }}"
                f" 100% {{ opacity:0; }}"
                f" }}")

    # ── Finish flag: waves, then gets blown off its pole ─────────────────
    L.append(
        "  @keyframes flag-wave {"
        " 0%,100% { transform:skewX(0deg); }"
        " 25% { transform:skewX(3deg); }"
        " 75% { transform:skewX(-3deg); }"
        " }")
    fp = mono([0, 1.2, BOOM - 0.2, BOOM + 0.2,
               min(BOOM + 9, BLAST_MAX), 100])
    L.append(
        f"  @keyframes flag-boom {{"
        f" 0% {{ opacity:0; transform:translate(0,0) rotate(0deg) scale(.4); }}"
        f" {fp[1]:.2f}% {{ opacity:1; transform:translate(0,0) rotate(0deg) scale(1); }}"
        f" {fp[2]:.2f}% {{ opacity:1; transform:translate(0,0) rotate(0deg) scale(1); }}"
        f" {fp[3]:.2f}% {{ opacity:1; transform:translate(10px,-4px) rotate(-6deg) scale(1.1); }}"
        f" {fp[4]:.2f}% {{ opacity:0; transform:translate(150px,-70px) rotate(120deg) scale(.3); }}"
        f" 100% {{ opacity:0; transform:translate(150px,-70px) rotate(120deg) scale(.3); }}"
        f" }}")

    # ── Detonation: white-out flash, shockwaves, core burst, debris ──────
    xp = mono([0, BOOM - 0.35, BOOM + 0.15, BOOM + 0.9, BOOM + 3.0, 100])
    L.append(
        f"  @keyframes boom-flash {{"
        f" 0%,{xp[1]:.2f}% {{ opacity:0; }}"
        f" {xp[2]:.2f}% {{ opacity:.82; }}"
        f" {xp[3]:.2f}% {{ opacity:.24; }}"
        f" {xp[4]:.2f}% {{ opacity:0; }}"
        f" 100% {{ opacity:0; }}"
        f" }}")

    for i in range(3):
        rp = mono([0, BOOM - 0.3 + i * 0.9, BOOM + 0.2 + i * 0.9,
                   min(BOOM + 7.5 + i * 1.4, BLAST_MAX), 100])
        L.append(
            f"  @keyframes ring-{i} {{"
            f" 0%,{rp[1]:.2f}% {{ opacity:0; transform:scale(.04); }}"
            f" {rp[2]:.2f}% {{ opacity:{0.9 - i * 0.2:.2f}; transform:scale(.12); }}"
            f" {rp[3]:.2f}% {{ opacity:0; transform:scale({9 + i * 3}); }}"
            f" 100% {{ opacity:0; transform:scale({9 + i * 3}); }}"
            f" }}")

    cp = mono([0, BOOM - 0.3, BOOM + 0.12, BOOM + 3.5, 100])
    L.append(
        f"  @keyframes core-burst {{"
        f" 0%,{cp[1]:.2f}% {{ opacity:0; transform:scale(.1); }}"
        f" {cp[2]:.2f}% {{ opacity:1; transform:scale(2.8); }}"
        f" {cp[3]:.2f}% {{ opacity:0; transform:scale(6); }}"
        f" 100% {{ opacity:0; transform:scale(6); }}"
        f" }}")

    debris = []
    for i in range(34):
        ang = math.radians(rnd.uniform(0, 360))
        power = rnd.uniform(90, 430)
        ddx = math.cos(ang) * power
        ddy = math.sin(ang) * power * 0.7 - rnd.uniform(10, 70)
        size = rnd.choice([1.2, 1.8, 2.4, 3.0])
        col = rnd.choice(["#0096ff", "#66c2ff", "#cfefff", "#33adff", "#ffaa00"])
        end = min(BOOM + rnd.uniform(4.5, 9.5), BLAST_MAX)
        debris.append((size, col))
        dp = mono([0, BOOM - 0.25, BOOM + 0.1, end, 100])
        L.append(
            f"  @keyframes deb-{i} {{"
            f" 0%,{dp[1]:.2f}% {{ opacity:0; transform:translate(0,0) scale(.3); }}"
            f" {dp[2]:.2f}% {{ opacity:1; transform:translate(0,0) scale(1); {EASE} }}"
            f" {dp[3]:.2f}% {{ opacity:0; transform:translate({ddx:.0f}px,{ddy:.0f}px) scale(.15); }}"
            f" 100% {{ opacity:0; }}"
            f" }}")

    # ── Camera shake on impact ───────────────────────────────────────────
    sk = mono([0, BOOM - 0.1, BOOM + 0.18, BOOM + 0.5, BOOM + 0.9,
               BOOM + 1.4, BOOM + 2.0, 100])
    L.append(
        f"  @keyframes shake {{"
        f" 0%,{sk[1]:.2f}% {{ transform:translate(0,0); }}"
        f" {sk[2]:.2f}% {{ transform:translate(-5px,2px); }}"
        f" {sk[3]:.2f}% {{ transform:translate(5px,-3px); }}"
        f" {sk[4]:.2f}% {{ transform:translate(-3px,-1px); }}"
        f" {sk[5]:.2f}% {{ transform:translate(3px,2px); }}"
        f" {sk[6]:.2f}% {{ transform:translate(0,0); }}"
        f" 100% {{ transform:translate(0,0); }}"
        f" }}")

    # ── Car: drives the path, disintegrates at the finish line ───────────
    mp = mono([0, BOOM, BOOM + 0.18, 100])
    L.append(
        f"  @keyframes car-move {{"
        f" 0% {{ offset-distance:0%; opacity:1; }}"
        f" {mp[1]:.2f}% {{ offset-distance:100%; opacity:1; }}"
        f" {mp[2]:.2f}% {{ offset-distance:100%; opacity:0; }}"
        f" 100% {{ offset-distance:100%; opacity:0; }}"
        f" }}")
    L.append(
        f"  .drift-car {{"
        f" offset-path:path('{path_d}');"
        f" offset-rotate:auto;"
        f" animation:car-move {DUR}s linear infinite;"
        f" }}")

    L.append("</style>")

    # ── Defs ──
    L.append('<defs>')
    L.append('  <filter id="gl"><feGaussianBlur stdDeviation="1.5" result="b"/>')
    L.append('    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    L.append('  <radialGradient id="core">')
    L.append('    <stop offset="0%" stop-color="#ffffff"/>')
    L.append('    <stop offset="45%" stop-color="#8fd4ff"/>')
    L.append('    <stop offset="100%" stop-color="#0096ff" stop-opacity="0"/>')
    L.append('  </radialGradient>')
    L.append('</defs>')

    # ── Background ──
    L.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#0d1117"/>')

    # ── Stage: everything that shakes on impact ──
    L.append(f'<g style="animation:shake {DUR}s linear infinite">')

    # Contribution grid
    L.append("<g>")
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            x = GX + c * STRIDE
            y = GY + r * STRIDE
            color = map_color(day["color"])
            ox = x + CELL / 2
            oy = y + CELL / 2
            L.append(
                f'  <rect x="{x:.0f}" y="{y:.0f}" width="{CELL}" height="{CELL}" '
                f'rx="2" fill="{color}" '
                f'style="animation:{cell_anim[(c, r)]} {DUR}s linear infinite;'
                f'transform-origin:{ox:.0f}px {oy:.0f}px"/>')
    L.append("</g>")

    # Finish line: outer group detonates, inner group waves
    L.append(f'<g style="animation:flag-boom {DUR}s linear infinite;'
             f'transform-origin:{fin_x:.0f}px {fin_y:.0f}px">')
    L.append(f'<g style="animation:flag-wave 1.5s ease-in-out infinite;'
             f'transform-origin:{fl_x + sq}px {fl_y + fl_h / 2:.0f}px">')
    for row in range(int(fl_h / sq) + 1):
        for col in range(2):
            fx = fl_x + col * sq
            fy = fl_y + row * sq
            if fy + sq > fl_y + fl_h:
                continue
            is_dark = (row + col) % 2 == 0
            fill = "#0096ff" if is_dark else "#0d1117"
            opacity = "0.6" if is_dark else "0.3"
            L.append(
                f'  <rect x="{fx}" y="{fy}" width="{sq}" height="{sq}" '
                f'fill="{fill}" opacity="{opacity}" stroke="#0096ff" stroke-width="0.3"/>')
    L.append('</g></g>')

    # Tire marks
    for stroke_w, op in ((1, 0.15), (3, 0.05)):
        L.append(
            f'<g opacity="{op}"><path d="{path_d}" fill="none" stroke="#0096ff" '
            f'stroke-width="{stroke_w}" pathLength="1" stroke-dasharray="1" '
            f'stroke-dashoffset="1" '
            f'style="animation:trail-draw {DUR}s linear infinite"/></g>')

    # Collect sparkles
    for (c, r), _hp in contrib_time.items():
        sx = GX + c * STRIDE + CELL / 2
        sy = GY + r * STRIDE + CELL / 2
        for si in range(3):
            L.append(
                f'  <circle cx="{sx:.0f}" cy="{sy:.0f}" r="1.5" fill="#0096ff" '
                f'filter="url(#gl)" '
                f'style="animation:spark-{c}-{r}-{si} {DUR}s linear infinite"/>')

    # ── Top-down drift car (CSS offset-path, same clock as the grid) ──
    L.append('<g filter="url(#gl)" class="drift-car">')
    L.append("""  <ellipse cx="0" cy="1" rx="14" ry="7" fill="#000" opacity="0.3"/>
  <path d="M 15,0 Q 14,-3.5 11,-4.5 L 7,-5.5 L 2,-6 L -4,-6 L -9,-5.5 L -12,-5
    Q -15,-4 -15,-1 L -15,1 Q -15,4 -12,5
    L -9,5.5 L -4,6 L 2,6 L 7,5.5 L 11,4.5 Q 14,3.5 15,0 Z
  " fill="#12161f" stroke="#0096ff" stroke-width="0.8"/>
  <line x1="9" y1="-3.5" x2="14" y2="0" stroke="#0096ff" stroke-width="0.4" opacity="0.5"/>
  <line x1="9" y1="3.5" x2="14" y2="0" stroke="#0096ff" stroke-width="0.4" opacity="0.5"/>
  <path d="M 8,-2 Q 10,0 8,2" fill="none" stroke="#0096ff" stroke-width="0.3" opacity="0.3"/>
  <rect x="7" y="-1.5" width="4" height="3" rx="1" fill="#0d1117" stroke="#0096ff" stroke-width="0.3" opacity="0.5"/>
  <path d="M 4,-5 L 7,-4.5 L 7,4.5 L 4,5 Z" fill="#0a1a2a" stroke="#0096ff" stroke-width="0.5" opacity="0.7"/>
  <rect x="-5" y="-4.5" width="9" height="9" rx="2" fill="#0d1520" stroke="#0096ff" stroke-width="0.4" opacity="0.6"/>
  <path d="M -7,-4.5 L -5,-5 L -5,5 L -7,4.5 Z" fill="#0a1a2a" stroke="#0096ff" stroke-width="0.3" opacity="0.5"/>
  <line x1="-14" y1="-7" x2="-14" y2="7" stroke="#0096ff" stroke-width="1.5" opacity="0.8"/>
  <line x1="-14" y1="-6.5" x2="-12" y2="-5" stroke="#0096ff" stroke-width="0.6" opacity="0.5"/>
  <line x1="-14" y1="6.5" x2="-12" y2="5" stroke="#0096ff" stroke-width="0.6" opacity="0.5"/>
  <rect x="8" y="-7.5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#0096ff" stroke-width="0.4" opacity="0.8"/>
  <rect x="8" y="5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#0096ff" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="-7.5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#0096ff" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#0096ff" stroke-width="0.4" opacity="0.8"/>
  <circle cx="15" cy="-3.5" r="1.5" fill="#0096ff" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="15" cy="3.5" r="1.5" fill="#0096ff" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <rect x="-15.5" y="-4" width="2" height="2.5" rx="0.5" fill="#ffaa00" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite"/>
  </rect>
  <rect x="-15.5" y="1.5" width="2" height="2.5" rx="0.5" fill="#ffaa00" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
  </rect>
  <ellipse cx="5" cy="-7" rx="1.8" ry="1" fill="#161b22" stroke="#0096ff" stroke-width="0.3"/>
  <ellipse cx="5" cy="7" rx="1.8" ry="1" fill="#161b22" stroke="#0096ff" stroke-width="0.3"/>
  <!-- NITRO FLAMES -->
  <ellipse cx="-20" cy="0" rx="6" ry="2.5" fill="#0096ff" opacity="0">
    <animate attributeName="rx" values="4;7;5;8;4" dur="0.15s" repeatCount="indefinite"/>
    <animate attributeName="ry" values="2;3;1.5;3.5;2" dur="0.15s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.6;0.9;0.5;0.8;0.6" dur="0.15s" repeatCount="indefinite"/>
  </ellipse>
  <ellipse cx="-22" cy="0" rx="4" ry="1.5" fill="#66c2ff" opacity="0">
    <animate attributeName="rx" values="3;5;4;6;3" dur="0.12s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.4;0.7;0.3;0.6;0.4" dur="0.12s" repeatCount="indefinite"/>
  </ellipse>
  <circle r="1.5" fill="#0096ff" opacity="0">
    <animate attributeName="cx" values="-18;-30;-45" dur="0.4s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="0;-0.5;-1" dur="0.4s" repeatCount="indefinite"/>
    <animate attributeName="r" values="1.5;3;5" dur="0.4s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.5;0.2;0" dur="0.4s" repeatCount="indefinite"/>
  </circle>
  <circle r="1" fill="#0096ff" opacity="0">
    <animate attributeName="cx" values="-18;-28;-40" dur="0.35s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="-2;-4;-6" dur="0.35s" repeatCount="indefinite"/>
    <animate attributeName="r" values="1;2.5;4" dur="0.35s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.4;0.15;0" dur="0.35s" repeatCount="indefinite"/>
  </circle>
  <circle r="1" fill="#0096ff" opacity="0">
    <animate attributeName="cx" values="-18;-28;-40" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="cy" values="2;4;6" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="r" values="1;2.5;4" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
    <animate attributeName="opacity" values="0.4;0.15;0" dur="0.35s" repeatCount="indefinite" begin="0.1s"/>
  </circle>
  <circle r="0.8" fill="#66c2ff" opacity="0">
    <animate attributeName="cx" values="-17;-35;-50" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="1;3;5" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="r" values="0.8;1.2;0.3" dur="0.25s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.7;0.3;0" dur="0.25s" repeatCount="indefinite"/>
  </circle>
  <circle r="0.8" fill="#66c2ff" opacity="0">
    <animate attributeName="cx" values="-17;-33;-48" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
    <animate attributeName="cy" values="-1;-3;-4" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
    <animate attributeName="r" values="0.8;1;0.2" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
    <animate attributeName="opacity" values="0.6;0.25;0" dur="0.25s" repeatCount="indefinite" begin="0.08s"/>
  </circle>
  <circle r="0.5" fill="#33adff" opacity="0">
    <animate attributeName="cx" values="-17;-40;-55" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
    <animate attributeName="cy" values="0;-2;-3" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
    <animate attributeName="r" values="0.5;1.5;0.2" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
    <animate attributeName="opacity" values="0.5;0.15;0" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
  </circle>
  <ellipse cx="-18" cy="0" rx="10" ry="8" fill="#0096ff" opacity="0">
    <animate attributeName="opacity" values="0.05;0.12;0.05;0.1;0.05" dur="0.2s" repeatCount="indefinite"/>
    <animate attributeName="rx" values="10;13;10" dur="0.3s" repeatCount="indefinite"/>
  </ellipse>""")
    L.append("</g>")

    L.append("</g>")  # /stage

    # ── White-out flash (masks the grid snapping back for the blast) ──
    L.append(
        f'<rect width="{W:.0f}" height="{H:.0f}" fill="#d6efff" opacity="0" '
        f'style="animation:boom-flash {DUR}s linear infinite"/>')

    # ── Shockwaves, core burst and debris ──
    for i in range(3):
        L.append(
            f'<circle cx="{fin_x:.0f}" cy="{fin_y:.0f}" r="60" fill="none" '
            f'stroke="#0096ff" stroke-width="{3 - i * 0.7:.1f}" '
            f'vector-effect="non-scaling-stroke" opacity="0" '
            f'style="animation:ring-{i} {DUR}s linear infinite;'
            f'transform-origin:{fin_x:.0f}px {fin_y:.0f}px"/>')
    L.append(
        f'<circle cx="{fin_x:.0f}" cy="{fin_y:.0f}" r="16" fill="url(#core)" '
        f'opacity="0" style="animation:core-burst {DUR}s linear infinite;'
        f'transform-origin:{fin_x:.0f}px {fin_y:.0f}px"/>')
    for i, (size, col) in enumerate(debris):
        L.append(
            f'<circle cx="{fin_x:.0f}" cy="{fin_y:.0f}" r="{size}" fill="{col}" '
            f'filter="url(#gl)" opacity="0" '
            f'style="animation:deb-{i} {DUR}s linear infinite;'
            f'transform-origin:{fin_x:.0f}px {fin_y:.0f}px"/>')

    # Footer
    L.append(
        f'<text x="{W / 2:.0f}" y="{H - 4:.0f}" text-anchor="middle" '
        f'font-family="monospace" font-size="10" fill="#0096ff" opacity="0.35">'
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
