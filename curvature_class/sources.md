# Sources: how others measure road curvature

Background for the design of the pseudo-tag `estimated_curvature_class` (a class for motorcyclists).
Researched on 15 Oct 2026.

## Kurviger

A route planner for motorcyclists. The exact algorithm is not published.

- [Kurviger blog: Explained: meaning of the curves](https://blog.kurviger.com/en/explained-meaning-of-the-curves/)
  Describes the modes *fastest*, *fast & curvy*, *curvy* and *extra curvy*. The *curvy* mode
  seeks a balance between fun and detours and prefers mountain passes and twisty
  roads. The *extra curvy* mode adds small roads with low traffic, avoids towns
  more and tolerates longer detours. Contains no technical description of the computation.
- [Kurviger forum: Routing heading](https://forum.kurviger.com/t/routing-heading/5289)
  According to a forum reply, curvature is only one of the factors. Towns are also taken into account,
  and the *curvy* modes avoid motorways.
- [OSM wiki: User:Boldtrn](https://wiki.openstreetmap.org/wiki/User:Boldtrn)
  Profile of Kurviger's founder. According to it, Kurviger prefers curvy roads
  and climbs and avoids towns and motorways. The author maps mainly for the sake of
  Kurviger and GraphHopper routing.

## GraphHopper

An open-source routing engine on which Kurviger's offline routing is built.

- [CurvatureCalculator.java](https://raw.githubusercontent.com/graphhopper/graphhopper/master/core/src/main/java/com/graphhopper/routing/util/CurvatureCalculator.java)
  The curvature of an edge is computed as `curvature = straight-line distance between ends / edge length`.
  This is inverse sinuosity (our metric M1): 1.0 means a straight road, a lower
  value a winding one. Edges shorter than 0.1 get 1.0. If the geometry contains
  elevations, the straight-line distance is computed in 3D.
- [GraphHopper forum: Help on Curvature settings in custom model](https://discuss.graphhopper.com/t/help-on-curvature-settings-in-custom-model/9885)
  Example of a motorcycle profile that multiplies priority according to the `curvature` value.
- [GraphHopper forum: Use weighting: curvature and custom](https://discuss.graphhopper.com/t/use-weighting-curvature-and-custom/7134)
  Difference between the older built-in `CurvatureWeighting` (uses a logarithm) and
  custom models, where priority can only be multiplied by a constant according to the `curvature` value.
  Reflects the state at the time the post was written; newer versions may differ.

## Curvature (roadcurvature.com), Adam Franco

An open-source tool (GPL v3) that searches OSM data for "fun" roads. It is
the best-documented approach and essentially corresponds to our metric M3.

- [adamfranco/curvature: README](https://raw.githubusercontent.com/adamfranco/curvature/master/README.md)
  Computation steps:
  - For each triple of neighbouring points, the radius of the circumscribed circle is computed. A segment between
    two points belongs to two triples and the smaller, larger or average of the two
    radii is taken (depending on configuration).
  - The length of each segment is multiplied by a weight according to its radius band. The road's score is
    the sum of weighted lengths in metres, i.e. roughly the length driven in bends.
  - Suppresses curvature at roundabouts and near crossings, stop signs
    and traffic lights. Filters out minor wiggles on straight sections.
  - Computes on merged road segments and splits the road at long straights
    (over 2.4 km).
  - Indicative score values: 300–600 are "pleasant" roads, over 1000 the best
    roads in the region.
- [adamfranco/curvature: add_segment_curvature.py](https://raw.githubusercontent.com/adamfranco/curvature/master/curvature/post_processors/add_segment_curvature.py)
  Default radius bands and weights:

  | R | weight |
  |---|---|
  | > 175 m | 0 (straight) |
  | ≤ 175 m | 1 |
  | ≤ 100 m | 1.3 |
  | ≤ 60 m | 1.6 |
  | ≤ 30 m | 2 |

- [Adam Franco Built Curvature to Help Find the Fun Roads](https://autos.yahoo.com/adam-franco-built-curvature-help-162500288.html)
  An older interview with the author. It gives different bands than the current code: over 150 m straight,
  around 50 m weight 2, hairpins under 25 m weight 4. Probably an older version of the
  settings; the current values are in `add_segment_curvature.py`.

## Implications for our design

- Sinuosity (GraphHopper) is simple, but an S-bend comes out almost like a straight road.
  For a standalone class, a radius-based foundation (Franco, M3) is better.
- Franco sums absolute length, so a long road wins. A class in brouter applies
  to a single segment, so a share of length in bends weighted by radius is more suitable.
- Not every curvature is fun for motorcyclists: urban corners, roundabouts
  and signalised intersections. This can be handled either directly in the class, or in the routing
  profile using the existing classes `estimated_town_class` and `estimated_traffic_class`.
- OSM splits roads at intersections. It is therefore advisable to compute the metrics on the merged
  road and assign the class to each of its sub-segments.
