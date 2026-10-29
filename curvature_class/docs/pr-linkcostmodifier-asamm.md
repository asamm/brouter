## Summary

A hook that changes the cost of a link from its whole geometry, selected by a negative
`turncost` of the way. It is the engine part of the runtime road curvature for road
motorcyclists: curvy roads should become cheaper, which the per-point turn angle penalty
cannot do. This PR contains only the hook and two trivial constant implementations; the
curvature algorithm comes later behind code `-10`.

The branch is based on `master` (= upstream `master`), so the same commits can later go
to upstream without cherry-picks.

## Behaviour

| `turncost` of the way | turn angle penalty | LinkCostModifier |
|---|---|---|
| `>= 0` | as before | none |
| `-10` | off | factor 1, the cost does not change (the curvature goes here later) |
| `-11` | off | factor 0.5, for tests |
| other negative | off | none |

Profiles with a non-negative `turncost` get exactly the same costs as before (the section
cost is multiplied by `1.`). No profile in `misc/profiles2` uses a negative `turncost`.

## Commits

1. **Negative turncost switches off the turn angle penalty** (`StdPath`, profile guide).
   A negative per-point penalty depended on how densely the way is drawn and dropped the
   whole link when a section cost went below zero. The bike crossing penalties
   (`additional_turn_cost`) are still added.
2. **Add LinkCostModifier interface**: one method,
   `linkCostFactor(lon0, lat0, sourceNode, transferNodes, targetNode)`, gets the point
   before the link (`-1` at the route start) and the whole link geometry in the direction
   of travel, returns a factor for its section costs.
3. **Select a LinkCostModifier by the turncost code**: `RoutingContext.getLinkCostModifier`
   with a `switch` over the code, static shared instances of `ConstantLinkCostModifier`.
   No new fields in `RoutingContext`; an implementation must be thread safe.
4. **Apply the LinkCostModifier to the section costs of a link** (`OsmPath`): the factor
   is computed once per link before the section loop and multiplies every section cost.
5. **Test** (`LinkCostModifierTest`): one track routed with copies of `shortest.brf`
   that differ only in `turncost` (0, 90, -10, -11, -12).

## What the factor applies to

- Applied: every section cost from `processWaySection`, i.e. distance × costfactor,
  elevation cost and the bike crossing penalties.
- Not applied: initialcost, nogo cost, target node cost, reference track penalty.
- The factor is applied before the `sectionCost < 0` check, so a negative factor drops
  the link instead of producing a negative cost.
- Waypoint in the middle of a link: the factor is computed from the whole link.
- Only the cost; time, energy and kinematics are unchanged. The per-section messages
  (detail mode) show the costfactor without the factor.
- A negative `turncost` also removes the start direction bias (the turn angle of the
  first section after a faked origin no longer costs anything).

## Test plan

- [x] `./gradlew :brouter-core:test` on the branch and on a trial merge into `asamm`
- [x] `pmdMain`, `pmdTest` without findings
- [x] costs on the test track (689 m): turncost 0 → 689, -10 → 689, -12 → 689,
      -11 → 331 (689 / 2 minus int rounding of 43 sections), 90 → 950

🤖 Generated with [Claude Code](https://claude.com/claude-code)
