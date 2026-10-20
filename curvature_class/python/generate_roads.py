#!/usr/bin/env python3
"""Generate randomized road linestrings with different curvature for the
table "lines" (see lines.sql).

Roads are built by a "turtle" in a local metric plane (x = east, y = north,
meters) from straight pieces and circular arcs. Each road is then placed on a
grid around --lat/--lon and converted to EPSG:3857.

Outputs (in --out-dir):
  lines_data.sql   INSERT statements for the table "lines" (run with psql)
  roads.svg        gallery of all roads for a quick visual check (open in a browser)
  roads.json       ground truth per road (type, pieces with radius/angle, length, turning)

Only the Python standard library is used.
"""

import argparse
import json
import math
import random
import statistics
from pathlib import Path

# curvature_class/out, independent of the current directory
OUT_DIR = Path(__file__).resolve().parent.parent / "out"

R_EARTH = 6378137.0  # sphere radius used by Web Mercator (EPSG:3857)
OSM_ID_BASE = 9_000_000_000  # far above real OSM way ids => no collision
NODE_ID_BASE = 9_100_000_000  # simulated node ids (lines.nodes)

# type -> highway, maxspeed, length range [m], color in svg
ROAD_TYPES = {
    "straight": {"highway": "motorway", "maxspeed": "130", "length": (30, 2000), "color": "#1f77b4"},
    "gentle": {"highway": "primary", "maxspeed": "90", "length": (300, 2000), "color": "#2ca02c"},
    "winding": {"highway": "secondary", "maxspeed": "70", "length": (100, 2000), "color": "#ff7f0e"},
    "mountain": {"highway": "tertiary", "maxspeed": "50", "length": (100, 2000), "color": "#9467bd"},
    "serpentine": {"highway": "secondary", "maxspeed": "30", "length": (300, 2000), "color": "#d62728"},
    "urban": {"highway": "residential", "maxspeed": "30", "length": (30, 800), "color": "#7f7f7f"},
}


# ---------------------------------------------------------------------------
# geometry building
# ---------------------------------------------------------------------------


class Turtle:
    """Walks in the local plane and records vertices until target length is reached.

    Idea ("turtle graphics", known from the Logo language): instead of computing
    coordinates directly, we steer an imaginary turtle that has a position (x, y)
    and a heading. Only two commands exist:

      straight(length)    go forward, heading unchanged
      arc(radius, angle)  drive a circular curve with given radius, turning by
                          angle degrees (+ = left, - = right)

    After each move the turtle drops a vertex into self.points. The resulting
    list of vertices is the road linestring, starting at (0, 0) in local meters.
    A road type is then just a recipe of commands, see build_*() functions, e.g.
    serpentine = (straight leg, hairpin arc 180 deg left, straight leg,
    hairpin arc 180 deg right, ...).

    How an arc is drawn (vertices exactly on the circle):

          turn dphi/2, move chord, turn dphi/2      (repeated "steps" times)

      The arc of angle A is split into steps with angle dphi = A / steps.
      The chord of one step has length 2 * R * sin(dphi / 2). Turning by
      dphi/2 before and after the chord is the same as following the tangent
      of the circle at both vertices, so every vertex lies on the circle and
      the heading after the arc is exactly heading + A.
      The number of steps follows OSM practice: vertex spacing ~ R / 4,
      limited to 3..20 m (tight hairpins get dense vertices, gentle curves sparse).

    Length and cutting:
      self.length counts the length of the polyline (sum of chords, slightly
      shorter than the true arc length R * A). When target length is reached,
      the current move is shortened and every further command does nothing
      (self.done). A road can therefore end in the middle of a curve; the
      really drawn part is what is recorded in self.pieces.

    Ground truth (self.pieces): every command that moved the turtle is stored
    as {"kind": "straight", "length"} or {"kind": "arc", "radius", "angle",
    "length"}, with the values really drawn (after cutting). It is written to
    roads.json, to validate curvature metrics later.

    Coordinates: x = east, y = north, heading in radians, 0 = east, growing
    counter-clockwise (like math.atan2). The initial heading is random, so
    roads point in all directions.

    rnd_first: the first straight is shortened by a random factor (0..1).
    Otherwise every short road would consist only of its first straight and
    e.g. a 100 m mountain road would never contain a curve.
    """

    def __init__(self, target_length, heading):
        self.x = 0.0
        self.y = 0.0
        self.heading = heading  # radians, 0 = east, counter-clockwise
        self.points = [(0.0, 0.0)]
        self.length = 0.0
        self.target = target_length
        self.pieces = []  # ground truth: what was really drawn
        self.rnd_first = 1.0  # set by generate(): fraction of the first straight

    @property
    def done(self):
        return self.length >= self.target - 1e-9

    def _move(self, dist):
        """Move forward, cut at target length. Returns the distance really moved."""
        dist = min(dist, self.target - self.length)
        if dist <= 0:
            return 0.0
        self.x += dist * math.cos(self.heading)
        self.y += dist * math.sin(self.heading)
        self.length += dist
        self.points.append((self.x, self.y))
        return dist

    def straight(self, length):
        if not self.points[1:]:  # first piece: random start position within the straight
            length *= self.rnd_first
        moved = self._move(length)
        if moved > 0:
            self.pieces.append({"kind": "straight", "length": round(moved, 2)})

    def arc(self, radius, angle_deg):
        """Circular arc, positive angle = left turn. Vertices every few meters
        (like OSM: denser on tight curves)."""
        angle = math.radians(angle_deg)
        arc_len = abs(angle) * radius
        node_spacing = max(3.0, min(20.0, radius * 0.25))
        steps = max(1, math.ceil(arc_len / node_spacing))
        dphi = angle / steps
        chord = 2 * radius * math.sin(abs(dphi) / 2)
        turned = 0.0
        moved_total = 0.0
        for _ in range(steps):
            if self.done:
                break
            # chord of an arc step: rotate half, move, rotate half
            self.heading += dphi / 2
            moved = self._move(chord)
            self.heading += dphi / 2
            if moved < chord:  # cut by target length: keep only the part really turned
                turned += dphi * moved / chord
                moved_total += moved
                break
            turned += dphi
            moved_total += moved
        if moved_total > 0:
            self.pieces.append(
                {"kind": "arc", "radius": round(radius, 2), "angle": round(math.degrees(turned), 2), "length": round(moved_total, 2)}
            )


