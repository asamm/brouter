#!/usr/bin/env python3
"""Statistics and a picture of real BRouter links exported by LinkDump
(a local development build of BRouter, -Dbrouter.linkdump / BROUTER_LINKDUMP).

Input: GeoJSONSeq, one feature per link of the final track (see LinkDump.java).
Output:
  - statistics on stdout: link lengths (by count and by share of the route length),
    section lengths (spacing of the points), turn angles at the vertices,
  - out/real_links.svg: the track with link boundaries and the histograms.

Run (from curvature_class):
  python3 python/analyze_real_links.py real-links-export/real-links.geojsonl

Only the Python standard library is used.
"""

import argparse
import json
import math
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "out"

INK = "#222"
MUTED = "#666"
GRID = "#ddd"
LINK_A = "#2b7bba"
LINK_B = "#e6550d"
SHORT = "#d62728"

LINK_BINS = [0, 20, 40, 90, 200, 500, 1000, math.inf]  # 40 m = window, 90 m = min length in SQL
SECTION_BINS = [0, 5, 10, 20, 40, 80, 160, math.inf]
ANGLE_BINS = [0, 1, 2, 5, 10, 20, 45, 90, 180.01]


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load(path, track=None):
    links = []
    with open(path) as f:
        for line in f:
            if line.strip():
                links.append(json.loads(line)["properties"])
    tracks = []
    for p in links:
        if p["track"] not in tracks:
            tracks.append(p["track"])
    if track is None:
        track = tracks[0]
    if len(tracks) > 1:
        print(f"tracks in file: {tracks}, using {track}")
    return sorted((p for p in links if p["track"] == track), key=lambda p: p["seq"])


def bin_label(lo, hi, unit):
    if hi == math.inf:
        return f"≥ {lo:g} {unit}"
    return f"{lo:g}–{hi:g} {unit}"


def histogram(values, bins, weights=None):
    counts = [0.0] * (len(bins) - 1)
    for i, v in enumerate(values):
        for b in range(len(bins) - 1):
            if bins[b] <= v < bins[b + 1]:
                counts[b] += weights[i] if weights else 1
                break
    return counts


def quantiles(values):
    s = sorted(values)
    n = len(s)
    return {q: s[min(n - 1, int(q * n))] for q in (0.0, 0.25, 0.5, 0.75, 1.0)}


def print_stats(links):
    lengths = [p["length_m"] for p in links]
    total = sum(lengths)
    print(f"links: {len(links)}, route length: {total} m, "
          f"partial start/end: {sum(p['partial_start'] for p in links)}/{sum(p['partial_end'] for p in links)}")

    q = quantiles(lengths)
    print(f"link length [m]  min {q[0.0]}  p25 {q[0.25]}  median {q[0.5]}  p75 {q[0.75]}  max {q[1.0]}")
    print("\nlink length         links   share of links   share of route length")
    by_count = histogram(lengths, LINK_BINS)
    by_len = histogram(lengths, LINK_BINS, lengths)
    for b in range(len(LINK_BINS) - 1):
        print(f"  {bin_label(LINK_BINS[b], LINK_BINS[b + 1], 'm'):14s} {int(by_count[b]):6d}"
              f"   {100 * by_count[b] / len(links):9.1f} %   {100 * by_len[b] / total:12.1f} %")

    dists = [d for p in links for d in p["dist"]]
    q = quantiles(dists)
    print(f"\nsections: {len(dists)}, length [m]  min {q[0.0]}  p25 {q[0.25]}  median {q[0.5]}"
          f"  p75 {q[0.75]}  max {q[1.0]}")
    print("points per link: median", quantiles([p["n_points"] for p in links])[0.5],
          " max", max(p["n_points"] for p in links))

    # vertex angles inside links (angle[0] is the junction / start, not the shape of the road)
    inner = [abs(a) for p in links for a in p["angle"][1:]]
    junction = [abs(p["angle"][0]) for p in links if not p["partial_start"]]
    print(f"\nangles at inner vertices: {len(inner)}, at junctions: {len(junction)}")
    print("  |angle|        inner   junction")
    hi = histogram(inner, ANGLE_BINS)
    hj = histogram(junction, ANGLE_BINS)
    for b in range(len(ANGLE_BINS) - 1):
        print(f"  {bin_label(ANGLE_BINS[b], round(ANGLE_BINS[b + 1]), '°'):12s} {int(hi[b]):6d} {int(hj[b]):10d}")
    print(f"  total turning inside links {sum(inner):.0f}°, at junctions {sum(junction):.0f}°")


def local_xy(links):
    """Track points in metres (equirectangular around the first point)."""
    lon0 = links[0]["ilon"][0]
    lat0 = links[0]["ilat"][0]
    kx = 111320.0 * math.cos(math.radians(lat0 / 1e6 - 90)) / 1e6
    ky = 110540.0 / 1e6
    return lambda ilon, ilat: ((ilon - lon0) * kx, (ilat - lat0) * ky)


