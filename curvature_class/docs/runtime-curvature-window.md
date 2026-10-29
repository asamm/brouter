# Runtime curvature of a link: window over arc length

The algorithm that computes the curvature factor `c` of one link at routing time, for the
variant described in `runtime-curvature-turncost.md` (curvature selected by a negative
`turncost` code, std model / `StdPath`; when it is active, the per-vertex turncost is not
computed at all). Prototype in Python: `python/curvature_window.py`, chosen variant
with the serpentine boost: `python/curvature_variants.py`.

Target users: road motorcyclists (roadsters, canyon chasers). The road motorcycle profile
will be built from scratch; the existing Enduro profiles (off-road) are not a reference.

## Goal

`c` is one number per link, **0.0 - 1.0**, with the same meaning as the map-creation
metric M3 (`metrics.md`, `sql/functions.sql`):

```
score = sum over radius bands (share of the link length in the band * weight)   0 .. 2
c     = score / 2
```

| band | R | weight |
|---|---|---|
| straight | > 175 m | 0 |
| gentle | 100-175 m | 1 |
| medium | 60-100 m | 1.3 |
| sharp | 30-60 m | 1.6 |
| hairpin | < 30 m | 2 |

`c` is used in the cost directly, with no extra strength parameter: the cost of the link is
multiplied by `(1 - c)` (decided 2026-10-22, details in "Integration into OsmPath /
StdPath"). The scale of `c` is therefore the strength itself: `c = 0.8` makes a link five
times cheaper.

## Why not turncost, why not resampling

- **turncost does not measure curvature.** The penalty per vertex is `(1 - cos θ) * turncost`,
  roughly `θ² / 2`, so it depends on how densely the road is drawn: a 90° bend costs 90 as
  one corner, 9 as nine 10° vertices and 0 as eighteen 5° vertices (below 7.6° per vertex
  the int cast gives 0 at turncost 90).
- **Quantities independent of the point density:** the length and the total (net) turning.
  Curvature = turning / length, radius = length / turning.
- **Resampling (as in SQL) is too expensive at runtime.** The algorithm must work on the
  points BRouter already has, in O(n), with the cheap arithmetic BRouter uses (no
  trigonometric function per point).

## Inputs (the same values `OsmPath.addAddionalPenalty` computes in its section loop)

Per section i of the link (point i -> i+1):

- `dist[i]`: section length in metres (the arithmetic of `rc.calcDistance`),
- `angle[i]`: signed turn angle at point i in degrees (`CheapAngleMeter.calcAngle`,
  polynomial, no `asin`). `angle[0]` is the turn at the source node relative to the last
  point of the previous link (`origin`).

Nothing else is needed: no tags. The implementation behind the hook gets the points of
the link and computes both itself ("Integration into the engine").

## Algorithm

1. **Junction angle.** `angle[0]` is usually road shape at a link boundary (links end at
   every junction, tagged node and map-cell border, also in the middle of a bend), not a
   turn: in the real export it is 18 % of all turning, with at most 4 real turns. It is
   ignored only when `|angle[0]| > 90°` (a real turn) or at the start of the route.
2. **Smearing.** The angle of vertex i is spread linearly over its surroundings: half of
   the neighbouring sections, at most 10 m to each side (vertex 0 has nothing on its left,
   the previous link is not part of this link). The result is the cumulative turning
   `Θ(s)`, a piecewise linear function of the arc length s. This is not resampling of the
   geometry: no new points, only a 1D function with two knots per vertex.
3. **Window.** Curvature at position s:
   `κ(s) = |Θ(s + W/2) - Θ(s - W/2)| / W`, W = 40 m (equivalent to the SQL radius through
   points i-2, i, i+2 with a 10 m step), the window clipped at the link ends.
   The signed sum cancels an S-bend inside the window, as the circumradius in SQL does,
   and suppresses zig-zag mapping noise.
4. **Bands.** κ is evaluated in the middle of every piece of a section (sections cut into
   pieces <= W/2); the piece length goes to the band of `R = 1/κ`.
   At runtime the division can be avoided: with a fixed W the band limits are fixed turning
   angles in the window (`θ = W / R`: 13.1°, 22.9°, 38.2°, 76.4° for 175, 100, 60, 30 m).
5. **Result.** `c = Σ(piece length * weight) / link length / 2`. Links shorter than
   40 m get no value (neutral, `c = 0`).

Complexity: O(n + L / (W/2)) per link expansion (n points, L link length); with two
pointers moving forward through `Θ`, no search. The same order as the existing section loop.

## Results on real links

Data: `real-links-export/real-links-krivoklatsko.geojsonl` (Křivoklátsko), exported by the temporary `LinkDump` from
the final track of a locally built BRouter (a separate development checkout with an
export hook added): 68 links, 16.7 km of `highway=secondary`. Statistics of the export:
`python/analyze_real_links.py` -> `out/real_links.svg`.

- Links: median 86 m, 53 % shorter than 90 m but only 10 % of the route length;
  links >= 200 m are 85 % of the length.
- Point spacing: median 28 m, a quarter of the sections longer than 54 m (sparser than
  the 10 m of the SQL resampling).

Reference: the SQL method ported to Python, on the whole track as one line (no link
boundaries, the view of a map-creation tag), radius points assigned to links.

| variant | corr. with reference | mean \|Δc\| (length-weighted) |
|---|---|---|
| window, each link alone (runtime) | 0.81 | 0.025 |
| - links >= 200 m | 0.98 | 0.018 |
| - links 40-200 m | 0.73 | 0.070 |
| window on the whole track (no link boundaries) | 0.96 | 0.019 |
| SQL method on each link alone | 0.90 (36 links) | 0.021 |

- The method itself matches SQL (0.96 without link boundaries). The loss to 0.81 is the
  **link boundary**: the angle at the target node belongs to the next link, which is not
  known yet, so a short link with a bend at its end does not see it.
- Tried without improvement: window 60 / 80 m (worse), junction limit 45° (filters real
  sharp corners at link boundaries), smearing over the whole half section (slightly
  worse), a causal window carried along the path (one float in `OsmPath`, like the turn
  accumulator of `KinematicPath`): corr. 0.80-0.83, lags behind by half a window.

## Serpentine boost (variant 2, chosen)

Visual check of `out/curvature_window.svg`: the track has several excellent sections with
sharp bends linked by curves, but the M3 weights give them at most `c = 0.5 - 0.56`. The
straights between the bends dilute the weighted mean. The target for such sections is
about `c = 0.8` (used directly as the factor `1 - c` on the cost, so a serpentine link
costs a fifth), with a steeper separation of straight roads from real serpentines.
Prototype: `python/curvature_variants.py` -> `out/curvature_variants.svg` (all variants),
`out/curvature_v2.svg` (variant 2 only, with the links in the rule space).

Two variants were compared, both on the same band lengths of the window method:

- **Variant 1, weights only** `{4, 3.2, 2, 0.5, 0}` (hairpin ... straight) / 2, clipped
  at 1. The weights must be higher than the normalisation 2: with 15-25 % straights in
  the best links, a maximum weight of 2 would need *higher* gentle weights to reach 0.8.
  Max. 0.79, but short links with a single corner rise as much (0.67-0.74): weights alone
  cannot tell a chain of bends from one corner.
- **Variant 2, M3 weights + serpentine rule** (the hairpin rule of `curv_class`,
  `sql/functions.sql`): if the link has a share **and** a length in tight curves above the
  thresholds, `c = max(c, 0.8)`.

| parameter | runtime | SQL hairpin rule | why different |
|---|---|---|---|
| tight curve | R < 60 m (hairpin + sharp) | R < 30 m | the 40 m window over points 28 m apart almost never gives R < 30 m, even in the sections felt as sharp serpentines |
| min. share | 20 % | 25 % | |
| min. length | 35 m | 100 m | applies to one link (median 86 m), not a whole way |
| result | `c >= 0.8` | class >= 5 | |

| | max | mean (length-weighted) | length with `c >= 0.6` |
|---|---|---|---|
| M3 weights | 0.56 | 0.13 | 0 % |
| variant 1 | 0.79 | 0.18 | 12.4 % |
| variant 2 | 0.80 | 0.18 | 13.8 % |

Variant 2 fires on exactly the 6 links of the serpentine sections (38-214 m, 23-33 % in
R < 60 m); short single-corner links keep their M3 value. The nearest miss is a junction
corner with 29 m / 22 %, the weakest hit has 38 m / 26 %: the margin is thin, check it
on more tracks.

**Decision (2026-10-22): variant 2.** The road motorcycle profile needs a steep boost of
serpentine sections (Stelvio and the Dolomite passes must come out very strongly); the
binary jump is intended. At runtime the rule costs nothing extra: the band lengths are
already there, it is two comparisons per link.

## Integration into the engine

The engine part is the generic hook `LinkCostModifier`, implemented on branch
`curvaturepr`: `link-cost-modifier-interface.md`. The curvature becomes an
implementation of it behind code `-10`; it is not written yet. Line numbers refer to
`brouter-core/src/main/java/btools/router/*.java` on `curvaturepr`.

### How c plugs in

```java
final class CurvatureLinkCostModifier implements LinkCostModifier {
  @Override
  public double linkCostFactor(int lon0, int lat0, OsmNode sourceNode, OsmTransferNode transferNodes, OsmNode targetNode) {
    // dist[], angle[] from the points, then bands() + M3 + serpentine rule, c <= 0.9
    return 1. - c;
  }
}
```

and in `RoutingContext.getLinkCostModifier` the code `-10` returns it instead of the
constant factor 1.

1. **Selection:** the profile sets `turncost = -10` (fixed or by tags). `StdPath` then
   skips the turn angle penalty (`StdPath.java:88-91`).
2. **Call:** once per link, before the section loop (`OsmPath.java:199-202`), with the
   point before the link and the whole geometry in the direction of travel.
3. **Inputs** (see "Inputs" above): the implementation computes `dist[]` and `angle[]`
   from the points `(lon0, lat0)`, `sourceNode`, the transfer nodes, `targetNode`. It must
   not use `rc.calcDistance` (side effects for waypoint matching and nogo areas,
   `RoutingContext.java:474-574`) nor `rc.anglemeter` (state of the routing context);
   the same arithmetic as `calcDistance` (`CheapRuler.getLonLatToMeterScales`, `sqrt`) and
   its own `CheapAngleMeter` give the same values as the loop. `lon0 == -1` means the
   start of the route (`isRouteStart`, `angle[0]` is ignored).
4. **Result:** `1 - c` multiplies every section cost of the link (`OsmPath.java:310-311`),
   i.e. the distance part with the slope-dependent costfactor, the elevation cost and
   the bike crossing penalties. Not initialcost, nogo, the target node cost: the same base
   as decided on 2026-10-22 (sum of the section costs), only applied per section.

The Kotlin port (`LinkCurvature.compute(dist, angle, isRouteStart)`) stays the core; a
front end builds the arrays from the geometry.

### Why one call before the loop after all

On 2026-10-22 a correction at the end of the link was chosen, to reuse `dist` and `angle`
of the section loop (and a pre-pass was rejected). On 2026-10-29 the interface was
changed to one call before the loop:

- the change in the engine is the smallest possible (one call, one multiplication),
  without special cases at the early `return` at the end waypoint or at the reset at the
  start waypoint,
- no buffers in the engine, the factor is known for every section.

The price, accepted:

- `dist` and `angle` are computed twice (about 2 `sqrt` and the `CheapAngleMeter`
  polynomial per section more, the same O(n));
- at a waypoint in the middle of a link the whole link is measured, not the used part.

### Buffers

The instances behind the codes are static and shared by all routing threads, so the
implementation must be thread safe; `RoutingContext` gets no new fields and `OsmPath` no
buffers (decided 2026-10-22, still holds).

| where | allocation | verdict |
|---|---|---|
| local arrays in `linkCostFactor` | a few small arrays per link expansion | simplest code, start with it |
| `ThreadLocal` inside the implementation, the object owns growable arrays | once per thread | if the allocation shows up in profiling |

The transfer node list belongs to the cache of `GeometryDecoder` and must not be kept
after the call.

### Properties

- **The cost never goes negative.** The factor `1 - c` is at least 0.1 (cap `c <= 0.9`),
  so every section cost stays positive; a negative factor would drop the link through
  the `sectionCost < 0` check (`OsmPath.java:312`).
- **c is capped at 0.9** (decided 2026-10-22, `Params.maxC` in `LinkCurvature.kt`), so a
  link costs at least a tenth. Without the cap, `c = 1` (a link entirely in the hairpin
  band) would make the link free: legal for the search (zero, not negative), but
  `cost == 0` also marks the start of a path (`isTrafficBackbone`, `OsmPath.java:151`)
  and a loop of free links would have no length penalty at all.
- **The strength is in the algorithm, not in the profile.** Changing it means changing
  the band weights or `serpC`, i.e. a new app version. Different strengths can be
  different codes (`-10` now, `-11` is taken by the test implementation).
- **The A\* search sees the discounted cost.** The factor is applied inside
  `addAddionalPenalty`, before the path is put into the queue.
- **Only the cost changes.** Time, energy and kinematics are not touched.
- **Rounding:** each section cost is cut to an `int` after the factor, so the loss is at
  most 1 per section (13 on 43 sections in `LinkCostModifierTest`).
- **Cost of the work:** one more pass over the geometry per link expansion with the
  distance and the angle per section, plus `bands()`, O(n + L / (W/2)); the geometric part
  of the link expansion gets roughly twice as expensive.
- **Messages (detail mode):** `costfactor` and `linkturncost` per section are without the
  factor, the cost of the track is with it. `c` itself is not in the messages; adding it
  would be a separate change.
- **Direction:** `angle[0]` and the one-sided smearing of vertex 0 depend on the direction
  of travel, so `c` of one link can differ a little between the two directions (and with
  `rc.inverseDirection`). The difference is small and acceptable.
- **Heuristic:** with the default `pass2coefficient = 0` (`RoutingContext.java:158`) the
  second pass is exact. A profile with `pass2coefficient > 0` assumes a minimum cost per
  metre; the discount lowers the real minimum to `(1 - c) * costfactor` (0.2 on
  serpentines, 0.1 at the cap), and that has to be taken into account when choosing it.

## Open questions

- Does `c` match the experience of riding the route? The SQL reference is another
  estimate, not the truth. Variant 2 matches the visual check of the sample track.
- Thresholds of the serpentine rule (20 % / 35 m) on more tracks, especially real
  alpine passes (Stelvio, Dolomites) and urban corners as false positives.
- A serpentine split into short links may miss the 35 m of the serpentine rule (the link
  boundary effect itself is accepted, decided 2026-10-22).
- New exports with the road motorcycle profile once it exists.
