// Same package as StdPath, helpers in TestSupport.kt.
package btools.router

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import kotlin.math.roundToInt
import kotlin.test.Test

/**
 * Cost of each simulated road from out/roads.json, as BRouter computes it for one
 * link, for several turncost values. costfactor = 1.0, flat (no elevation).
 * Writes out/roads_cost.json (per osm_id) for the visualization in python/.
 *
 * Each road is treated as a single BRouter link: points_local[0] and points_local[last]
 * are the link's nodes, the points in between are its geometry (transfer nodes),
 * every pair of neighbouring points is one section.
 *
 * Run (from curvature_class/jvm):
 *   ../../gradlew test --tests 'btools.router.RoadCostTest'
 */
class RoadCostTest {

    private val roadsFile = File("../out/roads.json")
    private val costFile = File("../out/roads_cost.json")

    private val costfactor = 1.0
    private val turncosts = listOf(0, 90, -20, -50)

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun `cost of simulated roads`() {
        val roads = json.decodeFromString<List<RoadIn>>(roadsFile.readText())
        val contexts = turncosts.associateWith { wayContext(it, costfactor) }

        val results = roads.map { road ->
            val points = road.pointsLocal.map { (x, y) -> toILonLat(x, y) }
            // the geometry of the sections does not depend on the profile
            val sections = geometry(contexts.getValue(0), points)
            RoadOut(
                osmId = road.osmId,
                type = road.type,
                highway = road.highway,
                lengthM = road.lengthM,
                distM = sections.sumOf { it.dist },
                sections = sections.map { SectionOut(it.dist, round2(it.angle), round4(it.cosangle)) },
                variants = turncosts.map { tc -> linkCost(contexts.getValue(tc), tc, sections) },
            )
        }

        costFile.parentFile.mkdirs()
        costFile.writeText(Json.encodeToString(CostOut(roadsFile.name, costfactor, turncosts, results)))

        printSummary(results)
        println("written: ${costFile.canonicalPath}")
    }