def build_straight(t, rnd):
    t.straight(t.target)


def build_gentle(t, rnd):
    # long straights, large radius curves (trunk / primary road)
    while not t.done:
        t.straight(rnd.uniform(100, 400))
        t.arc(rnd.uniform(400, 1500), rnd.choice((-1, 1)) * rnd.uniform(5, 25))


def angle_diff(a, b):
    """a - b normalized to (-pi, pi]."""
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def steered_arc(t, rnd, base, radius, turn_deg, max_dev_deg):
    """Arc in a random direction, but the heading stays within +-max_dev_deg
    of the base direction => the road keeps going somewhere and does not
    make loops crossing itself."""
    dev = math.degrees(angle_diff(t.heading, base))
    if abs(dev) > max_dev_deg / 3:
        side = -1 if dev > 0 else 1  # turn back towards the base direction
    else:
        side = rnd.choice((-1, 1))
    room = max_dev_deg - side * dev  # how far we may turn to this side
    t.arc(radius, side * min(turn_deg, room))


def build_winding(t, rnd):
    # country road: shorter straights, medium curves in both directions
    base = t.heading
    while not t.done:
        t.straight(rnd.uniform(20, 150))
        steered_arc(t, rnd, base, rnd.uniform(60, 250), rnd.uniform(15, 70), 90)


def build_mountain(t, rnd):
    # tight curves, mostly alternating direction
    base = t.heading
    while not t.done:
        t.straight(rnd.uniform(5, 50))
        steered_arc(t, rnd, base, rnd.uniform(20, 70), rnd.uniform(40, 130), 120)


def build_serpentine(t, rnd):
    # Passo Stelvio style: nearly parallel legs connected by hairpins of ~180 deg.
    # The hairpin angle is computed from the real heading, so small bends in
    # the legs do not accumulate and the legs never cross each other.
    base = t.heading
    side = rnd.choice((-1, 1))
    up = True  # leg direction: base or base + 180
    while not t.done:
        leg = rnd.uniform(40, 160)
        t.straight(leg * 0.6)
        t.arc(rnd.uniform(300, 600), rnd.uniform(-3, 3))  # slight bend in the leg
        t.straight(leg * 0.4)
        up = not up
        # legs slightly fan out (open towards the outer side of the hairpin)
        target = base + (0 if up else math.pi) + math.radians(rnd.uniform(0, 3)) * side
        turn = (side * angle_diff(target, t.heading)) % (2 * math.pi)
        t.arc(rnd.uniform(7, 15), side * math.degrees(turn))
        side = -side


def build_urban(t, rnd):
    # streets with right-angle corners of small radius
    base = t.heading
    while not t.done:
        t.straight(rnd.uniform(30, 200))
        steered_arc(t, rnd, base, rnd.uniform(5, 12), rnd.uniform(80, 95), 120)


