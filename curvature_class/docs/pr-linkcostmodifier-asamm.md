## Summary

A hook that changes the cost of a link from its whole geometry, selected by a negative
`turncost` of the way, and the runtime road curvature for road motorcyclists behind it:
curvy roads become cheaper, which the per-point turn angle penalty cannot do. The PR
contains the hook, two trivial constant implementations (`-10`, `-11`) and the curvature
(`LinkCurvature`, `-12`).

The branch is based on `master` (= upstream `master`), so the same commits can later go
to upstream without cherry-picks.

## Behaviour

| `turncost` of the way | turn angle penalty | LinkCostModifier |
|---|---|---|
| `>= 0` | as before | none |
| `-10` | off | factor 1, the cost does not change |
| `-11` | off | factor 0.5, for tests |
| `-12` | off | `LinkCurvature`: factor `1 - c`, `c` = curvature of the link, 0 ... 0.9 |
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
   that differ only in `turncost` (0, 90, -10, -11, and a negative code without a
   modifier).
6. **Link curvature** (`LinkCurvature`, `case -12`): the link is cut into pieces of at
   most 20 m; for each piece the change of direction over 40 m of road around it gives
   the radius and one of five radius bands (hairpin < 30 m, sharp < 60 m, medium
   < 100 m, gentle < 175 m, straight). `c` is the length-weighted mean of the band
   weights (2, 1.6, 1.3, 1, 0) / 2. Serpentine rule: at least 20 % and 35 m of the link
   in R < 60 m raise `c` to at least 0.8. Links shorter than 40 m get `c = 0`; `c` is
   capped at 0.9. Stateless, local arrays, distances and angles computed with the same
   arithmetic as `OsmPath`. The negative code without a modifier in the test moved from
   `-12` to `-13`.

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

- [x] `./gradlew :brouter-core:test` on the branch
- [ ] the same on a trial merge into `asamm` (done for the first five commits)
- [x] `pmdMain`, `pmdTest` without findings
- [x] costs on the test track (689 m): turncost 0 → 689, -10 → 689, -13 → 689,
      -11 → 331 (689 / 2 minus int rounding of 43 sections), 90 → 950, -12 → 594
- [x] `LinkCurvature` vs. the Python prototype on the same distances and angles: every
      link the search evaluated on the test track (270) and on the Stelvio pass (1890,
      `moped.brf` with `turncost -12`), max |Δc| 5e-5 (rounding of the export), the
      serpentine rule fires on the same links
- [x] distances and angles computed by `LinkCurvature` are identical to those of the
      section loop of `OsmPath` (278 of 279 full links of the Stelvio route, 48 km)

The verification used a temporary export in `LinkCurvature` (marked
`EXPORT (temporary)`); it is switched off and will be removed before upstream.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
