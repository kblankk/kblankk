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
    """Generate the drift car SVG with real contribution data."""

    weeks = calendar["weeks"]
    total = calendar["totalContributions"]

    # Grid configuration
    CELL = 11
    GAP = 2
    STRIDE = CELL + GAP
    ROWS = 7
    COLS = len(weeks)

    GRID_W = COLS * STRIDE - GAP
    GRID_H = ROWS * STRIDE - GAP

    W = GRID_W + 80  # padding
    H = GRID_H + 80

    GX = (W - GRID_W) / 2
    GY = 30

    # Car config - small car
    CAR_DUR = 8
    CAR_START_X = -120
    CAR_END_X = W + 60
    CAR_TRAVEL = CAR_END_X - CAR_START_X

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">')

    # === STYLES ===
    lines.append("<style>")
    lines.append(f"""
  .car {{ animation: drive {CAR_DUR}s ease-in-out infinite; }}
  @keyframes drive {{
    0% {{ transform: translateX({CAR_START_X}px); }}
    100% {{ transform: translateX({CAR_END_X:.0f}px); }}
  }}
""")
    lines.append("</style>")

    # === DEFS ===
    lines.append("""<defs>
  <filter id="gl">
    <feGaussianBlur stdDeviation="1.5" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>""")

    # === BACKGROUND ===
    lines.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#0d1117"/>')

    # === CONTRIBUTION GRID (real data) ===
    lines.append("<!-- Contribution Grid -->")
    lines.append("<g>")
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            x = GX + c * STRIDE
            y = GY + r * STRIDE
            color = map_color(day["color"])
            lines.append(
                f'  <rect x="{x:.0f}" y="{y:.0f}" width="{CELL}" height="{CELL}" '
                f'rx="2" fill="{color}"/>'
            )
    lines.append("</g>")

    # === TIRE MARKS (subtle, along the car path) ===
    car_y = GY + 2.5 * STRIDE  # car drives across row ~2-3 area
    tire_y1 = car_y + 2
    tire_y2 = car_y + 18

    lines.append("<!-- Tire marks -->")
    lines.append(
        f'<line x1="{GX:.0f}" y1="{tire_y1:.0f}" '
        f'x2="{GX + GRID_W:.0f}" y2="{tire_y1:.0f}" '
        f'stroke="#222" stroke-width="1.5" stroke-dasharray="8,5" opacity="0.3"/>'
    )
    lines.append(
        f'<line x1="{GX:.0f}" y1="{tire_y2:.0f}" '
        f'x2="{GX + GRID_W:.0f}" y2="{tire_y2:.0f}" '
        f'stroke="#222" stroke-width="1.5" stroke-dasharray="8,5" opacity="0.3"/>'
    )

    # === SMALL DRIFT CAR ===
    # Car ~85px long, ~28px tall, positioned to drive over the grid
    by = car_y - 10  # base y for car top

    lines.append("<!-- Drift Car -->")
    lines.append('<g class="car" filter="url(#gl)">')
    lines.append(f"""
  <!-- Shadow -->
  <ellipse cx="42" cy="{by+32}" rx="36" ry="3" fill="#000" opacity="0.35"/>

  <!-- Body -->
  <path d="
    M 4,{by+26}
    L 2,{by+22}
    L 4,{by+18}
    L 10,{by+15}
    L 20,{by+11}
    L 30,{by+8}
    L 36,{by+5}
    L 50,{by+3}
    L 62,{by+4}
    L 70,{by+7}
    L 76,{by+12}
    L 82,{by+16}
    L 86,{by+20}
    L 87,{by+24}
    L 86,{by+27}
    L 82,{by+29}
    L 10,{by+29}
    L 6,{by+28}
    Z
  " fill="#12161f" stroke="#00ff00" stroke-width="0.8"/>

  <!-- Side skirt -->
  <path d="M 8,{by+26} L 10,{by+29} L 80,{by+29} L 82,{by+26} Z"
        fill="#0a0e15" stroke="#00ff00" stroke-width="0.4" opacity="0.7"/>

  <!-- Windshield -->
  <path d="M 30,{by+8} L 36,{by+5} L 50,{by+3} L 50,{by+9} L 30,{by+9} Z"
        fill="#0a1628" stroke="#00ff00" stroke-width="0.5" opacity="0.7"/>

  <!-- Side window -->
  <path d="M 31,{by+8} L 49,{by+4} L 60,{by+5} L 67,{by+8} L 31,{by+8} Z"
        fill="#0a1628" opacity="0.4"/>

  <!-- Rear window -->
  <path d="M 62,{by+5} L 70,{by+7} L 76,{by+12} L 62,{by+9} Z"
        fill="#0a1628" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>

  <!-- Spoiler -->
  <line x1="78" y1="{by+10}" x2="90" y2="{by+10}" stroke="#00ff00" stroke-width="1.2" opacity="0.8"/>
  <line x1="80" y1="{by+10}" x2="79" y2="{by+14}" stroke="#00ff00" stroke-width="0.7" opacity="0.6"/>
  <line x1="87" y1="{by+10}" x2="86" y2="{by+14}" stroke="#00ff00" stroke-width="0.7" opacity="0.6"/>

  <!-- Headlight -->
  <rect x="2" y="{by+19}" width="3" height="4" rx="1" fill="#00ff00" opacity="0.9">
    <animate attributeName="opacity" values="0.9;1;0.8;1" dur="1s" repeatCount="indefinite"/>
  </rect>

  <!-- Taillight -->
  <rect x="86" y="{by+21}" width="2" height="4" rx="0.5" fill="#ff0033" opacity="0.85">
    <animate attributeName="opacity" values="0.85;1;0.5;1" dur="0.35s" repeatCount="indefinite"/>
  </rect>

  <!-- Front wheel -->
  <circle cx="18" cy="{by+29}" r="6" fill="#111" stroke="#333" stroke-width="1"/>
  <circle cx="18" cy="{by+29}" r="3.5" fill="none" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>
  <circle cx="18" cy="{by+29}" r="1.5" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.3"/>
  <circle cx="18" cy="{by+29}" r="6" fill="none" stroke="#222" stroke-width="1.2" stroke-dasharray="1.5,1.5">
    <animateTransform attributeName="transform" type="rotate" from="0 18 {by+29}" to="360 18 {by+29}" dur="0.2s" repeatCount="indefinite"/>
  </circle>

  <!-- Rear wheel -->
  <circle cx="72" cy="{by+29}" r="6" fill="#111" stroke="#333" stroke-width="1"/>
  <circle cx="72" cy="{by+29}" r="3.5" fill="none" stroke="#00ff00" stroke-width="0.4" opacity="0.5"/>
  <circle cx="72" cy="{by+29}" r="1.5" fill="#1a1a1a" stroke="#00ff00" stroke-width="0.3"/>
  <circle cx="72" cy="{by+29}" r="6" fill="none" stroke="#222" stroke-width="1.2" stroke-dasharray="1.5,1.5">
    <animateTransform attributeName="transform" type="rotate" from="0 72 {by+29}" to="360 72 {by+29}" dur="0.1s" repeatCount="indefinite"/>
  </circle>

  <!-- Exhaust smoke -->
  <circle cx="90" cy="{by+26}" r="2" fill="#00ff00" opacity="0.06">
    <animate attributeName="cx" values="90;100;112" dur="0.8s" repeatCount="indefinite"/>
    <animate attributeName="r" values="2;5;9" dur="0.8s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.08;0.03;0" dur="0.8s" repeatCount="indefinite"/>
  </circle>
  <circle cx="90" cy="{by+28}" r="1.5" fill="#444" opacity="0.06">
    <animate attributeName="cx" values="90;102;115" dur="1s" repeatCount="indefinite" begin="0.3s"/>
    <animate attributeName="r" values="1.5;4;8" dur="1s" repeatCount="indefinite" begin="0.3s"/>
    <animate attributeName="opacity" values="0.07;0.03;0" dur="1s" repeatCount="indefinite" begin="0.3s"/>
  </circle>

  <!-- Speed lines -->
  <g opacity="0.25">
    <line x1="92" y1="{by+15}" x2="100" y2="{by+15}" stroke="#00ff00" stroke-width="0.6">
      <animate attributeName="x2" values="100;106;100" dur="0.25s" repeatCount="indefinite"/>
    </line>
    <line x1="92" y1="{by+20}" x2="103" y2="{by+20}" stroke="#00ff00" stroke-width="0.6">
      <animate attributeName="x2" values="103;110;103" dur="0.2s" repeatCount="indefinite"/>
    </line>
    <line x1="92" y1="{by+25}" x2="98" y2="{by+25}" stroke="#00ff00" stroke-width="0.6">
      <animate attributeName="x2" values="98;105;98" dur="0.3s" repeatCount="indefinite"/>
    </line>
  </g>""")

    lines.append("</g>")

    # Footer
    lines.append(
        f'<text x="{W / 2:.0f}" y="{H - 6:.0f}" text-anchor="middle" '
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