    /*
    RESULTS (out/roads.json from generate_roads.py --count 60 --seed 1, costfactor = 1.0, flat)

    Cost change against turncost = 0 (cost = BRouter distance), per road type, 10 roads each:

      type        avg section | tc=90  min / avg / max  | tc=-20 min / avg / max | tc=-50 min / avg / max  | dropped at -50
      straight       433 m    |   0.0 /   0.0 /   0.0 % |   0.0 /  0.0 /  0.0 %  |   0.0 /   0.0 /   0.0 % |  0
      gentle          33 m    |   0.0 /   0.0 /   0.0 % |   0.0 /  0.0 /  0.0 %  |   0.0 /   0.0 /   0.0 % |  0
      winding         26 m    |   0.0 /  +0.6 /  +1.5 % |   0.0 /  0.0 /  0.0 %  |  -0.2 /   0.0 /   0.0 % |  0
      mountain        12 m    |  +7.7 / +12.2 / +14.9 % |   0.0 /  0.0 /  0.0 %  |  -7.3 /  -5.1 /  -3.7 % |  0
      serpentine      10 m    | +18.9 / +23.5 / +26.5 % |  -1.2 / -0.5 /  0.0 %  | -10.4 /  -9.0 /  -6.7 % |  2
      urban           28 m    |   0.0 / +17.7 / +47.2 % |  -5.2 / -1.3 /  0.0 %  | -15.5 /  -5.9 /   0.0 % |  5

    Turn angle at the inner points (vertices), per road type:

      type        vertices  median  >= 12.6° (non-zero at -50)  >= 20° (non-zero at -20)  max
      gentle         325     0.9°            0                          0                  3°
      winding        333     5.2°            5                          0                 13°
      mountain       569    12.9°          350                          0                 15°
      serpentine     946    14.1°          637                         51                 25°
      urban           69    15.3°           43                         20                 30°

    Summary

    1. turncost does not measure curvature, it measures the angles at the vertices of the
       geometry. The same bend drawn with more points has smaller angles and, because
       (1 - cos) grows with the square of the angle, a much smaller turncost
       (sum of (1 - cos) for a 90° bend: one 90° vertex = 1.0, three 30° vertices = 0.40,
       ten 9° vertices = 0.12; with a negative turncost the int cut in StdPath.java:89
       turns the small values into 0, so ten 9° vertices give nothing at -20 and -50).
       The result depends on how densely the road is mapped more than on how curvy it is.

    2. Today (turncost = 90) gentle and winding roads get practically nothing (0 to +1.5 %),
       mountain roads +12 %, serpentines +24 %, and urban streets up to +47 %, because they
       have few points and sharp corners. The current profiles therefore already make curvy
       roads more expensive, most of all the strongly curved ones.

    3. turncost = -20 does almost nothing. It is non-zero only from 20° per vertex; on these
       roads no gentle, winding or mountain vertex reaches 20°, so their cost does not change at
       all. Serpentines get -0.5 % on average. It cannot make curvy roads preferred.

    4. turncost = -50 (non-zero from 12.6°) gives mountain roads -5 % and serpentines -9 %,
       so it does favour them, but still not gentle or winding roads (0 %). At the same time
       7 of 60 links are dropped (sectionCost < 0, OsmPath.java:306): 5 urban streets and 2
       serpentines, always because of a 1-3 m section after a 20-30° vertex. On real
       maps such short sections are common at junctions and in roundabouts, and such links
       would become silently unusable.

    5. Negative turncost is therefore not a usable way to prefer curvy roads: its effect is
       small where it is wanted (gentle and winding roads), it depends on how densely the road
       is mapped, and it breaks the network through dropped links. A preference for curvy
       roads has to come from a curvature measure of the whole way, normalized by length
       (estimated_curvature_class), applied through costfactor, which stays positive.

    Caveat: the vertex angles come from generate_roads.py (median section length on curved
    roads: gentle and winding 19 m, mountain 10 m, serpentine and urban 3 m). Real OSM data has different node densities, so the per-type numbers will differ,
    but the mechanism (points 1, 4 and 5) does not depend on the data.
     */

    /**
     * Distance and angle of each section, measured by the real BRouter code.
     * This is the geometry part of the section loop in OsmPath.addAddionalPenalty,
     * see linkCost for the whole loop.
     */
    private fun geometry(rc: RoutingContext, points: List<Pair<Int, Int>>): List<SectionGeometry> =
        (0 until points.size - 1).map { i ->
            // OsmPath.java:209-217: the section ends at the next transfer node, the last one
            // at the target node. OsmPath.java:363-366 then shifts the points by one:
            // lon0 <- lon1, lon1 <- lon2. Here simply points[i - 1], points[i], points[i + 1].
            val (lon1, lat1) = points[i]
            val (lon2, lat2) = points[i + 1]

            // Previous point for the angle. For the first section of a link BRouter takes it
            // from the previous link (origin.originLon/Lat, OsmPath.java:128-129), so the turn
            // at a junction is measured like any bend inside the way. Our road is the start
            // of the route (isStartpoint, OsmPath.java:220), and without a start direction
            // BRouter fakes a point straight behind (OsmPath.java:284-287):
            // angle 0, so the first section has no turncost.
            val (lon0, lat0) = if (i == 0) (lon1 - (lon2 - lon1)) to (lat1 - (lat2 - lat1)) else points[i - 1]

            // OsmPath.java:238, whole metres (rounded), at least 1 m
            val dist = rc.calcDistance(lon1, lat1, lon2, lat2)
            // OsmPath.java:289-290
            val angle = rc.anglemeter.calcAngle(lon0, lat0, lon1, lat1, lon2, lat2)
            SectionGeometry(dist, angle, rc.anglemeter.cosAngle)
        }

