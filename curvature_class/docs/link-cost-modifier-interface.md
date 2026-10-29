# LinkCostModifier: hook in BRouter

Implemented on branch `curvaturepr` (based on `master`, i.e. upstream `master`), five
commits, PR to `asamm` first, then to upstream. Description of the PR:
`pr-linkcostmodifier-asamm.md`.

The runtime curvature has two parts with different owners:

| part | what | where | state |
|---|---|---|---|
| **hook** (this document) | a small, generic hook in the engine: a link is handed over with its whole geometry, the hook returns a factor for its section costs | `brouter-core`, branch `curvaturepr` | implemented, with two constant implementations |
| **curvature** | `c` from the window, M3 bands, serpentine rule, cap 0.9; factor `1 - c` | an implementation of the hook behind code `-10` | not written; algorithm in `runtime-curvature-window.md`, Kotlin port `jvm/src/main/kotlin/btools/router/LinkCurvature.kt` |

The hook knows nothing about curvature. Any algorithm that wants to change the cost of a
link from its shape can use it, which is the argument for the upstream PR. Background of
the negative `turncost` code: `runtime-curvature-turncost.md`.

Line numbers refer to `brouter-core/src/main/java/btools/router/*.java` on `curvaturepr`.

## Behaviour

| `turncost` of the way | turn angle penalty | LinkCostModifier |
|---|---|---|
| `>= 0` | as before | none |
| `-10` | off | factor 1, the cost does not change (the curvature goes here later) |
| `-11` | off | factor 0.5, for tests |
| other negative | off | none |

Profiles with a non-negative `turncost` get exactly the same costs as before (the section
cost is multiplied by `1.`). No profile in `misc/profiles2` on `master` uses a negative
`turncost`.

## Commits

| commit | content |
|---|---|
| `a2f78a6e` Negative turncost switches off the turn angle penalty | `StdPath.java:89-91`, `docs/developers/profile_developers_guide.md` |
| `f5b2a027` Add LinkCostModifier interface | new `LinkCostModifier.java` |
| `22e0ceb7` Select a LinkCostModifier by the turncost code | new `ConstantLinkCostModifier.java`, `RoutingContext.java:231-247` |
| `084a5298` Apply the LinkCostModifier to the section costs of a link | `OsmPath.java:199-202`, `:310-311` |
| `d582d3c2` Test the LinkCostModifier selection by turncost | new `src/test/java/btools/router/LinkCostModifierTest.java` |

## The code

### Turn angle penalty (`StdPath.java:88-91`)

```java
// penalty for turning angle
// a negative turncost switches it off, the value is reserved for a linkCostModifier
int turncost = turncostbase < 0.f ? 0
  : (int) ((1. - cosangle) * turncostbase + 0.2); // e.g. turncost=90 -> 90 degree = 90m penalty
```

The bike crossing penalties (`additional_turn_cost`, added to `turncost` right after) stay:
they are junction logic, not road shape.

### The interface (`LinkCostModifier.java`)

```java
/**
 * Changes the cost of a link from its geometry.
 *
 * Selected by a negative turncost of the way, the turn angle penalty is switched
 * off then (see StdPath). Called once per link, before its sections are processed.
 * An instance can be shared by several routing threads, so it must be thread safe.
 */
public interface LinkCostModifier {

  /**
   * @param lon0          longitude of the point before the link (the last but one point
   *                      of the previous link), -1 at the start of the route
   * @param lat0          latitude of that point, -1 at the start of the route
   * @param sourceNode    start of the link
   * @param transferNodes intermediate points in the direction of travel, null if none
   * @param targetNode    end of the link
   * @return factor for the section costs of the link, >= 0; 1 = no change
   */
  double linkCostFactor(int lon0, int lat0, OsmNode sourceNode, OsmTransferNode transferNodes, OsmNode targetNode);
}
```

### Selection (`RoutingContext.java:231-247`)

```java
// linkCostModifiers selected by a negative turncost of the way (see StdPath)
private static final LinkCostModifier LINK_COST_NONE = new ConstantLinkCostModifier(1.);
private static final LinkCostModifier LINK_COST_HALF = new ConstantLinkCostModifier(0.5); // for tests

public static LinkCostModifier getLinkCostModifier(float turncost) {
  switch ((int) turncost) {
    case -10:
      return LINK_COST_NONE;
    case -11:
      return LINK_COST_HALF;
    default:
      return null;
  }
}
```

`ConstantLinkCostModifier` returns the same factor for every link.

### The hook (`OsmPath.java:196-202`, `:310-311`)

```java
OsmTransferNode transferNode = link.geometry == null ? null
  : rc.geometryDecoder.decodeGeometry(link.geometry, sourceNode, targetNode, isReverse);

// a negative turncost can select a linkCostModifier for the section costs of the link
LinkCostModifier linkCostModifier = RoutingContext.getLinkCostModifier(rc.expctxWay.getTurncost());
double linkCostFactor = linkCostModifier == null ? 1.
  : linkCostModifier.linkCostFactor(lon0, lat0, sourceNode, transferNode, targetNode);

for (int nsection = 0; ; nsection++) {
  ...
  double sectionCost = processWaySection(rc, dist, delta_h, elevation, angle, cosangle, isStartpoint, nsection, lastpriorityclassifier)
    * linkCostFactor;
```

## Contract

