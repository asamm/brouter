// Same package as StdPath, helpers in TestSupport.kt.
package btools.router

import kotlin.test.Test

/**
 * Shortest section after a turn that does not drop the whole link.
 *
 * OsmPath.addAddionalPenalty (OsmPath.java:306) sets cost = -1 (link not usable)
 * when sectionCost < 0. With a negative turncost this happens for short sections:
 * sectionCost = turncost + dist * costfactor + 0.5 (flat, no elevation).
 * The section cost is computed by the real StdPath.processWaySection.
 *
 * Value in the table: N = the link is dropped when the section is shorter than N m.
 *
 * Run (from curvature_class/jvm):
 *   ../../gradlew test --tests 'btools.router.SectionDropTest'
 */
class SectionDropTest {

    private val turncosts = listOf(-20, -50)
    private val costfactors = listOf(1.0, 2.0, 0.8)
    private val angles = listOf(15, 30, 45, 60, 90, 135, 180)

    @Test
    fun `section length that drops the link`() {
        val variants = turncosts.flatMap { tc -> costfactors.map { cf -> Triple(tc, cf, wayContext(tc, cf)) } }

        println()
        println("link dropped when the section after the turn is shorter than N m (sectionCost < 0)")
        println("angle | " + variants.joinToString(" | ") { (tc, cf) -> "tc=%3d cf=%.1f".format(tc, cf) })
        for (deg in angles) {
            val turn = Turn(deg.toDouble())
            val values = variants.map { (_, _, rc) -> "%13s".format("< ${minSafeLength(rc, turn)} m") }
            println("%4d° | %s".format(deg, values.joinToString(" | ")))
        }
    }

    /*
      link dropped when the section after the turn is shorter than N m (sectionCost < 0)
      angle | tc=-20 cf=1.0 | tc=-20 cf=2.0 | tc=-20 cf=0.8 | tc=-50 cf=1.0 | tc=-50 cf=2.0 | tc=-50 cf=0.8
        15° |         < 0 m |         < 0 m |         < 0 m |         < 1 m |         < 1 m |         < 1 m
        30° |         < 2 m |         < 1 m |         < 2 m |         < 6 m |         < 3 m |         < 7 m
        45° |         < 5 m |         < 3 m |         < 6 m |        < 14 m |         < 7 m |        < 17 m
        60° |         < 9 m |         < 5 m |        < 11 m |        < 24 m |        < 12 m |        < 30 m
        90° |        < 19 m |        < 10 m |        < 24 m |        < 49 m |        < 25 m |        < 61 m
       135° |        < 33 m |        < 17 m |        < 41 m |        < 85 m |        < 43 m |       < 106 m
       180° |        < 39 m |        < 20 m |        < 49 m |        < 99 m |        < 50 m |       < 124 m
     */

    /** Smallest whole section length (m) with sectionCost >= 0. */
    private fun minSafeLength(rc: RoutingContext, turn: Turn): Int =
        (0..1000).first { Section(rc, it.toDouble(), turn).cost >= 0.0 }
}
