#!/usr/bin/env python3
"""Generate an animated 52-week SVG from a public GitHub contribution calendar."""

from __future__ import annotations

import argparse
import html as html_lib
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


DAY_PATTERN = re.compile(
    r'<td[^>]*data-date="([^"]+)"[^>]*id="([^"]+)"[^>]*data-level="(\d+)"[^>]*></td>'
    r'\s*<tool-tip[^>]*for="\2"[^>]*>([^<]+)</tool-tip>',
    re.DOTALL,
)
COUNT_PATTERN = re.compile(r"([\d,]+) contributions?")


@dataclass(frozen=True)
class ContributionDay:
    day: date
    count: int
    level: int


@dataclass(frozen=True)
class ContributionWeek:
    start: date
    count: int
    active_days: int
    level: int


THEMES = {
    "light": {
        "background_a": "#F8FAFC",
        "background_b": "#EEF2FF",
        "grid": "#94A3B8",
        "text": "#0F172A",
        "muted": "#64748B",
        "zero": "#CBD5E1",
        "primary": "#0891B2",
        "secondary": "#7C3AED",
        "accent": "#DB2777",
        "panel": "#FFFFFF",
    },
    "dark": {
        "background_a": "#050816",
        "background_b": "#111827",
        "grid": "#64748B",
        "text": "#F8FAFC",
        "muted": "#94A3B8",
        "zero": "#334155",
        "primary": "#22D3EE",
        "secondary": "#A78BFA",
        "accent": "#F472B6",
        "panel": "#0F172A",
    },
}


def fetch_calendar(username: str) -> str:
    url = f"https://github.com/users/{username}/contributions"
    request = Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "profile-contribution-landscape/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"GitHub returned HTTP {response.status}")
        return response.read().decode("utf-8")


def parse_calendar(source: str) -> list[ContributionDay]:
    days: list[ContributionDay] = []
    for date_text, _element_id, level_text, tooltip in DAY_PATTERN.findall(source):
        match = COUNT_PATTERN.search(tooltip)
        count = int(match.group(1).replace(",", "")) if match else 0
        days.append(
            ContributionDay(
                day=date.fromisoformat(date_text),
                count=count,
                level=int(level_text),
            )
        )
    if len(days) < 300:
        raise RuntimeError(
            f"Expected at least 300 calendar cells, parsed {len(days)}; "
            "GitHub may have changed its contribution markup."
        )
    return sorted(days, key=lambda item: item.day)


def aggregate_weeks(days: list[ContributionDay]) -> list[ContributionWeek]:
    first_day = days[0].day
    first_sunday = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
    grouped: dict[date, list[ContributionDay]] = defaultdict(list)
    for item in days:
        week_start = item.day - timedelta(days=(item.day.weekday() + 1) % 7)
        grouped[week_start].append(item)

    number_of_weeks = ((days[-1].day - first_sunday).days // 7) + 1
    weeks: list[ContributionWeek] = []
    for index in range(number_of_weeks):
        week_start = first_sunday + timedelta(days=index * 7)
        items = grouped.get(week_start, [])
        weeks.append(
            ContributionWeek(
                start=week_start,
                count=sum(item.count for item in items),
                active_days=sum(item.count > 0 for item in items),
                level=max((item.level for item in items), default=0),
            )
        )
    return weeks[-53:]


def smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    commands = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(len(points) - 1, index + 2)]
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        commands.append(
            f"C {c1x:.1f} {c1y:.1f}, {c2x:.1f} {c2y:.1f}, {p2[0]:.1f} {p2[1]:.1f}"
        )
    return " ".join(commands)


def node_color(normalized: float, theme: dict[str, str]) -> str:
    if normalized >= 0.72:
        return theme["accent"]
    if normalized >= 0.36:
        return theme["secondary"]
    if normalized > 0:
        return theme["primary"]
    return theme["zero"]


