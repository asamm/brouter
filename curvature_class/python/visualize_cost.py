#!/usr/bin/env python3
"""Gallery of the simulated roads (like out/roads.svg from generate_roads.py)
with the BRouter link cost computed by the JVM test RoadCostTest.

Roads come from out/roads.json, the costs from out/roads_cost.json (written by
jvm/src/test/kotlin/btools/router/RoadCostTest.kt), joined by osm_id.

One SVG per non-zero turncost in roads_cost.json (out/roads_cost_tc<value>.svg).
In each of them:
  - a road whose link BRouter drops (a section with sectionCost < 0, OsmPath.java:306)
    has a red tile, a red DROPPED badge, and the sections that caused it in red,
  - other roads have a badge with the cost change against turncost = 0
    (cost at turncost = 0 = BRouter distance of the road),
  - the vertices with a non-zero turncost are marked (orange = penalty, blue = bonus,
    the bigger the dot, the bigger the turncost),
  - below the road, a table with the cost for all turncost values.

Run after RoadCostTest (from curvature_class):
  python3 python/visualize_cost.py

Only the Python standard library is used.
"""

import argparse
import json
import math
import statistics
from pathlib import Path

from generate_roads import OUT_DIR, ROAD_TYPES, curviness, nice_scale

INK = "#222"
MUTED = "#666"
ROAD = "#555"  # road line; the type is in the column header, red is reserved for dropped
DROP = "#d62728"
DROP_BG = "#fdecea"
PENALTY = "#e6550d"
BONUS = "#2b7bba"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(cost, base):
    return 100.0 * (cost - base) / base if base else 0.0


def fmt_pct(p):
    if abs(p) < 0.05:
        return "±0 %"
    return f"{p:+.1f} %".replace("-", "−")


def pct_color(p):
    if abs(p) < 0.05:
        return MUTED
    return PENALTY if p > 0 else BONUS


def badge(parts, x, y, variant, base):
    """Badge 74 x 46 px, top left corner x, y: DROPPED, or the cost change in %."""
    if variant["dropped"]:
        parts.append(f'<rect x="{x}" y="{y}" width="74" height="46" rx="6" fill="{DROP}" stroke="white" stroke-width="2"/>')
        parts.append(f'<text x="{x + 37}" y="{y + 20}" text-anchor="middle" font-size="13" font-weight="bold" fill="white">DROPPED</text>')
        n = len(variant["dropped_sections"])
        parts.append(f'<text x="{x + 37}" y="{y + 36}" text-anchor="middle" font-size="10" fill="white">{n} section{"s" if n > 1 else ""} &lt; 0</text>')
        return
    p = pct(variant["cost"], base)
    color = pct_color(p)
    parts.append(f'<rect x="{x + 1}" y="{y + 1}" width="72" height="44" rx="6" fill="white" stroke="{color}" stroke-width="1.5"/>')
    parts.append(f'<text x="{x + 37}" y="{y + 13}" text-anchor="middle" font-size="9" fill="{MUTED}">cost</text>')
    parts.append(f'<text x="{x + 37}" y="{y + 36}" text-anchor="middle" font-size="17" font-weight="bold" fill="{color}">{fmt_pct(p)}</text>')


def cost_table(parts, x, y, cost, focus_tc):
    """Rows: turncost | cost | change against turncost = 0; the focus row in bold."""
    base = cost["variants"][0]["cost"]
    parts.append(f'<text x="{x}" y="{y}" font-size="9" fill="{MUTED}">turncost</text>')
    parts.append(f'<text x="{x + 92}" y="{y}" font-size="9" fill="{MUTED}" text-anchor="end">cost</text>')
    parts.append(f'<text x="{x + 160}" y="{y}" font-size="9" fill="{MUTED}" text-anchor="end">vs. tc 0</text>')
    for i, v in enumerate(cost["variants"]):
        ry = y + 14 + i * 14
        weight = ' font-weight="bold"' if v["turncost"] == focus_tc else ""
        if v["turncost"] == focus_tc:
            parts.append(f'<rect x="{x - 4}" y="{ry - 10}" width="210" height="13" fill="#f2f2f2"/>')
        parts.append(f'<text x="{x}" y="{ry}"{weight}>{v["turncost"]}</text>'.replace(">-", ">−"))
        if v["dropped"]:
            # BRouter sets cost = -1 and does not use the link; the summed value
            # (cost in roads_cost.json) is only in the tooltip
            parts.append(f'<text x="{x + 160}" y="{ry}" text-anchor="end" fill="{DROP}" font-weight="bold">✕ dropped</text>')
            continue
        parts.append(f'<text x="{x + 92}" y="{ry}" text-anchor="end"{weight}>{v["cost"]}</text>')
        if i == 0:
            parts.append(f'<text x="{x + 160}" y="{ry}" text-anchor="end" fill="{MUTED}">= distance</text>')
        else:
            p = pct(v["cost"], base)
            parts.append(f'<text x="{x + 160}" y="{ry}" text-anchor="end" fill="{pct_color(p)}"{weight}>{fmt_pct(p)}</text>')


