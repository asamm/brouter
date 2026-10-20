# Variant: curvature computed at routing time, selected by a negative turncost

Design note, nothing is implemented. An alternative to the map-creation tag
`estimated_curvature_class` (see `metrics.md`): the curvature of a link is computed
while routing, from the link geometry that BRouter already decodes, and a negative
`turncost` value in the profile selects the algorithm.

Line numbers refer to the files as they are in this repository
(`brouter-core/src/main/java/btools/router/OsmPath.java`, `StdPath.java`,
`brouter-mapaccess/src/main/java/btools/mapaccess/*`).

## Idea

Today `turncost` is a penalty per vertex, `(int) ((1 - cosangle) * turncost + 0.2)`
(`StdPath.java:89`). That works as intended for positive values: it penalizes sharp turns
and barely touches smooth curves. Negative values do not work as a bonus for curvy roads:
the effect depends on the vertex angles rather than on curvature, and a short section after
a turn makes `sectionCost < 0`, which drops the whole link (`OsmPath.java:306`). See the
results in `jvm/src/test/kotlin/btools/router/RoadCostTest.kt`.

The variant keeps the current behaviour for `turncost >= 0` and gives negative values a
new meaning: **a code that switches the implementation**. Instead of the per-vertex formula,
a separate algorithm computes one value in the range **0.0 - 1.0** over the whole link
geometry, for example:

| profile value     | meaning |
|-------------------|---------|
| `turncost >= 0`   | current per-vertex penalty, unchanged |
| `turncost = -11`  | curvature of the link, algorithm tuned for road bikes |
| `turncost = -12`  | curvature of the link, a slightly different algorithm for adventure bikes |
| other negative    | reserved |

The code can be chosen per way in the profile, because `turncost` is an ordinary
expression evaluated per link:

```
assign turncost = if junction=roundabout then 0
                  else if ismainroad then 90
                  else -11
```

No profile in this repository (`misc/profiles2`, `locus-routing-profiles`) uses a negative
`turncost` today, so the change of meaning does not break existing profiles here.

## What is available at runtime

### The link

A link (`OsmLink`) is an edge between two network nodes (`OsmNode`). One object serves
both directions; the direction follows from the node you come from
(`getTarget(source)`, `isReverse(source)`). It carries:

- `descriptionBitmap`: way tags, the same for both directions,
- `geometry`: the intermediate points (transfer nodes) as a `byte[]`, delta-encoded
  (`Δilon, Δilat, Δselev` per point, relative to the previous point), `null` when there
  are none. Stored for the forward direction only (`OsmNode.java:186-189`).

### The whole geometry of the link, in one place

In `OsmPath.addAddionalPenalty` the geometry is decoded once, before the section loop
(`OsmPath.java:196-197`):

```java
OsmTransferNode transferNode = link.geometry == null ? null
  : rc.geometryDecoder.decodeGeometry(link.geometry, sourceNode, targetNode, isReverse);
```

- `GeometryDecoder.decodeGeometry` decodes the whole `byte[]` at once and returns the head
  of a singly linked list of `OsmTransferNode` (`ilon`, `ilat`, `selev`, `next`).
- The list is already in the direction of travel (for a reverse link it is built backwards).
- The full point sequence is: `sourceNode`, then `transferNode -> .next -> ... -> null`,
  then `targetNode`.
- The section loop (`OsmPath.java:199`) only moves a local variable along the list and
  does not change it. A pre-pass over the list before the loop is therefore possible
  without touching the loop.

The way tags are evaluated just before that (`rc.expctxWay.evaluate(...)`,
`OsmPath.java:142`), so `rc.expctxWay.getTurncost()` is already known at that point and
can select the algorithm.

## Where it would hook in

1. **`OsmPath.addAddionalPenalty`, after `OsmPath.java:196-197`:** if `turncost <= -11`,
   walk the transfer node list once (plus `sourceNode` and `targetNode`) and compute the
   curvature value `c` in `[0.0, 1.0]` with the algorithm selected by the code. Store it in
   a field of the path, e.g. `linkCurvature`.
2. **`StdPath.processWaySection`:** if `turncostbase <= -11`, skip the per-vertex formula
   (`turncost = 0` instead of `StdPath.java:89`) and use `linkCurvature` in the section cost.
