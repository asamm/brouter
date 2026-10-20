#!/usr/bin/env python3
"""Gallery of the simulated roads (like out/roads.svg from generate_roads.py)
with the computed estimated_curvature_class of each road.

Roads come from out/roads.json, the computed values from the database
(table lines + curvature_tags + functions.sql), joined by osm_id. Each tile
shows the class as a badge (light = class 1 ... dark = class 6), the score,
the share / length in hairpins (R < 30 m) and whether the hairpin rule raised
the class.

The values are read by psql (must be on PATH), connection by the usual
PGHOST / PGPORT / PGUSER / PGDATABASE variables and ~/.pgpass, or --db.
Without a database: --csv with the output of the query QUERY below
(psql --csv -c "<QUERY>" > classes.csv).

Run after curvature_tags.sql:
  python3 python/visualize_curvature.py --db curvature_test

Only the Python standard library is used.
"""

import argparse
import csv
import io
import json
import statistics
import subprocess
import sys
from pathlib import Path

from generate_roads import OUT_DIR, ROAD_TYPES, curviness, nice_scale

# one row per road in lines; curvature_class = the tag (curvature_tags),
# class_by_score = without the hairpin rule
QUERY = """
SELECT
    l.osm_id,
    round(m.len_m::numeric) AS len_m,
    round(m.score::numeric, 2) AS score,
    round((100 * m.shares[1])::numeric, 1) AS hairpin_pct,
    round((m.shares[1] * m.n_radii * m.step_m)::numeric) AS hairpin_m,
    m.n_radii,
    curv_class (m.score) AS class_by_score,
    t.curvature_class
FROM
    lines l
    LEFT JOIN curvature_tags t ON t.losmid = l.osm_id::bigint,
    LATERAL curv_metrics (l.way, l.merca_coef) AS m
ORDER BY
    l.osm_id
"""

# ordinal ramp for the classes '1'..'6' (one hue, light -> dark), interpolated
# in OKLab between two blues; lightness grows monotonically with a clear step
# between neighbouring classes, the lightest one still has 2:1 contrast on white
CLASS_COLORS = ["#86b6ef", "#6d9bd3", "#5480b8", "#3c679e", "#254e84", "#0d366b"]
CLASS_TEXT = ["#14233a", "#14233a", "#ffffff", "#ffffff", "#ffffff", "#ffffff"]
CLASS_MEANING = ["occasional curve", "wavy", "curvy", "very curvy", "mountain road", "extreme"]
INK = "#222"
MUTED = "#666"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def read_values(args):
    if args.csv:
        text = args.csv.read_text(encoding="utf-8")
    else:
        cmd = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "--csv", "-c", QUERY]
        if args.db:
            cmd.insert(1, args.db)
        try:
            text = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
        except FileNotFoundError:
            sys.exit("psql not found, use --csv")
        except subprocess.CalledProcessError as e:
            sys.exit(f"psql failed:\n{e.stderr}")
    return {int(row["osm_id"]): row for row in csv.DictReader(io.StringIO(text))}


def badge(parts, x, y, v):
    """Class badge 46 x 46 px, top left corner x, y."""
    cls = v["curvature_class"] if v else ""
    if cls:
        i = int(cls) - 1
        parts.append(f'<rect x="{x}" y="{y}" width="46" height="46" rx="6" fill="{CLASS_COLORS[i]}" stroke="white" stroke-width="2"/>')
        parts.append(f'<text x="{x + 23}" y="{y + 13}" text-anchor="middle" font-size="9" fill="{CLASS_TEXT[i]}">class</text>')
        parts.append(
            f'<text x="{x + 23}" y="{y + 39}" text-anchor="middle" font-size="26" font-weight="bold" fill="{CLASS_TEXT[i]}">{cls}</text>'
        )
        return
    # no tag: straight (score < 0.1), undefined (too short) or not in the database
    if v is None:
        mark, label, dash = "×", "not in DB", ""
    elif v["score"] == "":
        mark, label, dash = "?", "short", ' stroke-dasharray="3 3"'
    else:
        mark, label, dash = "–", "no tag", ""
    parts.append(f'<rect x="{x + 1}" y="{y + 1}" width="44" height="44" rx="6" fill="white" stroke="#999" stroke-width="1.5"{dash}/>')
    parts.append(f'<text x="{x + 23}" y="{y + 13}" text-anchor="middle" font-size="9" fill="{MUTED}">{label}</text>')
    parts.append(f'<text x="{x + 23}" y="{y + 38}" text-anchor="middle" font-size="22" fill="{MUTED}">{mark}</text>')


