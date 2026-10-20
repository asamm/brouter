// Helpers shared by the tests. Same package as StdPath, so processWaySection (protected)
// and message are accessible.
package btools.router

import btools.expressions.BExpressionContextWay
import btools.expressions.BExpressionMetaData
import btools.util.CheapRuler
import java.io.File
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

private val lookupsFile = File("../../misc/profiles2/lookups.dat")

/**
 * RoutingContext with the way context evaluated from a minimal profile
 * with a constant turncost and costfactor.
 */
fun wayContext(turncost: Int, costfactor: Double = 1.0): RoutingContext {
    val profile = File.createTempFile("turncost$turncost-", ".brf").apply { deleteOnExit() }
    profile.writeText(
        """
        ---context:global
        ---context:way
        assign turncost = $turncost
        assign costfactor = $costfactor
        ---context:node
        assign initialcost = 0
        """.trimIndent() + "\n"
    )

    val meta = BExpressionMetaData()
    val expctxWay = BExpressionContextWay(meta)
    meta.readMetaData(lookupsFile)
    expctxWay.parseFile(profile, "global")

    val lookupData = expctxWay.createNewLookupData()
    expctxWay.addLookupValue("highway", "residential", lookupData)
    expctxWay.evaluate(false, expctxWay.encode(lookupData))

    val rc = RoutingContext()
    rc.expctxWay = expctxWay
    return rc
}

/** Result of the real StdPath.processWaySection for one flat section (no elevation). */
class Section(rc: RoutingContext, dist: Double, turn: Turn) {
    val cost: Double
    val turncost: Int

    init {
        val path = StdPath()
        path.message = MessageData()
        cost = path.processWaySection(rc, dist, 0.0, 100.0, turn.angle, turn.cosangle, false, 0, 0)
        turncost = path.message.linkturncost
    }
}

/**
 * Three points 0 -> 1 -> 2, 100 m each, turning by deg at point 1, angle and
 * cosine measured by the real CheapAngleMeter on integer coordinates.
 */
class Turn(deg: Double) {
    val angle: Double
    val cosangle: Double

    init {
        val rad = Math.toRadians(deg)
        val (lon0, lat0) = toILonLat(0.0, -100.0)
        val (lon1, lat1) = toILonLat(0.0, 0.0)
        val (lon2, lat2) = toILonLat(100.0 * sin(rad), 100.0 * cos(rad))

        val meter = RoutingContext().anglemeter
        angle = meter.calcAngle(lon0, lat0, lon1, lat1, lon2, lat2)
        cosangle = meter.cosAngle
    }
}

/**
 * Local metric plane (x = east, y = north, metres, as points_local in out/roads.json)
 * -> BRouter integer coordinates: ilon = (lon + 180) * 1e6, ilat = (lat + 90) * 1e6.
 * The origin is 15.0 E / 50.0 N. The metre scale is taken at the origin (CheapRuler,
 * the same scales BRouter uses); over a few km its change is far below 0.1 %.
 * Rounding to whole microdegrees (~0.07 m east, ~0.11 m north) is the same
 * quantization real map data has.
 */
fun toILonLat(x: Double, y: Double): Pair<Int, Int> {
    val originILon = 195_000_000 // 15.0 E
    val originILat = 140_000_000 // 50.0 N
    val (lon2m, lat2m) = CheapRuler.getLonLatToMeterScales(originILat).let { it[0] to it[1] }
    return (originILon + (x / lon2m).roundToInt()) to (originILat + (y / lat2m).roundToInt())
}
