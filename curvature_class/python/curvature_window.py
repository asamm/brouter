#!/usr/bin/env python3
"""Runtime curvature of a link (window over arc length) on real BRouter links,
compared with the SQL method (M3, sql/functions.sql) as the reference.

Algorithm, parameters and results: docs/runtime-curvature-window.md
(where it hooks into BRouter: docs/runtime-curvature-turncost.md).

Motivation: the curvature for road motorcyclists can be computed at routing time instead
of a map-creation tag; a negative turncost code would switch StdPath from the per-vertex
turncost to a curvature factor c of the link. turncost itself cannot measure curvature
(1 - cos θ per vertex depends on how densely the road is drawn), and resampling the
geometry as the SQL functions do is too expensive at runtime. This script prototypes a
density-independent method on the data BRouter already has (dist and angle of each
section), checks it on real links exported from the engine and measures how much the
link boundaries cost against the SQL method, before anything is written in Java.

Input: GeoJSONSeq from LinkDump (one feature per link of the final track).

c = curvature factor of the whole link, 0.0 - 1.0 (= score / 2, score as in curv_bands:
sum over radius bands of share of length * weight, max. 2 = the whole link in hairpins).

Runtime method (what OsmPath / StdPath can do, only the data of the current link):
  1. inputs per section: dist[i] and the signed vertex angle[i], exactly as BRouter computes
     them (rc.calcDistance, CheapAngleMeter); angle[0] is the turn at the source node
     relative to the previous link. It is road shape at a link boundary unless it is a real
     turn: |angle[0]| > --junction-max (or a partial start) => ignored.
  2. each vertex angle is smeared over its surroundings: half of the neighbouring sections,
     at most --spread-cap m to each side; this gives the cumulative turning Theta(s), a
     piecewise linear function of the arc length s. Nothing is resampled, no new points.
  3. curvature at s = |Theta(s + W/2) - Theta(s - W/2)| / W (window clipped at the link
     ends), evaluated at the middle of every piece of a section (sections are cut into
     pieces <= W/2), the piece length goes to the radius band of R = 1 / curvature.
  4. score = sum(length in band * weight) / link length, c = score / 2.
     Links shorter than --min-len get no value (neutral, c = 0 at runtime).

Reference (map-creation view, no link boundaries): the SQL method on the whole track
as one line (resampling to --step m, circumradius through points i-k, i, i+k), each
radius point belongs to the link that contains it. Also the SQL method on each link
alone, to separate the effect of the link boundaries from the effect of the method.

Run (from curvature_class):
  python3 python/curvature_window.py real-links-export/real-links.geojsonl

Writes out/curvature_window.svg. Only the Python standard library is used.
"""

import argparse
import bisect
import math
from pathlib import Path

from analyze_real_links import OUT_DIR, esc, load

# radius bands and weights as in curv_bands (sql/functions.sql)
LIMITS = [30, 60, 100, 175]
WEIGHTS = [2, 1.6, 1.3, 1, 0]
# curv_class score thresholds, as c (= score / 2)
C_CLASSES = [0.05, 0.125, 0.225, 0.35, 0.5, 0.65]

INK = "#222"
MUTED = "#666"
GRID = "#e4e4e4"
NA = "#bbbbbb"
REF = "#2a78d6"   # categorical slot 1
RUN = "#eb6834"   # categorical slot 2
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def band_index(r):
    for i, lim in enumerate(LIMITS):
        if r < lim:
            return i
    return len(LIMITS)


def band_weight(r):
    return WEIGHTS[band_index(r)]


# ---------------------------------------------------------------- runtime method