def write_svg(roads, values, path, tile=230):
    """Same layout as write_svg in generate_roads.py: one column per road type,
    columns by median curviness, within a column sorted by curviness."""
    pad = 18
    label_h = 62
    header_h = 92
    columns = {}
    for r in roads:
        columns.setdefault(r["type"], []).append(r)
    order = sorted(columns, key=lambda t: statistics.median(curviness(r) for r in columns[t]))
    rows = max(len(c) for c in columns.values())
    width = len(order) * tile
    height = header_h + rows * (tile + label_h)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11" fill="{INK}">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
    ]

    # legend: classes with counts, then the "no tag" variants
    counts = {}
    for r in roads:
        v = values.get(r["osm_id"])
        key = (v["curvature_class"] or ("undefined" if v["score"] == "" else "no tag")) if v else "not in DB"
        counts[key] = counts.get(key, 0) + 1
    parts.append(f'<text x="8" y="20" font-size="13" font-weight="bold">estimated_curvature_class</text>')
    parts.append(
        f'<text x="230" y="20" fill="{MUTED}">badge = tag from curvature_tags; '
        f'↑ = raised by the hairpin rule (≥ 25 % and ≥ 100 m with R &lt; 30 m)</text>'
    )
    lx = 8
    for i in range(6):
        parts.append(f'<rect x="{lx}" y="30" width="22" height="22" rx="4" fill="{CLASS_COLORS[i]}"/>')
        parts.append(f'<text x="{lx + 11}" y="46" text-anchor="middle" font-weight="bold" fill="{CLASS_TEXT[i]}">{i + 1}</text>')
        parts.append(f'<text x="{lx + 28}" y="45">{CLASS_MEANING[i]} ({counts.get(str(i + 1), 0)})</text>')
        lx += 150
    for mark, label, dash in (("–", "no tag", ""), ("?", "undefined", ' stroke-dasharray="3 3"'), ("×", "not in DB", "")):
        if label not in counts and label != "no tag":
            continue
        parts.append(f'<rect x="{lx + 1}" y="31" width="20" height="20" rx="4" fill="white" stroke="#999"{dash}/>')
        parts.append(f'<text x="{lx + 11}" y="46" text-anchor="middle" fill="{MUTED}">{mark}</text>')
        text = "short = undefined" if label == "undefined" else label
        parts.append(f'<text x="{lx + 28}" y="45">{text} ({counts.get(label, 0)})</text>')
        lx += 160

    # column headers (road type = color of the line, as in roads.svg)
    for col, rtype in enumerate(order):
        cfg = ROAD_TYPES[rtype]
        hx = col * tile + 8
        parts.append(f'<rect x="{hx}" y="71" width="12" height="12" fill="{cfg["color"]}"/>')
        parts.append(f'<text x="{hx + 16}" y="81" font-weight="bold">{rtype} ({cfg["highway"]})</text>')

    for col, rtype in enumerate(order):
        for row, r in enumerate(sorted(columns[rtype], key=curviness)):
            v = values.get(r["osm_id"])
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
            color = ROAD_TYPES[r["type"]]["color"]
            raised = bool(v and v["curvature_class"] and v["curvature_class"] != v["class_by_score"])

            # tooltip with all values
            tip = [f'{r["osm_id"]} {r["type"]} ({r["highway"]})']
            if v:
                tip += [f'{k} = {v[k] or "NULL"}' for k in ("len_m", "score", "hairpin_pct", "hairpin_m", "n_radii", "class_by_score", "curvature_class")]
            parts.append(f'<g><title>{esc(chr(10).join(tip))}</title>')
            parts.append(f'<rect x="{ox + 2}" y="{oy + 2}" width="{tile - 4}" height="{tile + label_h - 4}" fill="white" stroke="#ddd"/>')
            parts.append(
                f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" '
                f'fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            )
            for x, y in pts:  # vertices as in OSM
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1" fill="#333"/>')
            sx, sy = pts[0]
            ex, ey = pts[-1]
            parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="3" fill="#2ca02c"/>')
            parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="#d62728"/>')
            badge(parts, ox + tile - 54, oy + 8, v)
            # scale bar
            bar_m = nice_scale(span * 0.4)
            bar_px = bar_m * scale
            bx, by = ox + 10, oy + tile - 8
            parts.append(f'<line x1="{bx}" y1="{by}" x2="{bx + bar_px:.1f}" y2="{by}" stroke="black" stroke-width="2"/>')
            parts.append(f'<text x="{bx}" y="{by - 4}" font-size="9">{bar_m} m</text>')
            # labels
            ty = oy + tile
            parts.append(f'<text x="{ox + 8}" y="{ty + 10}" font-weight="bold">{r["osm_id"]} {r["type"]}</text>')
            parts.append(f'<text x="{ox + 8}" y="{ty + 24}">{r["length"]:.0f} m, turn {r["turning_deg"]:.0f}°, {curviness(r):.0f}°/km</text>')
            if v is None:
                parts.append(f'<text x="{ox + 8}" y="{ty + 38}" fill="{MUTED}">not in the database</text>')
            elif v["score"] == "":
                parts.append(f'<text x="{ox + 8}" y="{ty + 38}" fill="{MUTED}">too short: {v["n_radii"]} radii (min. 5)</text>')
            else:
                parts.append(f'<text x="{ox + 8}" y="{ty + 38}">score {v["score"]}, hairpins {float(v["hairpin_pct"]):.0f} % / {v["hairpin_m"]} m</text>')
            if raised:
                parts.append(
                    f'<text x="{ox + 8}" y="{ty + 52}" font-weight="bold">↑ hairpin rule: class {v["curvature_class"]} (score → {v["class_by_score"]})</text>'
                )
            parts.append("</g>")
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roads", type=Path, default=OUT_DIR / "roads.json", help="roads from generate_roads.py (default curvature_class/out/roads.json)")
    ap.add_argument("--db", help="database name or connection string for psql (default: PG* variables)")
    ap.add_argument("--csv", type=Path, help="computed values from a file instead of the database (columns of QUERY)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "roads_curvature.svg", help="output (default curvature_class/out/roads_curvature.svg)")
    args = ap.parse_args()

    roads = json.loads(args.roads.read_text(encoding="utf-8"))
    for r in roads:  # roads.json has length_m, the gallery code uses length
        r["length"] = r["length_m"]
    values = read_values(args)
    write_svg(roads, values, args.out)

    missing = [r["osm_id"] for r in roads if r["osm_id"] not in values]
    print(f"{len(roads)} roads, {len(roads) - len(missing)} with values from the database")
    if missing:
        print(f"not in the database: {missing}")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