    /**
     * Cost of one link: the section loop of OsmPath.addAddionalPenalty (OsmPath.java:199-368)
     * reduced to what applies here, with the real StdPath.processWaySection for each section.
     *
     * How BRouter gets there: when the router extends a path by a link, it creates a new
     * path with OsmPath.init(origin, link, ...) (OsmPath.java:80-95). That copies the cost
     * so far (cost = origin.cost, :88) and the StdPath state (init(origin), :93), then calls
     * addAddionalPenalty (:94), which adds the cost of the link to cost.
     *
     * addAddionalPenalty step by step, and what this test does with each step:
     *
     * Before the loop (once per link)
     * - :128-133  lon0/lat0 = previous point (end of the previous link), lon1/lat1 = source node
     *             -> geometry(), first section
     * - :142      rc.expctxWay.evaluate(...): way tags evaluated once for the whole link
     *             -> wayContext() in TestSupport.kt, evaluated once per turncost
     * - :155-173  initialcost when initialclassifier changes between links -> left out (one link)
     * - :175-193  destination logic (access=destination only at start/end) -> left out
     * - :196-197  geometry decoded into transfer nodes -> points_local of roads.json
     *
     * The loop, one pass per section (:199)
     * - :209-217  end point of the section: next transfer node, or the target node -> geometry()
     * - :220      isStartpoint: no previous point (start of the route) -> i == 0
     * - :222-230  turn restrictions, only nsection == 0 -> left out
     * - :232-236  new MessageData per section -> path.message = MessageData() below
     * - :238      dist = rc.calcDistance(...) -> geometry()
     * - :240-270  shortestmatch: waypoint matched in the middle of the link -> not applicable
     * - :277-288  faked previous point at the start of the route -> geometry()
     * - :289-290  angle, cosangle by rc.anglemeter -> geometry()
     * - :292-303  delta_h and elevation from node elevations -> 0.0 and 100.0 (flat)
     * - :305      processWaySection(...) -> called below, the real StdPath code:
     *               StdPath.java:89      turncost = (int) ((1 - cosangle) * turncost + 0.2)
     *               StdPath.java:95      sectionCost = turncost
     *               StdPath.java:97-167  + elevation cost (0 here)
     *               StdPath.java:170     costfactor mixed by up/down weights (= costfactor here)
     *               StdPath.java:176     + dist * costfactor + 0.5
     * - :306-309  sectionCost < 0 (or costfactor > 9998, or overflow) -> cost = -1, return
     *             -> recorded in droppedSections, the loop goes on
     * - :311-313  istrafficbackbone -> sectionCost = 0 -> left out
     * - :315      cost += (int) sectionCost -> cost += sc.toInt() below
     * - :318      computeKinematic: time / energy, does not change the cost -> left out
     * - :348-356  last section: reference track penalty, break -> left out
     * - :363-367  shift lon0 <- lon1, lon1 <- lon2 -> geometry(), points[i - 1]
     *
     * After the loop
     * - :370-376  nogo cost -> left out
     * - :378-384  StdPath.processTargetNode: node initialcost of the target node -> left out
     *             (no node tags)
     */
    private fun linkCost(rc: RoutingContext, turncost: Int, sections: List<SectionGeometry>): VariantOut {
        // One path object per link, as in BRouter: StdPath keeps state between the
        // sections (elevation hysteresis buffers ehbd / ehbu; zero here, flat road).
        val path = StdPath()
        var cost = 0
        val sectionCost = mutableListOf<Double>()
        val sectionTurncost = mutableListOf<Int>()
        val droppedSections = mutableListOf<Int>()

        sections.forEachIndexed { i, s ->
            // fresh MessageData per section, so linkturncost holds just this section's turncost
            path.message = MessageData()
            val sc = path.processWaySection(rc, s.dist.toDouble(), 0.0, 100.0, s.angle, s.cosangle, i == 0, i, 0)

            // OsmPath.java:306: sectionCost < 0 -> cost = -1, the whole link is not usable.
            // BRouter stops there; we go on and only record it, to see all sections.
            if (sc < 0.0) droppedSections += i

            // OsmPath.java:315, the fraction is cut off (StdPath adds 0.5 to round)
            cost += sc.toInt()
            sectionCost += round2(sc)
            sectionTurncost += path.message.linkturncost
        }

        return VariantOut(
            turncost = turncost,
            cost = cost,
            turncostSum = sectionTurncost.sum(),
            dropped = droppedSections.isNotEmpty(),
            droppedSections = droppedSections,
            sectionCost = sectionCost,
            sectionTurncost = sectionTurncost,
        )
    }

