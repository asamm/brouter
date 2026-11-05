# Curvature flow: where the LinkCostModifier hook is in the code

Files in `../../brouter-core/src/main/java/btools/router`. Line numbers refer to branch `asamm`
after the merge of `curvaturepr` (`cb998f0a`); on `curvaturepr` `RoutingContext` is 6 lines
earlier. Design and decisions: `docs/link-cost-modifier-interface.md`.

## 1. The interface: `LinkCostModifier.java:13-24`

One method, `linkCostFactor(lon0, lat0, sourceNode, transferNodes, targetNode)`. The
javadoc states the contract: called once per link, the implementation must be thread
safe, factor >= 0, 1 = no change.

## 2. Selection by the code: `RoutingContext.java:237-256`

- `:238-240` static shared instances `LINK_COST_NONE`, `LINK_COST_HALF`,
  `LINK_COST_CURVATURE`
- `:245` `getLinkCostModifier(float turncost)`: `switch ((int) turncost)`, -10 / -11 / -12
  return the instance, anything else `null`

## 3. Call and use of the factor: `OsmPath.java`, `addAddionalPenalty`

- `:196-197` decoding of the link geometry (`transferNode`), existing code
- `:199-202` the core of the hook: read `rc.expctxWay.getTurncost()`, select the modifier,
  call it once before the section loop; without a modifier the factor is `1.`
- `:310-311` `processWaySection(...) * linkCostFactor`, the factor multiplies every
  section cost
- `:312` the existing check `sectionCost < 0`, which drops the link for a negative factor

## 4. Turn angle penalty off: `StdPath.java:88-91`

`turncostbase < 0.f` gives `turncost = 0`. The bike crossing penalty
`additional_turn_cost` is still added right after.

## Implementations behind the hook

| class | code | factor |
|---|---|---|
| `ConstantLinkCostModifier.java:9-17` | -10, -11 | constant 1 / 0.5 |
| `LinkCurvature.java:96` (`linkCostFactor`) | -12 | `1 - c` |

## Test

`../../brouter-core/src/test/java/btools/router/LinkCostModifierTest.java`: one track with
copies of `shortest.brf`, `turncost` 0, 90, -10, -11, -13.

## Order at routing time

`OsmPath.java:200` -> `RoutingContext.getLinkCostModifier` -> `LinkCurvature.linkCostFactor`
-> back to `OsmPath.java:310`. The turn angle penalty (`StdPath.java:90`) runs separately,
inside `processWaySection`.
