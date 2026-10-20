// Same package as StdPath / OsmPath, so their package-private members are accessible.
package btools.router

import btools.util.CheapAngleMeter
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Run (from curvature_class/jvm):
 *   ../../gradlew test --tests 'btools.router.HelloBRouterTest'
 */
class HelloBRouterTest {

    @Test
    fun `BRouter classes are on the classpath`() {
        // package-private class from brouter-core
        assertEquals("btools.router.StdPath", StdPath::class.java.name)
    }

    @Test
    fun `right angle turn has cosine 0`() {
        // 0 -> 1 heading north, 1 -> 2 heading east (integer microdegrees, BRouter style)
        val lon = 195_000_000 // 15.0 E + 180
        val lat = 140_000_000 // 50.0 N + 90
        val meter = CheapAngleMeter()
        val angle = meter.calcAngle(lon, lat - 1000, lon, lat, lon + 1000, lat)
        println("angle = $angle, cos = ${meter.cosAngle}")
        assertTrue(abs(abs(angle) - 90.0) < 1.0)
        assertTrue(abs(meter.cosAngle) < 0.01)
    }
}
