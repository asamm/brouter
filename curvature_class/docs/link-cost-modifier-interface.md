# Interface: LinkCostModifier (hook in BRouter for a PR)

Proposal, nothing is implemented. The runtime curvature has two parts with different
owners:

| part | what | where | review |
|---|---|---|---|
| **interface** (this document) | a small, generic hook in the engine: a link is reported section by section, the hook returns a factor for its cost | BRouter (`brouter-core`) | upstream PR |
| **implementation** | curvature `c` (window, M3 bands, serpentine rule, cap 0.9), buffers, codes `-11`, `-12` | our code, `LinkCurvature` | ours |

The interface knows nothing about curvature. Any algorithm that wants to change the cost
of a link from its shape can use it, which is the argument for the PR. The algorithm of
the implementation: `runtime-curvature-window.md`; the background of the negative
`turncost` code: `runtime-curvature-turncost.md`.

Line numbers refer to `brouter-core/src/main/java/btools/router/*.java` in this repository.

## The interface

```java
package btools.router;

/**
 * Changes the cost of a link from its geometry.
 *
 * Active for a way whose turncost is negative; the turncost penalty per vertex is not
 * computed then. One instance per routing request, used by one thread only.
 */
public interface LinkCostModifier {

  /**
   * Start of a link, or of the rest of a link after a waypoint match in its middle
   * (then everything reported so far for this link is discarded).
   *
   * @param code         turncost of the way, a negative number, selects the algorithm
   * @param isRouteStart the link starts the route; the angle of the first section is not
   *                     a real turn (it comes from a faked origin)
   */
  void startLink(int code, boolean isRouteStart);

  /**
   * One section of the link, in the direction of travel.
   *
   * @param dist  length in m, as rc.calcDistance (>= 1)
   * @param angle signed turn angle at the start point of the section in degrees, as
   *              CheapAngleMeter.calcAngle; for the first section it is the turn relative
   *              to the last point of the previous link
   */
  void addSection(double dist, double angle);

  /**
   * End of the link: the factor for the sum of the section costs of the link.
   * 1 = no change; the curvature implementation returns 1 - c.
   */
  double linkCostFactor();
}
```

## Calls for one link

```
addAddionalPenalty(link)
  evaluate way tags (:142)            turncost < 0 and a modifier registered?
  startLink(code, isRouteStart)       isRouteStart = origin.originLon == -1 (:128)
  loop over sections (:199)
    [waypoint match in the link]      startLink(code, true), section cost sum = 0
    dist (:238), angle (:289)
    addSection(dist, angle)
    sectionCost (:305), turncost = 0 in StdPath
    cost += sectionCost; sum += sectionCost (:315)
    [stop at the end waypoint]        factor applied, return (:345)
  end of the loop (:368)              factor applied
```

The factor is applied once per link:

```java
cost += (int) ((linkCostModifier.linkCostFactor() - 1.) * linkSectionCost);
```

## Changes in BRouter

| file / place | change | lines (approx.) |
|---|---|---|
| new `LinkCostModifier.java` | the interface above | ~15 |
| registration (see decision 2) | `public LinkCostModifier linkCostModifier;` in `RoutingContext` | 1 |
| `OsmPath.java:142` | `modifier = turncost < 0 ? rc.linkCostModifier : null`, `startLink(...)` | 3 |
| `OsmPath.java:246-251` | `startLink(code, true)`, sum = 0 | 2 |
| `OsmPath.java:289` | `addSection(dist, angle)` | 1 |
| `OsmPath.java:315` | `linkSectionCost += (int) sectionCost` | 1 |
| `OsmPath.java:345`, `:368` | apply the factor | 2 × 3 |
| `StdPath.java:89` | `turncost = 0` when the modifier is active | 1 |

About 30 lines, no change for a profile without a negative turncost or without a
registered modifier (one comparison per link).

## Contract