def runtime_bands(p, window, junction_max, min_len, spread_cap=math.inf):
    """Length of the link in each radius band (index as in WEIGHTS), None for a short link.

    The measuring part of the runtime method, shared by every way of turning bands into c
    (runtime_c here, the variants in curvature_variants.py). Steps 1-3 of the module doc:
    junction angle, smearing into Theta(s), window W over Theta. In Java this is the loop
    over the sections of a link in OsmPath, on dist / angle it already computes.
    """
    dist = p["dist"]
    length = sum(dist)
    if length < min_len:
        return None
    ang = [math.radians(a) for a in p["angle"]]
    # step 1: angle[0] at the source node is road shape at a link boundary, kept;
    # a real turn (> junction_max) or the start of the route is not curvature
    if p["partial_start"] or p["origin_ilon"] == -1 or abs(p["angle"][0]) > junction_max:
        ang[0] = 0.0

    # cumulative turning Theta(s): the angle of vertex i rises linearly over
    # [s_i - left, s_i + right], left / right = half of the neighbouring section, capped
    # at spread_cap (inf = the whole dual interval); vertex 0 has nothing on its left here
    ks = [0.0]
    kt = [0.0]
    s = 0.0
    t = 0.0
    prev = 0.0
    for d, a in zip(dist, ang):
        left = min(prev / 2.0, spread_cap)
        right = min(d / 2.0, spread_cap)
        ks.append(s - left)
        kt.append(t)
        t += a
        ks.append(s + right)
        kt.append(t)
        s += d
        prev = d
    ks.append(length)
    kt.append(t)

    def theta(x):
        j = bisect.bisect_right(ks, x)
        if j >= len(ks):
            return kt[-1]
        x0, x1 = ks[j - 1], ks[j]
        return kt[j - 1] if x1 == x0 else kt[j - 1] + (kt[j] - kt[j - 1]) * (x - x0) / (x1 - x0)

    # step 3: net turning in the window centred in each piece (pieces <= W/2) gives
    # R = window length / turning; the piece length goes to the band of R
    half = window / 2.0
    bands = [0.0] * len(WEIGHTS)
    s = 0.0
    for d in dist:
        n = max(1, math.ceil(d / half))
        piece = d / n
        for q in range(n):
            x = s + (q + 0.5) * piece
            lo, hi = max(0.0, x - half), min(length, x + half)
            turn = abs(theta(hi) - theta(lo))
            r = math.inf if turn == 0 else (hi - lo) / turn
            bands[band_index(r)] += piece
        s += d
    return bands


def runtime_c(p, window, junction_max, min_len, spread_cap=math.inf):
    """c with the M3 weights (score / 2), the baseline; the chosen variant 2 is
    curvature_variants.c_variant2 (this c plus the serpentine rule)."""
    bands = runtime_bands(p, window, junction_max, min_len, spread_cap)
    if bands is None:
        return None
    return sum(b * w for b, w in zip(bands, WEIGHTS)) / sum(p["dist"]) / 2.0


# ---------------------------------------------------------------- SQL method (reference)

def to_xy(links):
    lat0 = links[0]["ilat"][0] / 1e6 - 90
    kx = 111320.0 * math.cos(math.radians(lat0)) / 1e6
    ky = 110540.0 / 1e6
    lon0 = links[0]["ilon"][0]
    ilat0 = links[0]["ilat"][0]
    return lambda lo, la: ((lo - lon0) * kx, (la - ilat0) * ky)


def resample(pts, step):
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    length = cum[-1]
    n = max(2, round(length / step))
    step_m = length / n
    out = []
    j = 0
    for i in range(n + 1):
        s = min(i * step_m, length)
        while j < len(cum) - 2 and cum[j + 1] < s:
            j += 1
        seg = cum[j + 1] - cum[j]
        f = 0.0 if seg == 0 else (s - cum[j]) / seg
        (x0, y0), (x1, y1) = pts[j], pts[j + 1]
        out.append((x0 + f * (x1 - x0), y0 + f * (y1 - y0), s))
    return out, step_m


def circumradius(p1, p2, p3):
    a = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    b = math.hypot(p3[0] - p2[0], p3[1] - p2[1])
    c = math.hypot(p3[0] - p1[0], p3[1] - p1[1])
    area2 = abs((p2[0] - p1[0]) * (p3[1] - p1[1]) - (p3[0] - p1[0]) * (p2[1] - p1[1]))
    if area2 == 0:
        return c / 2 if c < a + b - 1e-9 else math.inf  # 180 deg turn back / straight
    return a * b * c / (2 * area2)


def sql_radii(pts, step, k):
    rs, step_m = resample(pts, step)
    return [(rs[i][2], circumradius(rs[i - k], rs[i], rs[i + k])) for i in range(k, len(rs) - k)], step_m


def dedupe(pts):
    out = [pts[0]]
    for q in pts[1:]:
        if q != out[-1]:
            out.append(q)
    return out


def sql_c_link(pts, step, k, min_radii=5):
    pts = dedupe(pts)
    if len(pts) < 2:
        return None
    radii, _ = sql_radii(pts, step, k)
    if len(radii) < min_radii:
        return None
    return sum(band_weight(r) for _, r in radii) / len(radii) / 2.0