    private fun printSummary(results: List<RoadOut>) {
        println()
        println("cost of the whole road (link), costfactor = $costfactor, flat; * = link dropped (sectionCost < 0)")
        println("    osm_id  type       highway      len_m  dist_m  sect | " +
            turncosts.joinToString(" | ") { "cost tc=%3d".format(it) } + " | " +
            turncosts.joinToString(" | ") { "turn tc=%3d".format(it) })
        for (r in results) {
            val costs = r.variants.joinToString(" | ") { "%10d%s".format(it.cost, if (it.dropped) "*" else " ") }
            val turns = r.variants.joinToString(" | ") { "%11d".format(it.turncostSum) }
            println("%10d  %-10s %-11s %6.0f  %6d  %4d | %s | %s".format(
                r.osmId, r.type, r.highway, r.lengthM, r.distM, r.sections.size, costs, turns))
        }
        println()
        for ((i, tc) in turncosts.withIndex()) {
            val dropped = results.count { it.variants[i].dropped }
            println("tc=%3d: %2d of %d roads dropped".format(tc, dropped, results.size))
        }
    }

    private fun round2(v: Double) = (v * 100).roundToInt() / 100.0
    private fun round4(v: Double) = (v * 10000).roundToInt() / 10000.0

    private class SectionGeometry(val dist: Int, val angle: Double, val cosangle: Double)

    /** One road of out/roads.json (written by python/generate_roads.py), only the fields used here. */
    @Serializable
    private data class RoadIn(
        @SerialName("osm_id") val osmId: Long,
        val type: String,
        val highway: String,
        @SerialName("length_m") val lengthM: Double,
        @SerialName("points_local") val pointsLocal: List<List<Double>>,
    )

    // out/roads_cost.json

    @Serializable
    private data class CostOut(
        val source: String,
        val costfactor: Double,
        val turncosts: List<Int>,
        val roads: List<RoadOut>,
    )

    @Serializable
    private data class RoadOut(
        @SerialName("osm_id") val osmId: Long,
        val type: String,
        val highway: String,
        /** length from roads.json (exact, float) */
        @SerialName("length_m") val lengthM: Double,
        /** sum of the section distances as BRouter measures them (whole metres) */
        @SerialName("dist_m") val distM: Int,
        val sections: List<SectionOut>,
        val variants: List<VariantOut>,
    )

    /** Section i goes from points_local[i] to points_local[i + 1]; the angle is at points_local[i]. */
    @Serializable
    private data class SectionOut(
        val dist: Int,
        val angle: Double,
        val cosangle: Double,
    )

    @Serializable
    private data class VariantOut(
        val turncost: Int,
        /** sum of (int) sectionCost, as OsmPath accumulates it */
        val cost: Int,
        @SerialName("turncost_sum") val turncostSum: Int,
        /** at least one section with sectionCost < 0: BRouter would not use the link */
        val dropped: Boolean,
        @SerialName("dropped_sections") val droppedSections: List<Int>,
        /** StdPath.processWaySection result per section (before the int cut) */
        @SerialName("section_cost") val sectionCost: List<Double>,
        /** message.linkturncost per section */
        @SerialName("section_turncost") val sectionTurncost: List<Int>,
    )
}