- **Selection:** the `turncost` of the way is the code, so a profile can choose it per way
  by tags (`if ismainroad then 90 else -10`). The expression cache is not a problem, the
  code depends on tags only (`runtime-curvature-turncost.md`). A non-integer value is cut
  to an int (`-10.5` selects `-10`).
- **Input:** the point before the link (`origin.originLon/Lat`, `-1` at the start of the
  route) and the whole geometry in the direction of travel: `sourceNode`, the decoded
  list of `OsmTransferNode`, `targetNode`. Nothing is copied. The list lives in the cache
  of `GeometryDecoder` and is valid only during the call.
- **What the factor applies to:** every section cost from `processWaySection`, i.e.
  `dist * costfactor` (the slope-dependent costfactor), the elevation cost and the bike
  crossing penalties. Not initialcost (`OsmPath.java:155-171`), nogo cost, the target node
  cost or the reference track penalty: access penalties and nogo weights are never
  discounted.
- **Range:** the engine does not check the factor. It is applied before the check
  `sectionCost < 0` (`OsmPath.java:312`), so a negative factor drops the link instead of
  producing a negative cost.
- **Waypoint in the middle of a link:** the factor is computed from the whole link, also
  when the route uses only a part of it.
- **Traffic backbone:** the section costs are set to 0 after the factor, no effect.
- **Threads:** the instances are static and shared by all routing threads; an
  implementation must be thread safe (stateless, local arrays, or a `ThreadLocal` inside).
  `RoutingContext` gets no new fields.
- **Only the cost.** Time, energy and kinematics are not affected.
- **Messages (detail mode):** `costfactor` and `linkturncost` of `MessageData` are
  without the factor; the cost of the track is with it.
- **Models:** the hook is in `OsmPath`, so it works for the std and the kinematic model.
  The turn angle penalty is switched off only in `StdPath`; `KinematicPath` does not use
  `turncost`.
- **Start direction:** a negative `turncost` also removes the start direction bias (the
  angle of the first section after a faked origin, `OsmPath.java:282-293`, costs nothing).

## Test

`LinkCostModifierTest` routes the track of `RoutingEngineTest.routeCrossingSegmentBorder`
(689 m, segments from the map-creator test) with copies of `misc/profiles2/shortest.brf`
(cost 1 per metre) that differ only in `turncost`. The copy and `lookups.dat` are written
to a `TemporaryFolder`, with `turncost` in the file name, because `ProfileCache` knows a
profile by name and timestamp. Overriding `turncost` with `keyValues` does not work: an
injected value belongs to the global context and is read only in the way context
("cannot assign to readonly variable turncost").

| turncost | cost | checks |
|---|---|---|
| 0 | 689 | reference |
| -12 | 689 | a negative code without a modifier only switches the penalty off |
| -10 | 689 | factor 1 does not change the cost |
| -11 | 331 | factor 0.5; 689 / 2 minus the int rounding of 43 sections |
| 90 | 950 | a positive turncost still adds the penalty |

All tests also check that the track (its distance) stays the same. Not tested directly:
that initialcost is not discounted (`shortest.brf` has initialcost only on ferries).

## Our implementation behind it

The curvature becomes one more class and one more `case`:

```java
case -10:
  return LINK_COST_CURVATURE;    // linkCostFactor() = 1 - c
```

It computes `dist[]` and `angle[]` from the geometry itself and then runs `bands()` + M3
+ serpentine rule of `LinkCurvature.kt`. Details: "Integration into the engine" in
`runtime-curvature-window.md`.

## Decisions (2026-10-29) and what was rejected

The first proposal (2026-10-22) was a streamed interface with a correction at the end of
the link. Changed while implementing:

| question | first proposal | implemented | why |
|---|---|---|---|
| shape | streamed: `startLink` / `addSection(dist, angle)` / `linkCostFactor()` | one call with the whole geometry, before the section loop | the smallest change in the engine (one call, one multiplication); no special case at the early `return` at the end waypoint or at the reset at the start waypoint |
| where the factor applies | once at the end of the link, on the sum of the section costs | on every section cost | the factor is known before the loop; the same result up to int rounding (now per section, at most 1 per section) |
| registration | a field `linkCostModifier` in `RoutingContext`, set by the app | hardwired: `switch` over the code in `RoutingContext`, static instances | no new state in `RoutingContext`, no setup in the app; keep it simple |
| range of the factor | check `f >= 0` in the engine | no check | a negative factor drops the link through the existing `sectionCost < 0` check |
| negative turncost without a modifier | per-vertex penalty as before | penalty off | the negative per-vertex penalty was never usable (density dependent, drops links) |
| models | no restriction | no restriction | unchanged |
| new built-in variable instead of the `turncost` code | - | not in this PR | keep it simple; expected aesthetic objection upstream |

The price of the one call: the implementation computes distances and angles once more
(it must not use `rc.calcDistance`, which has side effects, `RoutingContext.java:474-574`),
and at a waypoint in the middle of a link it measures the whole link.

## Open for the upstream PR

- Aesthetic objections to expect: `turncost` overloaded with codes, a test implementation
  (`-11`) in production code, a hook whose only production implementation (`-10`) does
  nothing yet. The description should say what it is for (curvature for road
  motorcyclists).
- Upstream merges PRs as squash commits (since mid-2026): the five commits become one.
  If `curvaturepr` is merged into `asamm` first, `asamm` gets the same change again as
  another commit at the next sync with `master`; identical changes merge cleanly, changes
  made in the upstream review may conflict in `OsmPath` / `RoutingContext`.