def write_svg(roads, costs, focus_tc, costfactor, path, tile=230):
    """Same layout as write_svg in generate_roads.py: one column per road type,
    columns by median curviness, within a column sorted by curviness."""
    pad = 18
    label_h = 108
    header_h = 104
    columns = {}
    for r in roads:
        columns.setdefault(r["type"], []).append(r)
    order = sorted(columns, key=lambda t: statistics.median(curviness(r) for r in columns[t]))
    rows = max(len(c) for c in columns.values())
    width = len(order) * tile
    height = header_h + rows * (tile + label_h)
    vi = [v["turncost"] for v in costs[roads[0]["osm_id"]]["variants"]].index(focus_tc)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11" fill="{INK}">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
    ]

    # title and legend
    dropped = sum(costs[r["osm_id"]]["variants"][vi]["dropped"] for r in roads)
    parts.append(f'<text x="8" y="22" font-size="15" font-weight="bold">BRouter link cost, turncost = {focus_tc}'.replace("= -", "= −") + "</text>")
    parts.append(
        f'<text x="8" y="40" fill="{MUTED}">costfactor = {costfactor}, flat; each road = one link; '
        f'cost at turncost 0 = BRouter distance; computed by RoadCostTest (real StdPath.processWaySection)</text>'
    )
    parts.append(
        f'<text x="{width - 8}" y="22" text-anchor="end" font-size="15" font-weight="bold" '
        f'fill="{DROP if dropped else MUTED}">{dropped} of {len(roads)} links dropped</text>'
    )
    ly = 52
    lx = 8
    parts.append(f'<rect x="{lx}" y="{ly}" width="22" height="16" rx="3" fill="{DROP_BG}" stroke="{DROP}" stroke-width="2"/>')
    parts.append(f'<text x="{lx + 28}" y="{ly + 12}">link dropped: a section with sectionCost &lt; 0 (in red), BRouter cannot use the road</text>')
    lx += 520
    parts.append(f'<circle cx="{lx + 8}" cy="{ly + 8}" r="4" fill="{PENALTY}"/>')
    parts.append(f'<text x="{lx + 18}" y="{ly + 12}">turncost penalty</text>')
    lx += 120
    parts.append(f'<circle cx="{lx + 8}" cy="{ly + 8}" r="4" fill="{BONUS}"/>')
    parts.append(f'<text x="{lx + 18}" y="{ly + 12}">turncost bonus (dot area ~ |turncost| at the vertex)</text>')

    # column headers (road type = color as in roads.svg)
    for col, rtype in enumerate(order):
        cfg = ROAD_TYPES[rtype]
        hx = col * tile + 8
        parts.append(f'<rect x="{hx}" y="{header_h - 20}" width="12" height="12" fill="{cfg["color"]}"/>')
        parts.append(f'<text x="{hx + 16}" y="{header_h - 10}" font-weight="bold">{rtype} ({cfg["highway"]})</text>')

    for col, rtype in enumerate(order):
        for row, r in enumerate(sorted(columns[rtype], key=curviness)):
            cost = costs[r["osm_id"]]
            variant = cost["variants"][vi]
            base = cost["variants"][0]["cost"]
            is_dropped = variant["dropped"]
            ox = col * tile
            oy = header_h + row * (tile + label_h)
            xs = [p[0] for p in r["points_local"]]
            ys = [p[1] for p in r["points_local"]]
            span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
            scale = (tile - 2 * pad) / span
            cx = (max(xs) + min(xs)) / 2
            cy = (max(ys) + min(ys)) / 2

            def px(x, y):
                # svg y axis goes down => flip
                return ox + tile / 2 + (x - cx) * scale, oy + tile / 2 - (y - cy) * scale

            pts = [px(x, y) for x, y in r["points_local"]]

            tip = [f'{r["osm_id"]} {r["type"]} ({r["highway"]})', f'distance {cost["dist_m"]} m, {len(cost["sections"])} sections']
            for v in cost["variants"]:
                tip.append(
                    f'turncost {v["turncost"]}: cost {v["cost"]}{" (if not dropped)" if v["dropped"] else ""}, turncost sum {v["turncost_sum"]}'
                    + (f', DROPPED by sections {v["dropped_sections"]}' if v["dropped"] else "")
                )
            for i in variant["dropped_sections"]:
                s = cost["sections"][i]
                tip.append(
                    f'section {i}: {s["dist"]} m after {s["angle"]:.0f}°, turncost {variant["section_turncost"][i]}, '
                    f'sectionCost {variant["section_cost"][i]}'
                )
            parts.append(f'<g><title>{esc(chr(10).join(tip))}</title>')
            if is_dropped:
                parts.append(f'<rect x="{ox + 3}" y="{oy + 3}" width="{tile - 6}" height="{tile + label_h - 6}" fill="{DROP_BG}" stroke="{DROP}" stroke-width="3"/>')
            else:
                parts.append(f'<rect x="{ox + 2}" y="{oy + 2}" width="{tile - 4}" height="{tile + label_h - 4}" fill="white" stroke="#ddd"/>')

            parts.append(
                f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" '
                f'fill="none" stroke="{ROAD}" stroke-width="2" stroke-linejoin="round"'
                + (' stroke-dasharray="5 3"' if is_dropped else "") + "/>"
            )
            # turncost at the vertices: section i starts at points_local[i], its angle is there
            for i, tc in enumerate(variant["section_turncost"]):
                if tc:
                    x, y = pts[i]
                    rad = 1.2 * math.sqrt(abs(tc))
                    parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="{PENALTY if tc > 0 else BONUS}" fill-opacity="0.75"/>')
            # sections that drop the link: thick red, with a ring at the vertex
            for i in variant["dropped_sections"]:
                (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{DROP}" stroke-width="5" stroke-linecap="round"/>')
                parts.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="9" fill="none" stroke="{DROP}" stroke-width="2"/>')
            sx, sy = pts[0]
            ex, ey = pts[-1]
            parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="3" fill="#333"/>')
            parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="white" stroke="#333" stroke-width="1.5"/>')
            badge(parts, ox + tile - 82, oy + 8, variant, base)
            # scale bar
            bar_m = nice_scale(span * 0.4)
            bar_px = bar_m * scale
            bx, by = ox + 10, oy + tile - 8
            parts.append(f'<line x1="{bx}" y1="{by}" x2="{bx + bar_px:.1f}" y2="{by}" stroke="black" stroke-width="2"/>')
            parts.append(f'<text x="{bx}" y="{by - 4}" font-size="9">{bar_m} m</text>')
            # labels
            ty = oy + tile
            parts.append(f'<text x="{ox + 8}" y="{ty + 10}" font-weight="bold">{r["osm_id"]} {r["type"]}</text>')
            parts.append(f'<text x="{ox + 8}" y="{ty + 24}">{cost["dist_m"]} m, {len(cost["sections"])} sections, {curviness(r):.0f}°/km</text>')
            cost_table(parts, ox + 12, ty + 40, cost, focus_tc)
            parts.append("</g>")

    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roads", type=Path, default=OUT_DIR / "roads.json", help="roads from generate_roads.py (default curvature_class/out/roads.json)")
    ap.add_argument("--cost", type=Path, default=OUT_DIR / "roads_cost.json", help="costs from RoadCostTest (default curvature_class/out/roads_cost.json)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="output directory (default curvature_class/out)")
    args = ap.parse_args()

    roads = json.loads(args.roads.read_text(encoding="utf-8"))
    for r in roads:  # roads.json has length_m, curviness() uses length
        r["length"] = r["length_m"]
    data = json.loads(args.cost.read_text(encoding="utf-8"))
    costs = {c["osm_id"]: c for c in data["roads"]}
    missing = [r["osm_id"] for r in roads if r["osm_id"] not in costs]
    if missing:
        raise SystemExit(f"not in {args.cost.name}: {missing} (run RoadCostTest again)")
    if data["turncosts"][0] != 0:
        raise SystemExit("the first turncost in roads_cost.json must be 0 (the reference)")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for tc in data["turncosts"][1:]:
        out = args.out_dir / f"roads_cost_tc{tc}.svg"
        write_svg(roads, costs, tc, data["costfactor"], out)
        dropped = sum(costs[r["osm_id"]]["variants"][data["turncosts"].index(tc)]["dropped"] for r in roads)
        print(f"turncost {tc:>4}: {dropped:2d} of {len(roads)} links dropped, written: {out}")


if __name__ == "__main__":
    main()
