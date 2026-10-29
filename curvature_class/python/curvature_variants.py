#!/usr/bin/env python3
"""Two variants of the runtime curvature factor c that separate straight roads from
serpentines more steeply than the M3 weights (python/curvature_window.py).

Motivation: on the sample track the best serpentine sections (sharp bends linked by
curves) reach only c = 0.5 - 0.56 with the M3 weights, the target is about 0.8.
The window method itself (docs/runtime-curvature-window.md) is unchanged, both variants
only turn the band lengths of a link into c differently.

  baseline   M3 weights {2, 1.6, 1.3, 1, 0} / 2.
  variant 1  only other weights for the same LIMITS: gentle curves count less, tight
             curves more; the weights are higher than the normalisation 2, so c is
             clipped at 1 (a link full of sharp curves saturates).
  variant 2  M3 weights plus a serpentine rule taken from the hairpin rule of curv_class
             (sql/functions.sql): share of tight curves >= --serp-share AND length in them
             >= --serp-min-m  =>  c is raised at least to --serp-c. Both conditions, as in
             SQL: a single corner (junction turn, a link with one vertex) has a high share
             but little length. Adapted to runtime: "tight" is R < 60 m (hairpin + sharp),
             not R < 30 m, because the 40 m window over points 28 m apart almost never
             gives R < 30 m on this track; the length limit is lower than the 100 m in SQL,
             because it applies to one link (median 86 m), not to a whole way.

Decision (2026-10-22): variant 2 is used further. The road motorcycle profile needs
a steep boost of serpentine sections (Stelvio and the Dolomite passes must come out very
strongly), the binary jump of the rule is intended. Variant 1 stays for comparison: weights
alone cannot tell a chain of bends from one corner, so short links with a single corner
(junction turns) rise as much as serpentines.

Pipeline of variant 2 for one link (what will be ported to OsmPath / StdPath):
  runtime_bands (curvature_window.py)  band lengths from dist / angle, window 40 m
  c_weights(bands, WEIGHTS)            c with the M3 weights, 0 - 1
  serpentine(bands, serp_r)            length and share of the link with R < serp_r
  c_variant2                           both thresholds met => c = max(c, serp_c)

Run (from curvature_class):
  python3 python/curvature_variants.py real-links-export/real-links.geojsonl

Writes out/curvature_variants.svg (all variants) and out/curvature_v2.svg (variant 2
only, with the rule space). Only the Python standard library is used.
"""

import argparse
import math
from pathlib import Path

from analyze_real_links import OUT_DIR, esc, load
from curvature_window import INK, LIMITS, MUTED, GRID, NA, SEQ, WEIGHTS, runtime_bands, to_xy

# variant 1: hairpin, sharp, medium, gentle, straight (same LIMITS)
WEIGHTS_V1 = [4, 3.2, 2, 0.5, 0]
# colour classes of c for this picture (the M3 classes end at 0.65)
C_EDGES = [0.05, 0.15, 0.3, 0.45, 0.6, 0.75]

BASE = "#9a9a9a"
V1 = "#eb6834"   # categorical slot 2
V2 = "#2a78d6"   # categorical slot 1


def c_weights(bands, weights, norm=2.0):
    """Length-weighted mean of the band weights / norm, clipped at 1 (M3: max weight = norm)."""
    return min(1.0, sum(b * w for b, w in zip(bands, weights)) / sum(bands) / norm)


def serpentine(bands, tight_limit):
    """Length and share of the link in the bands with R < tight_limit.

    The serpentine metric. It needs no extra pass: the band lengths are already there,
    tight_limit must be one of LIMITS (60 m = hairpin + sharp)."""
    n = sum(1 for lim in LIMITS if lim <= tight_limit)
    tight = sum(bands[:n])
    return tight, tight / sum(bands)