- **Selection:** `turncost < 0` of the way **and** a registered modifier. The code is the
  turncost itself, so a profile can choose it per way by tags
  (`if ismainroad then 90 else -11`); the expression cache is not a problem, the code
  depends on tags only (`runtime-curvature-turncost.md`).
- **What the factor applies to:** the sum of the section costs of the link (distance part
  `dist * costfactor` with the slope-dependent costfactor, plus the elevation cost). Not to
  initialcost (`:155-171`), nogo cost (`:371-376`) or the target node cost (`:379`):
  access penalties and nogo weights are never discounted.
- **Sections are not changed.** The factor is applied after the loop, so the check
  `sectionCost < 0` (`:306`) and the per-section messages work as today.
- **Waypoint in the middle of a link:** at the start waypoint the path begins in the link
  (`:246-251`), `startLink(code, true)` is called again; at the end waypoint the loop stops
  early (`:345`) and the factor is computed from the sections reported so far.
- **Traffic backbone** (`:311-313`): the section costs are 0, so the factor has no effect.
- **Threads:** one instance per routing request (with registration in `RoutingContext`,
  which is per request), so the implementation needs no synchronisation and can keep its
  buffers as plain fields.
- **Only the cost.** Time, energy and kinematics (`:318`) are not affected.
- **Detail mode / messages:** nothing in this version. The implementation can be extended
  later (e.g. `c` as a column next to `TurnCost`), that is a separate change.

## Our implementation behind it

```kotlin
class LinkCurvature : LinkCostModifier {
    override fun startLink(code: Int, isRouteStart: Boolean)  // clear buffers, choose params by code
    override fun addSection(dist: Double, angle: Double)      // append to growable buffers
    override fun linkCostFactor(): Double                     // 1 - c, c from bands() + M3 + serpentine rule, <= 0.9
}
```

The port in `jvm/src/main/kotlin/btools/router/LinkCurvature.kt` has the algorithm; the
interface methods and reusable buffers replace its `compute(dist, angle, isRouteStart)`.
Unknown codes (other than `-11`, `-12`) return 1.

## Alternatives not chosen

- **One call before the loop with the geometry** (`sourceNode`, the transfer node list,
  `targetNode`): even less code in the engine, but the implementation would have to compute
  distances and angles again (it must not use `rc.calcDistance`, which has side effects,
  `RoutingContext.java:423-509`), and at a waypoint in the middle of a link it would measure
  the whole link.
- **The engine collects arrays and calls `compute(dist[], angle[])` at the end:** buffers
  in the engine code, which is what we want to avoid.
- **The hook changes every section cost:** the factor is not known before the end of the
  link (the window looks ahead), so it would need the pre-pass above.

## Decisions open

1. **Shape of the interface:** streamed (`startLink` / `addSection` / `linkCostFactor`,
   recommended) or one call with the geometry.
2. **Registration:**
   - (a) **one field in `RoutingContext`**, `public LinkCostModifier linkCostModifier`
     (recommended): a reference, no buffers; the context exists per request, so one
     instance per thread without `ThreadLocal`. The app sets it before routing.
   - (b) a static factory in `OsmPath` (`OsmPath.setLinkCostModifierFactory(...)`) with a
     `ThreadLocal` inside: `RoutingContext` untouched, but global state, which upstream
     reviewers usually do not like.
3. **Range of the factor checked by the engine:** only `f >= 0` (recommended: generic, a
   modifier may also penalise with `f > 1`; the safety of our values, `c <= 0.9`, is the
   implementation's job) or `0 < f <= 1` (discount only).
4. **Negative turncost without a registered modifier:** today's behaviour, the per-vertex
   penalty with a negative value (recommended: nothing that exists changes) or turncost 0.
5. **Models:** the hook is in `OsmPath`, so it works for the std and the kinematic model.
   `KinematicPath` does not use turncost at all (it has its own turn penalty,
   `KinematicPath.java:44`), so there is nothing to switch off there; the kinematic model
   is for cars and nobody would set a negative turncost in it. Recommended: no restriction
   to the std model in the engine.
