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
    url = f"https://github.com/users/{username}/contributions"
    req = urllib.request.Request(url, headers={"User-Agent": "drift-car-generator"})

    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")

    # Parse the contribution cells from HTML
    # Each cell looks like: <td ... data-date="2024-01-01" data-level="2" ...>
    weeks = []
    current_week = []

    # Find all contribution day cells
    pattern = r'data-date="([^"]+)"[^>]*data-level="(\d)"'
    matches = re.findall(pattern, html)

    if not matches:
        raise ValueError("Could not parse contribution data from GitHub page")

    # GitHub contribution grid: 7 rows (days) x N columns (weeks)
    # The HTML is organized by columns (weeks), each with up to 7 days
    level_colors = {
        "0": "#ebedf0",
        "1": "#9be9a8",
        "2": "#40c463",
        "3": "#30a14e",
        "4": "#216e39",
    }

    total = 0
    for date, level in matches:
        level_int = int(level)
        if level_int > 0:
            total += level_int

        current_week.append({
            "contributionCount": level_int,
            "date": date,
            "color": level_colors.get(level, "#ebedf0"),
        })

        if len(current_week) == 7:
            weeks.append({"contributionDays": current_week})
            current_week = []

    if current_week:
        weeks.append({"contributionDays": current_week})

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
    """Generate drift car SVG - zigzags through grid with drift curves + explosion."""
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

    W = GRID_W + 60
    H = GRID_H + 60

    GX = (W - GRID_W) / 2
    GY = 25

    # Build zigzag path with DRIFT CURVES at turns
    cell_hit_time = {}
    total_cells = COLS * ROWS
    cell_index = 0

    # Calculate cell centers and hit times
    for r in range(ROWS):
        cols_range = range(COLS) if r % 2 == 0 else range(COLS - 1, -1, -1)
        for c in cols_range:
            cell_hit_time[(c, r)] = cell_index / total_cells
            cell_index += 1

    # Build SVG path with curves at row transitions
    DRIFT_OVERSHOOT = 20  # how far the car overshoots before drifting back
    path_parts = []

    for r in range(ROWS):
        left_x = GX + CELL / 2
        right_x = GX + (COLS - 1) * STRIDE + CELL / 2
        cy = GY + r * STRIDE + CELL / 2

        if r == 0:
            # Start
            path_parts.append(f"M {left_x:.1f},{cy:.1f}")
            path_parts.append(f"L {right_x:.1f},{cy:.1f}")
        else:
            prev_cy = GY + (r - 1) * STRIDE + CELL / 2
            mid_cy = (prev_cy + cy) / 2

            if r % 2 == 0:
                # Coming from right, drift curve to left side, then go right
                # Overshoot left before curving down and going right
                path_parts.append(
                    f"Q {left_x - DRIFT_OVERSHOOT:.1f},{prev_cy:.1f} "
                    f"{left_x - DRIFT_OVERSHOOT:.1f},{mid_cy:.1f}"
                )
                path_parts.append(
                    f"Q {left_x - DRIFT_OVERSHOOT:.1f},{cy:.1f} "
                    f"{left_x:.1f},{cy:.1f}"
                )
                path_parts.append(f"L {right_x:.1f},{cy:.1f}")
            else:
                # Coming from left, drift curve to right side, then go left
                path_parts.append(
                    f"Q {right_x + DRIFT_OVERSHOOT:.1f},{prev_cy:.1f} "
                    f"{right_x + DRIFT_OVERSHOOT:.1f},{mid_cy:.1f}"
                )
                path_parts.append(
                    f"Q {right_x + DRIFT_OVERSHOOT:.1f},{cy:.1f} "
                    f"{right_x:.1f},{cy:.1f}"
                )
                path_parts.append(f"L {left_x:.1f},{cy:.1f}")

    path_d = " ".join(path_parts)

    # 85% driving, 15% explosion pause
    CAR_DUR = 18

    # Last cell position (for explosion origin)
    last_r = ROWS - 1
    if last_r % 2 == 0:
        last_cx = GX + (COLS - 1) * STRIDE + CELL / 2
    else:
        last_cx = GX + CELL / 2
    last_cy = GY + last_r * STRIDE + CELL / 2

    lines = []
    lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">'
    )

    # === STYLES ===
    lines.append("<style>")

    # Square eat animations (85% of total time for driving)
    drive_pct = 85
    for c in range(COLS):
        for r in range(ROWS):
            key = (c, r)
            if key in cell_hit_time:
                t = cell_hit_time[key]
                pct_before = max(0, t * drive_pct - 0.4)
                pct_hit = t * drive_pct
                pct_gone = min(t * drive_pct + 1.5, drive_pct)
                lines.append(
                    f"  @keyframes e-{c}-{r} {{"
                    f" 0%,{pct_before:.1f}% {{ opacity:1; transform:scale(1); }}"
                    f" {pct_hit:.1f}% {{ opacity:0.7; transform:scale(1.4); }}"
                    f" {pct_gone:.1f}%,100% {{ opacity:0; transform:scale(0); }}"
                    f" }}"
                )

    # Explosion particle keyframes
    NUM_PARTICLES = 24
    for i in range(NUM_PARTICLES):
        angle = (i / NUM_PARTICLES) * 2 * math.pi
        dist = 80 + (i % 3) * 40
        dx = math.cos(angle) * dist
        dy = math.sin(angle) * dist
        lines.append(
            f"  @keyframes boom-{i} {{"
            f" 0%,{drive_pct}% {{ transform:translate(0,0); opacity:0; }}"
            f" {drive_pct + 1}% {{ transform:translate(0,0); opacity:1; }}"
            f" {drive_pct + 10}% {{ transform:translate({dx:.0f}px,{dy:.0f}px); opacity:0.8; }}"
            f" 100% {{ transform:translate({dx*1.2:.0f}px,{dy*1.2:.0f}px); opacity:0; }}"
            f" }}"
        )

    # Explosion flash
    lines.append(
        f"  @keyframes flash {{"
        f" 0%,{drive_pct}% {{ opacity:0; }}"
        f" {drive_pct + 1}% {{ opacity:0.6; }}"
        f" {drive_pct + 5}% {{ opacity:0.2; }}"
        f" {drive_pct + 12}%,100% {{ opacity:0; }}"
        f" }}"
    )

    # Explosion ring
    lines.append(
        f"  @keyframes ring {{"
        f" 0%,{drive_pct}% {{ r:0; opacity:0; stroke-width:4; }}"
        f" {drive_pct + 1}% {{ r:5; opacity:0.8; stroke-width:3; }}"
        f" {drive_pct + 10}% {{ r:80; opacity:0.3; stroke-width:1; }}"
        f" {drive_pct + 15}%,100% {{ r:120; opacity:0; stroke-width:0.5; }}"
        f" }}"
    )

    # DRIFT text flash
    lines.append(
        f"  @keyframes drift-text {{"
        f" 0%,{drive_pct}% {{ opacity:0; }}"
        f" {drive_pct + 2}% {{ opacity:0.9; }}"
        f" {drive_pct + 8}% {{ opacity:0.7; }}"
        f" {drive_pct + 14}%,100% {{ opacity:0; }}"
        f" }}"
    )

    # Car hide after drive
    lines.append(
        f"  @keyframes car-vis {{"
        f" 0%,{drive_pct - 1}% {{ opacity:1; }}"
        f" {drive_pct}%,100% {{ opacity:0; }}"
        f" }}"
    )

    lines.append("</style>")

    # === DEFS ===
    lines.append(f"""<defs>
  <filter id="gl">
    <feGaussianBlur stdDeviation="1.5" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="gl2">
    <feGaussianBlur stdDeviation="3" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <path id="carpath" d="{path_d}" fill="none"/>
</defs>""")

    # === BACKGROUND ===
    lines.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#0d1117"/>')

    # === CONTRIBUTION GRID ===
    lines.append("<g>")
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            x = GX + c * STRIDE
            y = GY + r * STRIDE
            color = map_color(day["color"])
            ox = x + CELL / 2
            oy = y + CELL / 2
            anim = (
                f' style="animation:e-{c}-{r} {CAR_DUR}s linear infinite;'
                f'transform-origin:{ox:.0f}px {oy:.0f}px"'
            )
            lines.append(
                f'  <rect x="{x:.0f}" y="{y:.0f}" width="{CELL}" height="{CELL}" '
                f'rx="2" fill="{color}"{anim}/>'
            )
    lines.append("</g>")

    # === TIRE MARKS along the drift curves ===
    lines.append("<!-- Drift tire marks at turns -->")
    for r in range(1, ROWS):
        prev_cy = GY + (r - 1) * STRIDE + CELL / 2
        cy = GY + r * STRIDE + CELL / 2

        if r % 2 == 0:
            tx = GX + CELL / 2 - DRIFT_OVERSHOOT + 5
        else:
            tx = GX + (COLS - 1) * STRIDE + CELL / 2 + DRIFT_OVERSHOOT - 5

        # Tire mark arc at each turn
        t_ratio = cell_hit_time.get(
            (0 if r % 2 == 0 else COLS - 1, r), r / ROWS
        )
        mark_pct = t_ratio * drive_pct
        lines.append(
            f'<path d="M {tx:.0f},{prev_cy:.0f} Q {tx:.0f},{(prev_cy+cy)/2:.0f} {tx:.0f},{cy:.0f}" '
            f'fill="none" stroke="#00ff00" stroke-width="1" opacity="0" stroke-dasharray="3,3">'
            f'<animate attributeName="opacity" values="0;0;0.3;0.15;0" '
            f'keyTimes="0;{mark_pct/100:.2f};{(mark_pct+2)/100:.2f};{(mark_pct+8)/100:.2f};1" '
            f'dur="{CAR_DUR}s" repeatCount="indefinite"/>'
            f'</path>'
        )

    # === TOP-DOWN DRIFT CAR ===
    lines.append("<!-- Drift Car (top-down) -->")
    lines.append(f'<g filter="url(#gl)" style="animation:car-vis {CAR_DUR}s linear infinite">')
    lines.append(f'  <animateMotion dur="{CAR_DUR * drive_pct / 100:.1f}s" repeatCount="indefinite" rotate="auto">')
    lines.append(f'    <mpath href="#carpath"/>')
    lines.append(f'  </animateMotion>')
    lines.append(f"""
  <!-- Shadow -->
  <ellipse cx="0" cy="1" rx="14" ry="7" fill="#000" opacity="0.3"/>

  <!-- Body -->
  <path d="
    M 15,0 Q 14,-3.5 11,-4.5 L 7,-5.5 L 2,-6 L -4,-6 L -9,-5.5 L -12,-5
    Q -15,-4 -15,-1 L -15,1 Q -15,4 -12,5
    L -9,5.5 L -4,6 L 2,6 L 7,5.5 L 11,4.5 Q 14,3.5 15,0 Z
  " fill="#12161f" stroke="#00ff00" stroke-width="0.8"/>

  <!-- Hood aero lines -->
  <line x1="9" y1="-3.5" x2="14" y2="0" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>
  <line x1="9" y1="3.5" x2="14" y2="0" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>
  <path d="M 8,-2 Q 10,0 8,2" fill="none" stroke="#00ff00" stroke-width="0.3" opacity="0.3"/>

  <!-- Hood scoop -->
  <rect x="7" y="-1.5" width="4" height="3" rx="1" fill="#0d1117" stroke="#00ff00" stroke-width="0.3" opacity="0.5"/>

  <!-- Windshield -->
  <path d="M 4,-5 L 7,-4.5 L 7,4.5 L 4,5 Z" fill="#0a2040" stroke="#00ff00" stroke-width="0.5" opacity="0.7"/>

  <!-- Cabin -->
  <rect x="-5" y="-4.5" width="9" height="9" rx="2" fill="#0d1520" stroke="#00ff00" stroke-width="0.4" opacity="0.6"/>

  <!-- Rear window -->
  <path d="M -7,-4.5 L -5,-5 L -5,5 L -7,4.5 Z" fill="#0a2040" stroke="#00ff00" stroke-width="0.3" opacity="0.5"/>

  <!-- Spoiler -->
  <line x1="-14" y1="-7" x2="-14" y2="7" stroke="#00ff00" stroke-width="1.5" opacity="0.8"/>
  <line x1="-14" y1="-6.5" x2="-12" y2="-5" stroke="#00ff00" stroke-width="0.6" opacity="0.5"/>
  <line x1="-14" y1="6.5" x2="-12" y2="5" stroke="#00ff00" stroke-width="0.6" opacity="0.5"/>

  <!-- Front wheels -->
  <rect x="8" y="-7.5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>
  <rect x="8" y="5" width="4" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>

  <!-- Rear wheels (wider = sport) -->
  <rect x="-11" y="-7.5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>
  <rect x="-11" y="5" width="5" height="2.5" rx="0.8" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.4" opacity="0.8"/>

  <!-- Headlights -->
  <circle cx="15" cy="-3.5" r="1.5" fill="#00ff00" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="15" cy="3.5" r="1.5" fill="#00ff00" opacity="0.9">
    <animate attributeName="opacity" values="0.8;1;0.7;1" dur="0.6s" repeatCount="indefinite"/>
  </circle>

  <!-- Taillights -->
  <rect x="-15.5" y="-4" width="2" height="2.5" rx="0.5" fill="#ff0033" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite"/>
  </rect>
  <rect x="-15.5" y="1.5" width="2" height="2.5" rx="0.5" fill="#ff0033" opacity="0.85">
    <animate attributeName="opacity" values="0.8;1;0.4;1" dur="0.3s" repeatCount="indefinite" begin="0.15s"/>
  </rect>

  <!-- Side mirrors -->
  <ellipse cx="5" cy="-7" rx="1.8" ry="1" fill="#161b22" stroke="#00ff00" stroke-width="0.3"/>
  <ellipse cx="5" cy="7" rx="1.8" ry="1" fill="#161b22" stroke="#00ff00" stroke-width="0.3"/>

  <!-- Exhaust smoke -->
  <circle r="2" fill="#00ff00" opacity="0">
    <animate attributeName="cx" values="-17;-25;-35" dur="0.6s" repeatCount="indefinite"/>
    <animate attributeName="cy" values="0;-1;-2" dur="0.6s" repeatCount="indefinite"/>
    <animate attributeName="r" values="1.5;4;7" dur="0.6s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.1;0.04;0" dur="0.6s" repeatCount="indefinite"/>
  </circle>
""")
    lines.append("</g>")

    # === EXPLOSION EFFECT ===
    lines.append(f"<!-- Explosion at end -->")

    # Flash circle
    lines.append(
        f'<circle cx="{last_cx:.0f}" cy="{last_cy:.0f}" r="60" '
        f'fill="#00ff00" style="animation:flash {CAR_DUR}s linear infinite" filter="url(#gl2)"/>'
    )

    # Expanding ring
    lines.append(
        f'<circle cx="{last_cx:.0f}" cy="{last_cy:.0f}" r="0" '
        f'fill="none" stroke="#00ff00" stroke-width="3" '
        f'style="animation:ring {CAR_DUR}s linear infinite"/>'
    )

    # Particles
    lines.append(f'<g filter="url(#gl)">')
    colors = ["#00ff00", "#39d353", "#26a641", "#ffffff", "#00ff00"]
    for i in range(NUM_PARTICLES):
        size = 3 + (i % 4)
        color = colors[i % len(colors)]
        lines.append(
            f'  <rect x="{last_cx - size/2:.0f}" y="{last_cy - size/2:.0f}" '
            f'width="{size}" height="{size}" rx="1" fill="{color}" '
            f'style="animation:boom-{i} {CAR_DUR}s linear infinite"/>'
        )
    lines.append("</g>")

    # DRIFT text on explosion
    lines.append(
        f'<text x="{last_cx:.0f}" y="{last_cy + 4:.0f}" text-anchor="middle" '
        f'font-family="monospace" font-size="20" font-weight="bold" '
        f'fill="#00ff00" filter="url(#gl2)" '
        f'style="animation:drift-text {CAR_DUR}s linear infinite">DRIFT!</text>'
    )

    # Footer
    lines.append(
        f'<text x="{W / 2:.0f}" y="{H - 4:.0f}" text-anchor="middle" '
        f'font-family="monospace" font-size="10" fill="#00ff00" opacity="0.35">'
        f'{username} // {total} contributions</text>'
    )

    lines.append("</svg>")
    return "\n".join(lines)


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