def sql_c_route(links, xy, step, k):
    """SQL method on the whole track, radius points assigned to links by arc length."""
    pts = []
    bounds = [0.0]
    for p in links:
        lp = [xy(lo, la) for lo, la in zip(p["ilon"], p["ilat"])]
        seg = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(lp, lp[1:]))
        bounds.append(bounds[-1] + seg)
        pts.extend(lp if not pts else lp[1:])
    radii, _ = sql_radii(dedupe(pts), step, k)
    sums = [0.0] * len(links)
    cnts = [0] * len(links)
    for s, r in radii:
        i = min(len(links) - 1, max(0, bisect.bisect_right(bounds, s) - 1))
        sums[i] += band_weight(r)
        cnts[i] += 1
    return [sums[i] / cnts[i] / 2.0 if cnts[i] else None for i in range(len(links))]


# ---------------------------------------------------------------- comparison

def corr(a, b):
    n = len(a)
    if n < 3:
        return float("nan")
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return float("nan")
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def compare(name, links, ref, val):
    pairs = [(r, v, p["length_m"]) for p, r, v in zip(links, ref, val) if r is not None and v is not None]
    if not pairs:
        print(f"  {name:28s} no values")
        return
    lw = sum(w for _, _, w in pairs)
    mae = sum(abs(r - v) * w for r, v, w in pairs) / lw
    covered = lw / sum(p["length_m"] for p in links)
    print(f"  {name:28s} links {len(pairs):3d}  length {100 * covered:5.1f} %  "
          f"corr {corr([r for r, _, _ in pairs], [v for _, v, _ in pairs]):5.2f}  "
          f"mean |diff| (length-weighted) {mae:.3f}")


def c_color(c):
    if c is None:
        return NA
    for i, lim in enumerate(C_CLASSES):
        if c < lim:
            return SEQ[i]
    return SEQ[-1]


def fmt(c):
    return "–" if c is None else f"{c:.2f}"


# ---------------------------------------------------------------- SVG