def svg_bars(x, y, w, h, title, labels, values, unit, color=LINK_A, mark=None):
    out = [f'<text x="{x}" y="{y - 22}" font-size="13" font-weight="bold" fill="{INK}">{esc(title)}</text>']
    vmax = max(values) or 1
    bw = w / len(values)
    for i, v in enumerate(values):
        bh = h * v / vmax
        c = mark(i) if mark else color
        out.append(f'<rect x="{x + i * bw + 2:.1f}" y="{y + h - bh:.1f}" width="{bw - 4:.1f}" '
                   f'height="{bh:.1f}" fill="{c}"/>')
        out.append(f'<text x="{x + i * bw + bw / 2:.1f}" y="{y + h - bh - 4:.1f}" font-size="11" '
                   f'text-anchor="middle" fill="{INK}">{v:.0f}{unit}</text>')
        out.append(f'<text x="{x + i * bw + bw / 2:.1f}" y="{y + h + 14:.1f}" font-size="10" '
                   f'text-anchor="middle" fill="{MUTED}">{esc(labels[i])}</text>')
    out.append(f'<line x1="{x}" y1="{y + h}" x2="{x + w}" y2="{y + h}" stroke="{GRID}"/>')
    return out


def write_svg(links, path):
    xy = local_xy(links)
    pts = [[xy(lo, la) for lo, la in zip(p["ilon"], p["ilat"])] for p in links]
    xs = [x for ps in pts for x, _ in ps]
    ys = [y for ps in pts for _, y in ps]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)

    map_w = 900
    scale = map_w / max(maxx - minx, maxy - miny, 1)
    map_h = (maxy - miny) * scale
    pad = 40
    W = map_w + 2 * pad

    def tx(x, y):
        return pad + (x - minx) * scale, pad + 30 + (maxy - y) * scale

    out = [f'<text x="{pad}" y="24" font-size="16" font-weight="bold" fill="{INK}">'
           f'Real BRouter links: {len(links)} links, {sum(p["length_m"] for p in links)} m '
           f'(colours alternate per link, red = link shorter than 40 m)</text>']
    for i, (p, ps) in enumerate(zip(links, pts)):
        color = SHORT if p["length_m"] < 40 else (LINK_A if i % 2 == 0 else LINK_B)
        d = " ".join(f"{a:.1f},{b:.1f}" for a, b in (tx(x, y) for x, y in ps))
        out.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="3" '
                   f'stroke-linejoin="round"><title>seq {p["seq"]}: {p["length_m"]} m, '
                   f'{p["n_points"]} points, {esc(p["way_tags"])}</title></polyline>')
        for x, y in ps[1:-1]:
            a, b = tx(x, y)
            out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="1.6" fill="{INK}"/>')
        a, b = tx(*ps[0])
        out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3.5" fill="white" stroke="{INK}"/>')
        if p["length_m"] >= 300:
            mx, my = tx(*ps[len(ps) // 2])
            out.append(f'<text x="{mx + 6:.1f}" y="{my - 6:.1f}" font-size="11" fill="{MUTED}">'
                       f'{p["seq"]}: {p["length_m"]} m</text>')
    # scale bar
    sb = 10 ** int(math.log10((maxx - minx) / 4 or 1))
    a, b = pad, pad + 30 + map_h + 20
    out.append(f'<line x1="{a}" y1="{b}" x2="{a + sb * scale:.1f}" y2="{b}" stroke="{INK}" stroke-width="2"/>')
    out.append(f'<text x="{a}" y="{b + 14}" font-size="11" fill="{INK}">{sb:g} m</text>')

    lengths = [p["length_m"] for p in links]
    total = sum(lengths)
    labels = [bin_label(LINK_BINS[b], LINK_BINS[b + 1], "") for b in range(len(LINK_BINS) - 1)]
    is_short = lambda i: SHORT if LINK_BINS[i + 1] <= 40 else LINK_A
    y0 = pad + 30 + map_h + 70
    hw = (W - 3 * pad) / 2
    out += svg_bars(pad, y0, hw, 140, "Links by length [m]: count", labels,
                    histogram(lengths, LINK_BINS), "", mark=is_short)
    out += svg_bars(2 * pad + hw, y0, hw, 140, "Links by length [m]: share of route length", labels,
                    [100 * v / total for v in histogram(lengths, LINK_BINS, lengths)], "%", mark=is_short)
    dists = [d for p in links for d in p["dist"]]
    y1 = y0 + 200
    out += svg_bars(pad, y1, hw, 140, "Sections (point spacing) [m]: count",
                    [bin_label(SECTION_BINS[b], SECTION_BINS[b + 1], "") for b in range(len(SECTION_BINS) - 1)],
                    histogram(dists, SECTION_BINS), "")
    inner = [abs(a) for p in links for a in p["angle"][1:]]
    out += svg_bars(2 * pad + hw, y1, hw, 140, "Turn angle at inner vertices [°]: count",
                    [bin_label(ANGLE_BINS[b], round(ANGLE_BINS[b + 1]), "") for b in range(len(ANGLE_BINS) - 1)],
                    histogram(inner, ANGLE_BINS), "")

    H = y1 + 180
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="sans-serif">',
           f'<rect width="100%" height="100%" fill="white"/>'] + out + ["</svg>"]
    path.write_text("\n".join(svg))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="GeoJSONSeq from LinkDump")
    ap.add_argument("--track", help="track id (default: the first one in the file)")
    ap.add_argument("--svg", default=str(OUT_DIR / "real_links.svg"))
    args = ap.parse_args()

    links = load(args.input, args.track)
    print_stats(links)
    OUT_DIR.mkdir(exist_ok=True)
    write_svg(links, Path(args.svg))
    print(f"\nwritten {args.svg}")


if __name__ == "__main__":
    main()
