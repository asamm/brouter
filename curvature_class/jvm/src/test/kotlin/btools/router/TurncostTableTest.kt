// Same package as StdPath, helpers in TestSupport.kt.
package btools.router

import kotlin.test.Test

/**
 * Turncost of a single section for a given turn angle, computed by the real
 * StdPath.processWaySection (StdPath.java:89). Pure turncost only: zero length,
 * no elevation, the value is read from message.linkturncost.
 *
 * Run (from curvature_class/jvm):
 *   ../../gradlew test --tests 'btools.router.TurncostTableTest'
 */
class TurncostTableTest {

    private val turncosts = listOf(-20, -50)
    private val angles = listOf(0, 5, 8, 10, 12, 13, 15, 20, 30, 45, 60, 90, 120, 135, 150, 180)

    @Test
    fun `turncost by angle`() {
        val contexts = turncosts.associateWith { wayContext(it) }

        println()
        println("turncost by turn angle (StdPath.processWaySection, message.linkturncost)")
        println("angle | measured |   cos   | " + turncosts.joinToString(" | ") { "tc=%4d".format(it) })
        for (deg in angles) {
            val turn = Turn(deg.toDouble())
            val values = turncosts.map { "%7d".format(Section(contexts.getValue(it), 0.0, turn).turncost) }
            println("%4d° | %7.2f° | %7.4f | %s".format(deg, turn.angle, turn.cosangle, values.joinToString(" | ")))
        }

        println()
        println("smallest angle with non-zero turncost (0.1° steps)")
        for (tc in turncosts) {
            val rc = contexts.getValue(tc)
            val first = (0..1800).map { it / 10.0 }.first { Section(rc, 0.0, Turn(it)).turncost != 0 }
            println("tc=%4d: %5.1f°".format(tc, first))
        }
    }

    /*
    TurncostTableTest > turncost by angle() STANDARD_OUT

    turncost by turn angle (StdPath.processWaySection, message.linkturncost)
    angle | measured |   cos   | tc= -20 | tc= -50
       0° |    0.00° |  1.0000 |       0 |       0
       5° |    5.02° |  0.9962 |       0 |       0
       8° |    8.01° |  0.9903 |       0 |       0
      10° |   10.01° |  0.9848 |       0 |       0
      12° |   12.03° |  0.9782 |       0 |       0
      13° |   13.03° |  0.9744 |       0 |      -1
      15° |   15.03° |  0.9660 |       0 |      -1
      20° |   20.07° |  0.9396 |      -1 |      -2
      30° |   30.06° |  0.8662 |      -2 |      -6
      45° |   44.98° |  0.7074 |      -5 |     -14
      60° |   59.89° |  0.5004 |      -9 |     -24
      90° |   90.00° |  0.0000 |     -19 |     -49
     120° |  120.11° | -0.5004 |     -29 |     -74
     135° |  135.02° | -0.7074 |     -33 |     -85
     150° |  149.94° | -0.8662 |     -37 |     -93
     180° |  180.00° | -1.0000 |     -39 |     -99

    smallest angle with non-zero turncost (0.1° steps)
    tc= -20:  20.0°
    tc= -50:  12.6°
     */
}