3. Optionally record `c` in `MessageData` in detailMode, so it shows up in the messages
   output next to `TurnCost`.

How `c` enters the cost is an open question. The one hard requirement: the section cost
must stay `>= 0` for every possible section, otherwise the link is dropped
(`OsmPath.java:306`). Applying `c` to the distance part is safe by construction, e.g. a
discount on the costfactor:

```
costfactor_eff = costfactor * (1 - w * c)      // 0 <= w < 1  =>  costfactor_eff > 0
sectionCost    = elevation cost + dist * costfactor_eff + 0.5
```

The strength `w` could be a profile variable, or come from the code as well.

## What the profile can and cannot do (expression cache)

The way context is evaluated once per link (`OsmPath.java:142`), and its results are cached
by the way tags (CRC of `descriptionBitmap`, `BExpressionContext.java:358-390`): all links
with the same tags share one result. So a profile expression can depend only on tags and
constants, never on the geometry of a particular link.

**Fine: selecting the algorithm in the profile.** A fixed value in one profile works:

```
assign turncost = -11
```

Every link gets -11 regardless of the cache. A tag-dependent value works as well
(`if ismainroad then 90 else -11`), because tags are exactly what the cache is keyed by.
Java reads `rc.expctxWay.getTurncost()` in `addAddionalPenalty`, sees -11 and runs the
geometry algorithm; the value `c` is computed in Java afterwards, so the cache is not
involved. The same holds for any other parameter the profile supplies as a constant or
from tags (e.g. the strength `w`).

**Not possible: using `c` inside the profile.** A rejected alternative was to expose `c` to
the profile as a variable and compute the cost there, e.g. (hypothetical)

```
assign costfactor = multiply 1.0 sub 1 multiply 0.3 curvature   # curvature = c of the link
```

This cannot work: two `highway=secondary` links with the same tags would share one cached
`costfactor`, one straight and one curvy. Therefore applying `c` to the cost
(e.g. `costfactor * (1 - w * c)`) has to be done in Java, in `StdPath.processWaySection`;
the profile never sees `c`.

Summary:

| what                                         | where                         | ok? |
|----------------------------------------------|-------------------------------|-----|
| choose the algorithm (`turncost = -11`)      | profile, fixed or by tags     | yes |
| parameters like `w`                          | profile, constant or by tags  | yes |
| the value `c` itself                         | Java only                     | -   |
| a profile expression using `c`               | -                             | no  |

## Disadvantages

### Runtime cost

- The pre-pass runs on every link expansion, not once per link: the same link is reached
  by several paths, in both directions, in both routing passes, and again for alternatives.
  Over a route this is up to millions of link expansions.
- Per expansion the cost is linear in the number of geometry points, the same order as the
  existing section loop, so the slowdown is a constant factor on that part, not a change of
  complexity. It is larger for algorithms that need more than one pass or a window over
  several points (radius estimation).
- A cache per link is possible but not free: `OsmLink` has no spare field, and links are
  loaded and unloaded with their tiles. A small cache keyed by the `geometry` array identity
  (as `GeometryDecoder` does with `lastGeometry`) would help mainly for repeated expansions
  of the same link in a row.
- The cost is paid only where a profile uses a negative code; other profiles keep today's
  performance (one extra comparison per link).

#### What a section costs today

There are no trigonometric functions in the per-section path. This holds for every
turncost value, also 0: the angle is always computed (`OsmPath.java:289-290`), the turncost
itself is one multiplication at the end.

| step                      | where                                                | operations |
|---------------------------|------------------------------------------------------|------------|
| lon/lat -> metre scale    | `CheapRuler.getLonLatToMeterScales`                  | table lookup (`SCALE_CACHE[ilat / increment]`), no computation |
| distance                  | `RoutingContext.calcDistance` (`:415-421`, `:513`)   | 4 multiplications, 1 `sqrt`, `round`; nogo check only if nogo points exist |
| angle and cosine          | `CheapAngleMeter.calcAngle`                          | ~10 multiplications, 1 `sqrt`, 1 division; angle from a polynomial (`57.4539 + s2 * (9.57565 + ...)`), cosine as a normalized dot product |
| turncost                  | `StdPath.java:89`                                    | 1 multiplication, 1 addition, int cast |
| rest of processWaySection | `StdPath.java:49-176`                                | ~20 reads of built-in variables, a few divisions (`1000000 / downhillcost` etc. recomputed for every section), elevation buffers, `dist * costfactor` |