def write_svg(links, xy, ref, run, sql_link, args, path):
    pts = [[xy(lo, la) for lo, la in zip(p["ilon"], p["ilat"])] for p in links]
    xs = [x for ps in pts for x, _ in ps]
    ys = [y for ps in pts for _, y in ps]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = 40
    map_w = 560
    scale = map_w / max(maxx - minx, maxy - miny, 1)
    map_h = (maxy - miny) * scale
    W = 2 * map_w + 3 * pad
    out = [f'<text x="{pad}" y="26" font-size="16" font-weight="bold" fill="{INK}">'
           f'Curvature factor c per link (0 – 1): reference vs. runtime window</text>',
           f'<text x="{pad}" y="46" font-size="12" fill="{MUTED}">'
           f'window {args.window:g} m, junction max {args.junction_max:g}°, min. link length '
           f'{args.min_len:g} m; reference = SQL method on the whole track (step {args.step:g} m, '
           f'k = {args.k}); grey = no value</text>']

    def draw_map(ox, title, values):
        oy = 90
        res = [f'<text x="{ox}" y="{oy - 10}" font-size="13" font-weight="bold" fill="{INK}">{esc(title)}</text>']
        for p, ps, c in zip(links, pts, values):
            d = " ".join(f"{ox + (x - minx) * scale:.1f},{oy + (maxy - y) * scale:.1f}" for x, y in ps)
            tip = (f'link {p["seq"]}: {p["length_m"]} m, {p["n_points"]} points | reference {fmt(ref[p["seq"]])}, '
                   f'runtime {fmt(run[p["seq"]])}, SQL on link alone {fmt(sql_link[p["seq"]])} | {p["way_tags"]}')
            res.append(f'<polyline points="{d}" fill="none" stroke="{INK}" stroke-width="5.5" '
                       f'stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>')
            res.append(f'<polyline points="{d}" fill="none" stroke="{c_color(c)}" stroke-width="3.5" '
                       f'stroke-linejoin="round" stroke-linecap="round"><title>{esc(tip)}</title></polyline>')
        return res

    out += draw_map(pad, "Reference: SQL method on the whole track", ref)
    out += draw_map(2 * pad + map_w, "Runtime: window on each link alone", run)

    # legend of the colour classes
    ly = 90 + map_h + 30
    edges = [0] + C_CLASSES + [1]
    for i, col in enumerate(SEQ):
        lx = pad + i * 112
        out.append(f'<rect x="{lx}" y="{ly}" width="26" height="12" rx="2" fill="{col}" stroke="{INK}" stroke-opacity="0.3"/>')
        out.append(f'<text x="{lx + 32}" y="{ly + 11}" font-size="11" fill="{INK}">{edges[i]:g}–{edges[i + 1]:g}</text>')
    lx = pad + len(SEQ) * 112
    out.append(f'<rect x="{lx}" y="{ly}" width="26" height="12" rx="2" fill="{NA}"/>')
    out.append(f'<text x="{lx + 32}" y="{ly + 11}" font-size="11" fill="{INK}">no value</text>')

    # c along the route: step lines, one per method
    cy = ly + 70
    ch = 200
    cw = W - 2 * pad
    total = sum(p["length_m"] for p in links)
    cmax = max([v for v in ref + run if v is not None] + [0.1])
    cmax = math.ceil(cmax * 10) / 10
    out.append(f'<text x="{pad}" y="{cy - 28}" font-size="13" font-weight="bold" fill="{INK}">'
               f'c along the route (link by link)</text>')
    for g in range(0, int(round(cmax * 10)) + 1):
        v = g / 10
        y = cy + ch - ch * v / cmax
        out.append(f'<line x1="{pad}" y1="{y:.1f}" x2="{pad + cw}" y2="{y:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{pad - 6}" y="{y + 4:.1f}" font-size="10" text-anchor="end" fill="{MUTED}">{v:.1f}</text>')
    for km in range(0, int(total // 1000) + 1):
        x = pad + cw * km * 1000 / total
        out.append(f'<text x="{x:.1f}" y="{cy + ch + 16}" font-size="10" text-anchor="middle" fill="{MUTED}">{km} km</text>')

    # hover areas (one per link, under the lines), then one step line per method
    s = 0
    for p in links:
        x0 = pad + cw * s / total
        s += p["length_m"]
        out.append(f'<rect x="{x0:.1f}" y="{cy}" width="{max(cw * p["length_m"] / total, 1):.1f}" '
                   f'height="{ch}" fill="#fff" fill-opacity="0"><title>link {p["seq"]} ({p["length_m"]} m): '
                   f'reference {fmt(ref[p["seq"]])}, runtime {fmt(run[p["seq"]])}</title></rect>')

    def step_line(values, color):
        res = []
        s = 0
        for p, v in zip(links, values):
            x0 = pad + cw * s / total
            s += p["length_m"]
            x1 = pad + cw * s / total
            if v is None:
                continue
            y = cy + ch - ch * v / cmax
            res.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{color}" '
                       f'stroke-width="2" stroke-linecap="round"/>')
        return res

    out += step_line(ref, REF)
    out += step_line(run, RUN)
    # legend
    for i, (name, col) in enumerate([("reference (SQL, whole track)", REF), ("runtime (window, link alone)", RUN)]):
        lx = pad + 260 + i * 240
        out.append(f'<line x1="{lx}" y1="{cy - 32}" x2="{lx + 22}" y2="{cy - 32}" stroke="{col}" stroke-width="2.5"/>')
        out.append(f'<text x="{lx + 28}" y="{cy - 28}" font-size="11" fill="{INK}">{name}</text>')

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
                    help="max. distance a vertex angle is smeared to each side, inf = half section (default 10 m)")
    ap.add_argument("--step", type=float, default=10.0, help="SQL reference: resampling step (default 10 m)")
    ap.add_argument("--k", type=int, default=2, help="SQL reference: neighbour distance (default 2)")
    ap.add_argument("--svg", default=str(OUT_DIR / "curvature_window.svg"))
    args = ap.parse_args()

    links = load(args.input, args.track)
    for i, p in enumerate(links):
        p["seq"] = i
    xy = to_xy(links)
    ref = sql_c_route(links, xy, args.step, args.k)
    run = [runtime_c(p, args.window, args.junction_max, args.min_len, args.spread_cap) for p in links]
    sql_link = [sql_c_link([xy(lo, la) for lo, la in zip(p["ilon"], p["ilat"])], args.step, args.k) for p in links]

    print(f"{'seq':>4} {'len':>5} {'pts':>4}  {'ref':>5} {'run':>5} {'sqlL':>5}")
    for p, r, v, s in zip(links, ref, run, sql_link):
        print(f"{p['seq']:4d} {p['length_m']:5d} {p['n_points']:4d}  {fmt(r):>5} {fmt(v):>5} {fmt(s):>5}")
    print("\nagainst the reference (SQL method on the whole track):")
    compare("runtime window", links, ref, run)
    compare("SQL method on link alone", links, ref, sql_link)

    OUT_DIR.mkdir(exist_ok=True)
    write_svg(links, xy, ref, run, sql_link, args, Path(args.svg))
    print(f"\nwritten {args.svg}")


if __name__ == "__main__":
    main()