def c_variant2(bands, args):
    """Chosen variant: c with the M3 weights, raised to serp_c on a serpentine link.

    As the hairpin rule of curv_class (sql/functions.sql), both conditions are needed:
    the share separates serpentines from curvy roads with long gentle bends, the length
    separates them from a single corner (one junction turn has a high share, 9-29 m).
    The rule is binary on purpose (a floor, never lowers c): serpentines are what the
    road riders go for, they must stand out regardless of the straights between the
    hairpins, which dilute the weighted mean.
    On the sample track: fires on links with 38-214 m / 23-33 %, the nearest miss
    is a junction corner with 29 m / 22 % (thin margin, to be checked on more tracks)."""
    c = c_weights(bands, WEIGHTS)
    tight, share = serpentine(bands, args.serp_r)
    if share >= args.serp_share and tight >= args.serp_min_m:
        return max(c, args.serp_c), True
    return c, False


def c_color(c):
    if c is None:
        return NA
    for i, lim in enumerate(C_EDGES):
        if c < lim:
            return SEQ[i]
    return SEQ[-1]


def fmt(c):
    return "–" if c is None else f"{c:.2f}"


# ---------------------------------------------------------------- SVG

def write_svg(links, xy, rows, args, path):
    pts = [[xy(lo, la) for lo, la in zip(p["ilon"], p["ilat"])] for p in links]
    xs = [x for ps in pts for x, _ in ps]
    ys = [y for ps in pts for _, y in ps]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = 40
    map_w = 420
    scale = map_w / max(maxx - minx, maxy - miny, 1)
    map_h = (maxy - miny) * scale
    W = 3 * map_w + 4 * pad
    wv1 = ", ".join(f"{w:g}" for w in WEIGHTS_V1)
    out = [f'<text x="{pad}" y="26" font-size="16" font-weight="bold" fill="{INK}">'
           f'Curvature factor c per link (0 – 1): M3 weights vs. two variants with a steeper separation</text>',
           f'<text x="{pad}" y="46" font-size="12" fill="{MUTED}">'
           f'runtime window {args.window:g} m on each link alone, links &lt; {args.min_len:g} m grey; '
           f'variant 1: weights {{{wv1}}} / 2, clipped at 1; variant 2: M3 weights, '
           f'R &lt; {args.serp_r:g} m ≥ {100 * args.serp_share:g} % and ≥ {args.serp_min_m:g} m '
           f'⇒ c ≥ {args.serp_c:g} (orange halo)</text>']

    def draw_map(ox, title, key):
        oy = 92
        res = [f'<text x="{ox}" y="{oy - 12}" font-size="13" font-weight="bold" fill="{INK}">{esc(title)}</text>']
        for p, ps, r in zip(links, pts, rows):
            d = " ".join(f"{ox + (x - minx) * scale:.1f},{oy + (maxy - y) * scale:.1f}" for x, y in ps)
            tip = (f'link {p["seq"]}: {p["length_m"]} m, {p["n_points"]} points | M3 {fmt(r["base"])}, '
                   f'variant 1 {fmt(r["v1"])}, variant 2 {fmt(r["v2"])}'
                   + (f' | R &lt; {args.serp_r:g} m: {r["tight"]:.0f} m, {100 * r["share"]:.0f} %'
                      if r["bands"] else ""))
            if key == "v2" and r["serp"]:
                res.append(f'<polyline points="{d}" fill="none" stroke="{V1}" stroke-width="13" '
                           f'stroke-linejoin="round" stroke-linecap="round" opacity="0.45"/>')
            res.append(f'<polyline points="{d}" fill="none" stroke="{INK}" stroke-width="5.5" '
                       f'stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>')
            res.append(f'<polyline points="{d}" fill="none" stroke="{c_color(r[key])}" stroke-width="3.5" '
                       f'stroke-linejoin="round" stroke-linecap="round"><title>{tip}</title></polyline>')
        return res

    out += draw_map(pad, "M3 weights (current)", "base")
    out += draw_map(2 * pad + map_w, "Variant 1: weights only", "v1")
    out += draw_map(3 * pad + 2 * map_w, "Variant 2: M3 + serpentine rule", "v2")

    # legend of the colour classes
    ly = 92 + map_h + 30
    edges = [0] + C_EDGES + [1]
    for i, col in enumerate(SEQ):
        lx = pad + i * 112
        out.append(f'<rect x="{lx}" y="{ly}" width="26" height="12" rx="2" fill="{col}" stroke="{INK}" stroke-opacity="0.3"/>')
        out.append(f'<text x="{lx + 32}" y="{ly + 11}" font-size="11" fill="{INK}">{edges[i]:g}–{edges[i + 1]:g}</text>')
    lx = pad + len(SEQ) * 112
    out.append(f'<rect x="{lx}" y="{ly}" width="26" height="12" rx="2" fill="{NA}"/>')
    out.append(f'<text x="{lx + 32}" y="{ly + 11}" font-size="11" fill="{INK}">no value</text>')

    # c along the route: one step line per variant
    cy = ly + 76
    ch = 240
    cw = W - 2 * pad
    total = sum(p["length_m"] for p in links)
    out.append(f'<text x="{pad}" y="{cy - 30}" font-size="13" font-weight="bold" fill="{INK}">'
               f'c along the route (link by link)</text>')
    for g in range(0, 11):
        v = g / 10
        y = cy + ch - ch * v
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{pad + cw}" y2="{y:.1f}" stroke="{GRID}"/>')
        if g % 2 == 0:
            out.append(f'<text x="{pad - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">{v:.1f}</text>')
    y8 = cy + ch - ch * 0.8
    out.append(f'<line x1="{pad}" y1="{y8:.1f}" x2="{pad + cw}" y2="{y8:.1f}" stroke="{INK}" '
               f'stroke-dasharray="4 4" stroke-opacity="0.5"/>')
    out.append(f'<text x="{pad + cw}" y="{y8 - 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">target 0.8</text>')
    for km in range(0, int(total // 1000) + 1, 1 if total < 20000 else 2):
        x = pad + cw * km * 1000 / total
        out.append(f'<text x="{x:.1f}" y="{cy + ch + 16}" font-size="10" text-anchor="middle" fill="{MUTED}">{km} km</text>')

    s = 0
    for p, r in zip(links, rows):
        x0 = pad + cw * s / total
        s += p["length_m"]
        out.append(f'<rect x="{x0:.1f}" y="{cy}" width="{max(cw * p["length_m"] / total, 1):.1f}" '
                   f'height="{ch}" fill="#fff" fill-opacity="0"><title>link {p["seq"]} ({p["length_m"]} m): '
                   f'M3 {fmt(r["base"])}, variant 1 {fmt(r["v1"])}, variant 2 {fmt(r["v2"])}</title></rect>')

    def step_line(key, color, width):
        res = []
        s = 0
        for p, r in zip(links, rows):
            x0 = pad + cw * s / total
            s += p["length_m"]
            x1 = pad + cw * s / total
            if r[key] is None:
                continue
            y = cy + ch - ch * r[key]
            res.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{color}" '
                       f'stroke-width="{width}" stroke-linecap="round"/>')
        return res

    out += step_line("v2", V2, 4)
    out += step_line("v1", V1, 2)
    out += step_line("base", BASE, 1.5)
    for i, (name, col) in enumerate([("M3 weights", BASE), ("variant 1: weights", V1),
                                     ("variant 2: serpentine rule", V2)]):
        lx = pad + 260 + i * 200
        out.append(f'<line x1="{lx}" y1="{cy - 34}" x2="{lx + 22}" y2="{cy - 34}" stroke="{col}" stroke-width="2.5"/>')
        out.append(f'<text x="{lx + 28}" y="{cy - 30}" font-size="11" fill="{INK}">{name}</text>')

    H = cy + ch + 40
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="sans-serif">',
           '<rect width="100%" height="100%" fill="white"/>'] + out + ["</svg>"]
    path.write_text("\n".join(svg))