Per section that is about 2 `sqrt`, tens of multiplications and additions, a few divisions
and no transcendental function. `sqrt` is a single hardware instruction on current CPUs;
`sin`, `cos`, `atan2`, `exp` are roughly an order of magnitude more expensive.

Trigonometric and other transcendental functions appear only outside the regular sections:
`sin` / `cos` once at the start of the route when a start direction is given
(`OsmPath.java:282-283`), and `exp` in `StdPath.computeKinematic` (`calcIncline`, Tobler's
function, `StdPath.java:231`, `:258`), which runs only in detailMode, i.e. for the final
track, not during the search.

#### Big-O

- Today, per link expansion: decoding the geometry O(n) plus the section loop O(n),
  n = number of points of the link, together O(n).
- With one extra pass over the whole geometry: O(n) + O(n) = **O(n), the same class**.
  The whole search stays O(E * n̄ + E log E) (link expansions times the average number of
  points, plus the priority queue); only the constant factor of the O(n) part grows.
- n is bounded by the Douglas-Peucker filter of the map creator (points closer than 0.4 m
  to the simplified line are not in `.rd5`).

#### Constant factor

It depends only on what the algorithm does per point:

- **BRouter style** (coordinate differences, dot and cross products, `sqrt`, or the same
  `CheapAngleMeter` / its polynomial approximation): about the cost of today's geometric
  part of the loop, so the O(n) part gets slower by up to roughly 2x.
- **`atan2`, `acos`, `sin` per point**, or a radius estimate over a window of points with
  trigonometry: a clearly larger factor, still linear.

Recommendation: work like BRouter does, with cosines, cross products and differences of
directions instead of angles from trigonometric functions. A radius can be obtained from
the chord length and the sine of the angle, which comes from the cross product, again
without transcendental functions.

### A link is not a way

- A link ends at every network node: each junction, each tagged node (barrier, traffic
  signals, crossing: `OsmNodePT` is never a transfer node), each change of the map cell
  (`WayLinker.java:376-379`). One curvy road is usually split into many links.
- The algorithm sees only the current link. Of the previous link it has one point
  (`origin.originLon/Lat`, `OsmPath.java:128-129`); the following link is not known yet.
- Consequences:
  - short links (between junctions in villages, around a tagged node) have too few points
    for a reliable value; the algorithm needs a minimum length below which `c` falls back
    to a neutral value,
  - a bend cut by a junction is split between two links, and each of them sees only half
    of it,
  - neighbouring links of the same road can get different values, so the preference can
    change along one road.
- The map-creation tag does not have this problem: it is computed over the whole way
  (or a merged chain of ways) and only stored on each link.

### Not a problem: Douglas-Peucker

The geometry in `.rd5` is simplified by the map creator: only points at least 0.4 m from
the simplified line survive (`DPFilter.java:13`, `OsmNodeP.java:223-233`). This removes
points on nearly straight parts and thins out dense arcs, but keeps the shape. The
algorithm just has to be tuned on the simplified geometry, which is what it sees at runtime
anyway.

### Other notes

- The decoded list lives in a shared cache (`GeometryDecoder.cachedNodes`); it is valid
  only until the next `decodeGeometry` call and must not be kept.
- When a waypoint is matched in the middle of a link (`shortestmatch`,
  `OsmPath.java:241-270`), `c` is computed over the whole link but applied only to the
  part that is used. That is acceptable for a per-link property.
- Overloading `turncost` with codes is compact but implicit. A cleaner but larger change
  would be a new built-in way variable (e.g. `curvaturemode`) in `BExpressionContextWay`.

## Comparison with the map-creation tag

|                          | runtime, negative turncost code | tag `estimated_curvature_class` |
|--------------------------|---------------------------------|---------------------------------|
| scope of the measurement | one link                        | whole way                       |
| routing speed            | extra pass per link expansion   | no change                       |
| map data                 | no change                       | new lookup value, maps rebuilt  |
| new algorithm / tuning   | new app version                 | new maps                        |
| profile control          | code per way (`-11`, `-12`)     | ordinary expression on the tag  |
| curvature value usable in profile expressions | no (`c` applied in Java; the algorithm is selected by `turncost`) | yes (the tag is an ordinary lookup value) |