def render_svg(
    username: str,
    days: list[ContributionDay],
    weeks: list[ContributionWeek],
    theme_name: str,
) -> str:
    theme = THEMES[theme_name]
    width, height = 1200, 360
    left, right = 72.0, 1128.0
    graph_top, graph_bottom = 104.0, 270.0
    step = (right - left) / max(1, len(weeks) - 1)
    max_week = max((week.count for week in weeks), default=1) or 1
    total = sum(item.count for item in days)
    active_days = sum(item.count > 0 for item in days)
    peak_index = max(range(len(weeks)), key=lambda index: weeks[index].count)

    points: list[tuple[float, float]] = []
    normalized_values: list[float] = []
    for index, week in enumerate(weeks):
        normalized = math.sqrt(week.count / max_week) if week.count else 0.0
        x = left + index * step
        y = graph_bottom - normalized * (graph_bottom - graph_top)
        points.append((x, y))
        normalized_values.append(normalized)

    path = smooth_path(points)
    area_path = f"{path} L {points[-1][0]:.1f} {graph_bottom:.1f} L {points[0][0]:.1f} {graph_bottom:.1f} Z"

    horizontal_grid = []
    for index, ratio in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
        y = graph_bottom - ratio * (graph_bottom - graph_top)
        label = round(max_week * ratio)
        horizontal_grid.append(
            f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{right:.1f}" y2="{y:.1f}" '
            f'stroke="{theme["grid"]}" stroke-opacity="0.13"/>'
        )
        if index in (0, 2, 4):
            horizontal_grid.append(
                f'<text x="{left - 14:.1f}" y="{y + 4:.1f}" text-anchor="end" '
                f'fill="{theme["muted"]}" font-size="10">{label}</text>'
            )

    month_labels = []
    previous_month: tuple[int, int] | None = None
    for index, week in enumerate(weeks):
        center = week.start + timedelta(days=3)
        current_month = (center.year, center.month)
        if current_month != previous_month:
            x = left + index * step
            month_labels.append(
                f'<line x1="{x:.1f}" y1="{graph_top - 8:.1f}" x2="{x:.1f}" y2="{graph_bottom + 8:.1f}" '
                f'stroke="{theme["grid"]}" stroke-opacity="0.10"/>'
            )
            month_labels.append(
                f'<text x="{x:.1f}" y="{graph_bottom + 31:.1f}" fill="{theme["muted"]}" '
                f'font-size="10" font-weight="650" letter-spacing="1">{center.strftime("%b").upper()}</text>'
            )
            previous_month = current_month

    nodes = []
    heat_strip = []
    top_indices = set(
        sorted(range(len(weeks)), key=lambda index: weeks[index].count, reverse=True)[:3]
    )
    for index, (week, point, normalized) in enumerate(zip(weeks, points, normalized_values)):
        x, y = point
        color = node_color(normalized, theme)
        radius = 2.2 + normalized * 6.4
        opacity = 0.28 if week.count == 0 else 0.72 + normalized * 0.28
        class_name = ' class="beacon"' if index in top_indices else ""
        nodes.append(
            f'<circle{class_name} cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{color}" fill-opacity="{opacity:.2f}" '
            f'stroke="{theme["panel"]}" stroke-width="1.2">'
            f'<title>{week.start.isoformat()}: {week.count} contributions</title></circle>'
        )
        strip_width = max(4.0, step - 3.0)
        heat_strip.append(
            f'<rect x="{x - strip_width / 2:.1f}" y="326" width="{strip_width:.1f}" height="6" rx="3" '
            f'fill="{color}" fill-opacity="{0.20 if week.count == 0 else 0.42 + normalized * 0.58:.2f}"/>'
        )

    peak_x, peak_y = points[peak_index]
    latest_x, latest_y = points[-1]
    updated = max(item.day for item in days).isoformat()
    escaped_user = html_lib.escape(username)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="360" viewBox="0 0 1200 360" role="img" aria-labelledby="title desc">
  <title id="title">{escaped_user} contribution decision landscape</title>
  <desc id="desc">A 52-week trajectory generated from {total} public GitHub contributions across {active_days} active days.</desc>
  <defs>
    <linearGradient id="background" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{theme["background_a"]}"/>
      <stop offset="1" stop-color="{theme["background_b"]}"/>
    </linearGradient>
    <linearGradient id="signal" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{theme["primary"]}"/>
      <stop offset="0.52" stop-color="{theme["secondary"]}"/>
      <stop offset="1" stop-color="{theme["accent"]}"/>
    </linearGradient>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{theme["secondary"]}" stop-opacity="0.30"/>
      <stop offset="1" stop-color="{theme["primary"]}" stop-opacity="0"/>
    </linearGradient>
    <filter id="glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <style>
    .signal-flow {{ stroke-dasharray: 12 16; animation: flow 13s linear infinite; }}
    .beacon {{ transform-box: fill-box; transform-origin: center; animation: pulse 3.2s ease-in-out infinite; filter: url(#glow); }}
    .scanner {{ animation: scan 9s ease-in-out infinite; }}
    @keyframes flow {{ to {{ stroke-dashoffset: -280; }} }}
    @keyframes pulse {{ 0%, 100% {{ opacity: .62; transform: scale(.82); }} 50% {{ opacity: 1; transform: scale(1.28); }} }}
    @keyframes scan {{ 0%, 100% {{ transform: translateX(0); opacity: 0; }} 10%, 90% {{ opacity: .6; }} 50% {{ transform: translateX(1056px); opacity: .9; }} }}
    @media (prefers-reduced-motion: reduce) {{ .signal-flow, .beacon, .scanner {{ animation: none; }} }}
  </style>

  <rect width="1200" height="360" rx="22" fill="url(#background)"/>
  <rect x="1" y="1" width="1198" height="358" rx="21" fill="none" stroke="{theme["grid"]}" stroke-opacity="0.18"/>

  <g font-family="Inter, Segoe UI, Arial, sans-serif">
    <text x="72" y="45" fill="{theme["primary"]}" font-size="13" font-weight="750" letter-spacing="2.4">CONTRIBUTION DECISION LANDSCAPE</text>
    <text x="72" y="72" fill="{theme["text"]}" font-size="18" font-weight="650">{total:,} contributions · {active_days} active days</text>
    <text x="1128" y="45" text-anchor="end" fill="{theme["muted"]}" font-size="11" font-weight="650" letter-spacing="1.2">52-WEEK PUBLIC TRACE</text>
    <text x="1128" y="70" text-anchor="end" fill="{theme["muted"]}" font-size="10">UPDATED {updated}</text>

    <g>{''.join(horizontal_grid)}</g>
    <g>{''.join(month_labels)}</g>

    <path d="{area_path}" fill="url(#area)"/>
    <path d="{path}" fill="none" stroke="{theme["primary"]}" stroke-opacity="0.28" stroke-width="5" filter="url(#glow)"/>
    <path d="{path}" fill="none" stroke="url(#signal)" stroke-width="2.8" stroke-linecap="round"/>
    <path class="signal-flow" d="{path}" fill="none" stroke="{theme["text"]}" stroke-opacity="0.45" stroke-width="1.2" stroke-linecap="round"/>

    <g>{''.join(nodes)}</g>
    <g>{''.join(heat_strip)}</g>

    <line class="scanner" x1="72" y1="92" x2="72" y2="304" stroke="{theme["primary"]}" stroke-width="1.4" stroke-opacity="0.7" filter="url(#glow)"/>

    <g>
      <line x1="{peak_x:.1f}" y1="{peak_y - 12:.1f}" x2="{peak_x:.1f}" y2="{peak_y - 28:.1f}" stroke="{theme["accent"]}" stroke-opacity="0.65"/>
      <text x="{peak_x:.1f}" y="{peak_y - 36:.1f}" text-anchor="middle" fill="{theme["accent"]}" font-size="9" font-weight="750" letter-spacing="1">PEAK · {weeks[peak_index].count}</text>
      <circle cx="{latest_x:.1f}" cy="{latest_y:.1f}" r="12" fill="none" stroke="{theme["primary"]}" stroke-opacity="0.65" stroke-width="1.4"/>
      <text x="{latest_x - 8:.1f}" y="{latest_y - 18:.1f}" text-anchor="end" fill="{theme["primary"]}" font-size="9" font-weight="750" letter-spacing="1">NOW</text>
    </g>

    <text x="72" y="349" fill="{theme["muted"]}" font-size="9" font-weight="650" letter-spacing="1.2">HEIGHT + NODE SIZE = WEEKLY PUBLIC ACTIVITY</text>
    <text x="1128" y="349" text-anchor="end" fill="{theme["muted"]}" font-size="9" font-weight="650" letter-spacing="1.2">EXPLORE · BUILD · TRACE · REPAIR</text>
  </g>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True, help="GitHub username")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--source-file", type=Path, help="Use saved HTML instead of fetching")
    args = parser.parse_args()

    source = (
        args.source_file.read_text(encoding="utf-8")
        if args.source_file
        else fetch_calendar(args.user)
    )
    days = parse_calendar(source)
    weeks = aggregate_weeks(days)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    light_path = args.output_dir / "contribution-landscape.svg"
    dark_path = args.output_dir / "contribution-landscape-dark.svg"
    light_path.write_text(render_svg(args.user, days, weeks, "light"), encoding="utf-8")
    dark_path.write_text(render_svg(args.user, days, weeks, "dark"), encoding="utf-8")

    print(
        f"Generated {light_path} and {dark_path} from "
        f"{sum(item.count for item in days):,} contributions."
    )


if __name__ == "__main__":
    main()