def write_svg_v2(links, xy, rows, args, path):
    """Variant 2 only: map of c, the rule space (length / share in tight curves) with the
    thresholds, and c along the route."""
    pts = [[xy(lo, la) for lo, la in zip(p["ilon"], p["ilat"])] for p in links]
    xs = [x for ps in pts for x, _ in ps]
    ys = [y for ps in pts for _, y in ps]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = 40
    map_w = 640
    scale = map_w / max(maxx - minx, maxy - miny, 1)
    map_h = (maxy - miny) * scale
    sc_w = 520
    W = map_w + sc_w + 3 * pad + 30
    out = [f'<text x="{pad}" y="26" font-size="16" font-weight="bold" fill="{INK}">'
           f'Curvature factor c per link (0 – 1), variant 2: M3 weights + serpentine rule</text>',
           f'<text x="{pad}" y="46" font-size="12" fill="{MUTED}">'
           f'runtime window {args.window:g} m on each link alone, links &lt; {args.min_len:g} m grey; '
           f'serpentine (orange): R &lt; {args.serp_r:g} m ≥ {100 * args.serp_share:g} % of the link '
           f'and ≥ {args.serp_min_m:g} m ⇒ c ≥ {args.serp_c:g}</text>']

    def tip(p, r):
        t = f'link {p["seq"]}: {p["length_m"]} m, {p["n_points"]} points | c {fmt(r["v2"])} (M3 {fmt(r["base"])})'
        if r["bands"]:
            t += f' | R &lt; {args.serp_r:g} m: {r["tight"]:.0f} m, {100 * r["share"]:.0f} %'
        return t + (" | serpentine" if r["serp"] else "")

    # map
    oy = 92
    out.append(f'<text x="{pad}" y="{oy - 12}" font-size="13" font-weight="bold" fill="{INK}">Map</text>')
    for p, ps, r in zip(links, pts, rows):
        d = " ".join(f"{pad + (x - minx) * scale:.1f},{oy + (maxy - y) * scale:.1f}" for x, y in ps)
        if r["serp"]:
            out.append(f'<polyline points="{d}" fill="none" stroke="{V1}" stroke-width="15" '
                       f'stroke-linejoin="round" stroke-linecap="round" opacity="0.45"/>')
        out.append(f'<polyline points="{d}" fill="none" stroke="{INK}" stroke-width="6.5" '
                   f'stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>')
        out.append(f'<polyline points="{d}" fill="none" stroke="{c_color(r["v2"])}" stroke-width="4.5" '
                   f'stroke-linejoin="round" stroke-linecap="round"><title>{tip(p, r)}</title></polyline>')
    ly = oy + map_h + 24
    edges = [0] + C_EDGES + [1]
    for i, col in enumerate(SEQ):
        lx = pad + (i % 4) * 150
        y = ly + (i // 4) * 20
        out.append(f'<rect x="{lx}" y="{y}" width="26" height="12" rx="2" fill="{col}" stroke="{INK}" stroke-opacity="0.3"/>')
        out.append(f'<text x="{lx + 32}" y="{y + 11}" font-size="11" fill="{INK}">{edges[i]:g}–{edges[i + 1]:g}</text>')
    out.append(f'<rect x="{pad + 3 * 150}" y="{ly + 20}" width="26" height="12" rx="2" fill="{NA}"/>')
    out.append(f'<text x="{pad + 3 * 150 + 32}" y="{ly + 31}" font-size="11" fill="{INK}">no value</text>')

    # rule space: every link with a value, x = length in tight curves, y = share
    sx0 = 2 * pad + map_w + 30
    sy0 = oy
    sh = 360
    vals = [r for r in rows if r["bands"]]
    xmax = max(50, math.ceil(max(r["tight"] for r in vals) / 50) * 50)
    ymax = max(0.4, math.ceil(max(r["share"] for r in vals) * 10) / 10)

    def X(v):
        return sx0 + sc_w * v / xmax

    def Y(v):
        return sy0 + sh - sh * v / ymax

    out.append(f'<text x="{sx0 - 30}" y="{sy0 - 12}" font-size="13" font-weight="bold" fill="{INK}">'
               f'Serpentine rule: links in the rule space</text>')
    out.append(f'<rect x="{X(args.serp_min_m):.1f}" y="{Y(ymax):.1f}" width="{X(xmax) - X(args.serp_min_m):.1f}" '
               f'height="{Y(args.serp_share) - Y(ymax):.1f}" fill="{V1}" fill-opacity="0.1"/>')
    for g in range(0, int(round(ymax * 10)) + 1):
        y = Y(g / 10)
        out.append(f'<line x1="{sx0}" y1="{y:.1f}" x2="{sx0 + sc_w}" y2="{y:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{sx0 - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">{10 * g} %</text>')
    for v in range(0, int(xmax) + 1, 50):
        out.append(f'<text x="{X(v):.1f}" y="{sy0 + sh + 16}" font-size="10" text-anchor="middle" fill="{MUTED}">{v} m</text>')
    out.append(f'<line x1="{X(args.serp_min_m):.1f}" y1="{sy0}" x2="{X(args.serp_min_m):.1f}" y2="{sy0 + sh}" '
               f'stroke="{V1}" stroke-dasharray="4 3"/>')
    out.append(f'<line x1="{sx0}" y1="{Y(args.serp_share):.1f}" x2="{sx0 + sc_w}" y2="{Y(args.serp_share):.1f}" '
               f'stroke="{V1}" stroke-dasharray="4 3"/>')
    out.append(f'<text x="{X(args.serp_min_m) + 4:.1f}" y="{sy0 + 12}" font-size="10" fill="{V1}">≥ {args.serp_min_m:g} m</text>')
    out.append(f'<text x="{sx0 + sc_w - 4}" y="{Y(args.serp_share) - 5:.1f}" font-size="10" text-anchor="end" '
               f'fill="{V1}">≥ {100 * args.serp_share:g} %</text>')
    out.append(f'<text x="{sx0 + sc_w - 4}" y="{Y(ymax) + 14:.1f}" font-size="11" text-anchor="end" '
               f'fill="{INK}">serpentine ⇒ c ≥ {args.serp_c:g}</text>')
    out.append(f'<text x="{sx0 + sc_w / 2}" y="{sy0 + sh + 34}" font-size="11" text-anchor="middle" fill="{INK}">'
               f'length of the link with R &lt; {args.serp_r:g} m</text>')
    out.append(f'<text x="{sx0 - 40}" y="{sy0 + sh / 2}" font-size="11" text-anchor="middle" fill="{INK}" '
               f'transform="rotate(-90 {sx0 - 40} {sy0 + sh / 2})">share of the link</text>')
    for p, r in zip(links, rows):
        if not r["bands"] or (r["tight"] == 0 and not r["serp"]):
            continue
        cx, cy_ = X(r["tight"]), Y(r["share"])
        col = V1 if r["serp"] else BASE
        out.append(f'<circle cx="{cx:.1f}" cy="{cy_:.1f}" r="5" fill="{col}" stroke="white" stroke-width="1.5">'
                   f'<title>{tip(p, r)}</title></circle>')
        out.append(f'<text x="{cx + 7:.1f}" y="{cy_ + 4:.1f}" font-size="10" fill="{MUTED}">{p["seq"]}</text>')
    n_zero = sum(1 for r in vals if r["tight"] == 0)
    out.append(f'<text x="{sx0}" y="{sy0 + sh + 52}" font-size="11" fill="{MUTED}">'
               f'{n_zero} links with no tight curve not shown; labels = link number</text>')

    # c along the route
    cy = max(ly + 60, sy0 + sh + 70) + 40
    ch = 220
    cw = W - 2 * pad
    total = sum(p["length_m"] for p in links)
    out.append(f'<text x="{pad}" y="{cy - 20}" font-size="13" font-weight="bold" fill="{INK}">'
               f'c along the route (link by link), orange = serpentine</text>')
    for g in range(0, 11):
        y = cy + ch - ch * g / 10
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{pad + cw}" y2="{y:.1f}" stroke="{GRID}"/>')
        if g % 2 == 0:
            out.append(f'<text x="{pad - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">{g / 10:.1f}</text>')
    for km in range(0, int(total // 1000) + 1, 1 if total < 20000 else 2):
        x = pad + cw * km * 1000 / total
        out.append(f'<text x="{x:.1f}" y="{cy + ch + 16}" font-size="10" text-anchor="middle" fill="{MUTED}">{km} km</text>')
    s = 0
    for p, r in zip(links, rows):
        x0 = pad + cw * s / total
        s += p["length_m"]
        x1 = pad + cw * s / total
        out.append(f'<rect x="{x0:.1f}" y="{cy}" width="{max(x1 - x0, 1):.1f}" height="{ch}" fill="#fff" '
                   f'fill-opacity="0"><title>{tip(p, r)}</title></rect>')
        if r["v2"] is None:
            continue
        y = cy + ch - ch * r["v2"]
        if r["serp"]:
            out.append(f'<rect x="{x0:.1f}" y="{y:.1f}" width="{max(x1 - x0, 1):.1f}" height="{cy + ch - y:.1f}" '
                       f'fill="{V1}" fill-opacity="0.15"/>')
        out.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" '
                   f'stroke="{V1 if r["serp"] else V2}" stroke-width="{4 if r["serp"] else 2.5}" '
                   f'stroke-linecap="round" pointer-events="none"/>')

    H = cy + ch + 40
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="sans-serif">',
           '<rect width="100%" height="100%" fill="white"/>'] + out + ["</svg>"]
    path.write_text("\n".join(svg))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="GeoJSONSeq from LinkDump")
    ap.add_argument("--track", help="track id (default: the first one in the file)")
    ap.add_argument("--window", type=float, default=40.0, help="window length in m (default 40)")
    ap.add_argument("--junction-max", type=float, default=90.0,
                    help="|angle[0]| above this is a real turn, ignored (default 90 deg)")
    ap.add_argument("--min-len", type=float, default=40.0, help="shorter links get no value (default 40 m)")
    ap.add_argument("--spread-cap", type=float, default=10.0,
                    help="max. distance a vertex angle is smeared to each side (default 10 m)")
    ap.add_argument("--serp-r", type=float, default=60.0,
                    help="variant 2: tight curve = R below this, a band limit (default 60 m)")
    ap.add_argument("--serp-share", type=float, default=0.2,
                    help="variant 2: min. share of the link in tight curves (default 0.2)")
    ap.add_argument("--serp-min-m", type=float, default=35.0,
                    help="variant 2: min. length of the link in tight curves (default 35 m)")
    ap.add_argument("--serp-c", type=float, default=0.8, help="variant 2: c is raised at least to this (default 0.8)")
    ap.add_argument("--svg", default=str(OUT_DIR / "curvature_variants.svg"))
    ap.add_argument("--svg-v2", default=str(OUT_DIR / "curvature_v2.svg"), help="picture of variant 2 only")
    args = ap.parse_args()
    if args.serp_r not in LIMITS:
        ap.error(f"--serp-r must be one of the band limits {LIMITS}")

    links = load(args.input, args.track)
    for i, p in enumerate(links):
        p["seq"] = i
    rows = []
    for p in links:
        b = runtime_bands(p, args.window, args.junction_max, args.min_len, args.spread_cap)
        r = {"bands": b, "base": None, "v1": None, "v2": None, "serp": False, "tight": 0.0, "share": 0.0}
        if b:
            r["base"] = c_weights(b, WEIGHTS)
            r["v1"] = c_weights(b, WEIGHTS_V1)
            r["v2"], r["serp"] = c_variant2(b, args)
            r["tight"], r["share"] = serpentine(b, args.serp_r)
        rows.append(r)

    print(f"{'seq':>4} {'len':>5}  {'M3':>5} {'v1':>5} {'v2':>5}  tight R<{args.serp_r:g}")
    for p, r in zip(links, rows):
        if r["bands"] is None:
            continue
        mark = "  serpentine" if r["serp"] else ""
        print(f"{p['seq']:4d} {p['length_m']:5d}  {fmt(r['base']):>5} {fmt(r['v1']):>5} {fmt(r['v2']):>5}  "
              f"{r['tight']:4.0f} m {100 * r['share']:3.0f} %{mark}")
    total = sum(p["length_m"] for p, r in zip(links, rows) if r["bands"])
    print()
    for key, name in (("base", "M3 weights"), ("v1", "variant 1"), ("v2", "variant 2")):
        vals = [(r[key], p["length_m"]) for p, r in zip(links, rows) if r[key] is not None]
        mean = sum(c * L for c, L in vals) / total
        hi = sum(L for c, L in vals if c >= 0.6) / total
        print(f"  {name:11s} max {max(c for c, _ in vals):.2f}  mean (length-weighted) {mean:.2f}  "
              f"length with c >= 0.6: {100 * hi:4.1f} %")

    OUT_DIR.mkdir(exist_ok=True)
    write_svg(links, xy=to_xy(links), rows=rows, args=args, path=Path(args.svg))
    write_svg_v2(links, xy=to_xy(links), rows=rows, args=args, path=Path(args.svg_v2))
    print(f"\nwritten {args.svg}, {args.svg_v2}")


if __name__ == "__main__":
    main()