BUILDERS = {
    "straight": build_straight,
    "gentle": build_gentle,
    "winding": build_winding,
    "mountain": build_mountain,
    "serpentine": build_serpentine,
    "urban": build_urban,
}


def log_uniform(rnd, lo, hi):
    """More short roads than with plain uniform: tens of meters appear too."""
    return math.exp(rnd.uniform(math.log(lo), math.log(hi)))


def total_turning_deg(points):
    """Sum of absolute heading changes between consecutive segments."""
    total = 0.0
    for (x0, y0), (x1, y1), (x2, y2) in zip(points, points[1:], points[2:]):
        h1 = math.atan2(y1 - y0, x1 - x0)
        h2 = math.atan2(y2 - y1, x2 - x1)
        d = (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
        total += abs(d)
    return math.degrees(total)


# ---------------------------------------------------------------------------
# projection
# ---------------------------------------------------------------------------


def lonlat_to_3857(lon, lat):
    x = R_EARTH * math.radians(lon)
    y = R_EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def local_to_3857(points, lon0, lat0):
    """Local meters -> EPSG:3857. Real meters are multiplied by merca_coef
    (~ 1/cos(lat)), exactly the conversion brouter.sql does with ST_Buffer etc.
    Within 2 km the change of merca_coef with latitude is < 0.05 %, so one
    coefficient per road is enough."""
    x0, y0 = lonlat_to_3857(lon0, lat0)
    k = 1 / math.cos(math.radians(lat0))
    return [(x0 + dx * k, y0 + dy * k) for dx, dy in points], k


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------


def write_sql(roads, path):
    first_id = roads[0]["osm_id"]
    last_id = roads[-1]["osm_id"]
    out = [
        "--  generated by generate_roads.py -- simulated roads for the table \"lines\" (lines.sql)",
        "SET client_encoding TO UTF8;",
        "",
        "-- remove roads of a previous run (only the simulated id range)",
        f"DELETE FROM lines WHERE osm_id BETWEEN '{first_id}' AND '{last_id}' AND length(osm_id) = {len(str(first_id))};",
        "",
    ]
    for r in roads:
        wkt = "LINESTRING(" + ", ".join(f"{x:.2f} {y:.2f}" for x, y in r["points_3857"]) + ")"
        nodes = json.dumps(r["node_ids"])
        out.append(
            "INSERT INTO lines (osm_id, highway, way, oneway, nodes, maxspeed) VALUES "
            f"('{r['osm_id']}', '{r['highway']}', ST_GeomFromText('{wkt}', 3857), "
            f"{'NULL' if r['highway'] != 'motorway' else repr('yes')}, '{nodes}'::jsonb, '{r['maxspeed']}');"
        )
    out += [
        "",
        "-- the same expression as in brouter.sql",
        "UPDATE lines SET merca_coef = st_length (way) / st_length (ST_Transform (way, 4326)::geography)",
        f"WHERE osm_id BETWEEN '{first_id}' AND '{last_id}' AND length(osm_id) = {len(str(first_id))};",
        "",
        "ANALYZE lines;",
        "",
    ]
    path.write_text("\n".join(out), encoding="utf-8")


def nice_scale(max_m):
    """Largest 'nice' length not bigger than max_m (for the scale bar)."""
    for v in (1000, 500, 200, 100, 50, 20, 10, 5):
        if v <= max_m:
            return v
    return 5


def curviness(r):
    """Simple measure used only to order the gallery: total turning per km [deg/km]."""
    return r["turning_deg"] / (r["length"] / 1000)


def write_svg(roads, path, tile=230):
    """Gallery with one column per road type, the header names the type.
    Columns are ordered by median curviness of the type (straight on the left),
    within a column the roads are sorted by curviness (least curved on top)."""
    pad = 18
    label_h = 48
    header_h = 30
    columns = {}
    for r in roads:
        columns.setdefault(r["type"], []).append(r)
    order = sorted(columns, key=lambda t: statistics.median(curviness(r) for r in columns[t]))
    rows = max(len(c) for c in columns.values())
    width = len(order) * tile
    height = header_h + rows * (tile + label_h)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
    ]
    placed = []
    for col, rtype in enumerate(order):
        cfg = ROAD_TYPES[rtype]
        # column header
        hx = col * tile + 8
        parts.append(f'<rect x="{hx}" y="9" width="12" height="12" fill="{cfg["color"]}"/>')
        parts.append(f'<text x="{hx + 16}" y="19" font-weight="bold">{rtype} ({cfg["highway"]})</text>')
        for row, r in enumerate(sorted(columns[rtype], key=curviness)):
            placed.append((col, row, r))
    for col, row, r in placed:
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
        parts.append(f'<rect x="{ox + 2}" y="{oy + 2}" width="{tile - 4}" height="{tile + label_h - 4}" fill="none" stroke="#ddd"/>')
        parts.append(
            f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" '
            f'fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
        )
        for x, y in pts:  # vertices as in OSM
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1" fill="#333"/>')
        sx, sy = pts[0]
        ex, ey = pts[-1]
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="3.5" fill="#2ca02c"/>')
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" fill="#d62728"/>')
        # scale bar
        bar_m = nice_scale(span * 0.4)
        bar_px = bar_m * scale
        bx, by = ox + 10, oy + tile - 8
        parts.append(f'<line x1="{bx}" y1="{by}" x2="{bx + bar_px:.1f}" y2="{by}" stroke="black" stroke-width="2"/>')
        parts.append(f'<text x="{bx}" y="{by - 4}" font-size="9">{bar_m} m</text>')
        # labels
        parts.append(f'<text x="{ox + 8}" y="{oy + tile + 10}" font-weight="bold">{r["osm_id"]} {r["type"]}</text>')
        parts.append(f'<text x="{ox + 8}" y="{oy + tile + 24}">{r["length"]:.0f} m, {len(r["points_local"])} nodes</text>')
        parts.append(f'<text x="{ox + 8}" y="{oy + tile + 38}">turn {r["turning_deg"]:.0f}°, {curviness(r):.0f}°/km</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_json(roads, path):
    data = [
        {
            "osm_id": r["osm_id"],
            "type": r["type"],
            "highway": r["highway"],
            "length_m": round(r["length"], 2),
            "turning_deg": round(r["turning_deg"], 1),
            "node_count": len(r["points_local"]),
            "merca_coef_expected": round(r["merca_coef"], 6),
            "pieces": r["pieces"],
            "points_local": [[round(x, 2), round(y, 2)] for x, y in r["points_local"]],
        }
        for r in roads
    ]
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------


def generate(count, seed, lat, lon):
    rnd = random.Random(seed)
    types = list(ROAD_TYPES)
    cols = math.ceil(math.sqrt(count))
    roads = []
    node_id = NODE_ID_BASE
    for i in range(count):
        rtype = types[i % len(types)]  # balanced mix of types
        cfg = ROAD_TYPES[rtype]
        target = log_uniform(rnd, *cfg["length"])
        t = Turtle(target, heading=rnd.uniform(0, 2 * math.pi))
        if rtype != "straight":
            t.rnd_first = rnd.random()
        BUILDERS[rtype](t, rnd)
        # place each road in its own grid cell (~3 km apart, no overlaps)
        lat0 = lat + (i // cols) * 0.03
        lon0 = lon + (i % cols) * 0.045
        pts_3857, k = local_to_3857(t.points, lon0, lat0)
        node_ids = list(range(node_id, node_id + len(t.points)))
        node_id += len(t.points)
        roads.append(
            {
                "osm_id": OSM_ID_BASE + i,
                "type": rtype,
                "highway": cfg["highway"],
                "maxspeed": cfg["maxspeed"],
                "length": t.length,
                "turning_deg": total_turning_deg(t.points),
                "pieces": t.pieces,
                "points_local": t.points,
                "points_3857": pts_3857,
                "node_ids": node_ids,
                "merca_coef": k,
            }
        )
    return roads


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=60, help="number of roads (default 60)")
    ap.add_argument("--seed", type=int, default=1, help="random seed, same seed = same roads (default 1)")
    ap.add_argument("--lat", type=float, default=50.0, help="latitude of the first road (default 50.0)")
    ap.add_argument("--lon", type=float, default=15.0, help="longitude of the first road (default 15.0)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="output directory (default curvature_class/out)")
    args = ap.parse_args()

    roads = generate(args.count, args.seed, args.lat, args.lon)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_sql(roads, args.out_dir / "lines_data.sql")
    write_svg(roads, args.out_dir / "roads.svg")
    write_json(roads, args.out_dir / "roads.json")

    print(f"{'osm_id':>10}  {'type':<10} {'highway':<11} {'length':>7} {'turn':>6} {'nodes':>5}")
    for r in roads:
        print(
            f"{r['osm_id']:>10}  {r['type']:<10} {r['highway']:<11} {r['length']:>6.0f}m "
            f"{r['turning_deg']:>5.0f}° {len(r['points_local']):>5}"
        )
    print(f"\nwritten: {args.out_dir / 'lines_data.sql'}, {args.out_dir / 'roads.svg'}, {args.out_dir / 'roads.json'}")


if __name__ == "__main__":
    main()
