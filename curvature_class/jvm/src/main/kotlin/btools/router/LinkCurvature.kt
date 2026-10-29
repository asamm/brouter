// Kotlin port of the runtime curvature of one link, for study before the implementation
// in OsmPath / StdPath. No BRouter dependency: the inputs are the per-section values that
// OsmPath.addAddionalPenalty already computes.
package btools.router

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min

/**
 * Curvature factor c of one link, 0.0 - 1.0: M3 weights + serpentine rule (variant 2).
 *
 * Algorithm and results: docs/runtime-curvature-window.md. Ported from
 * python/curvature_window.py (`runtime_bands`) and python/curvature_variants.py
 * (`c_weights`, `serpentine`, `c_variant2`).
 *
 * Pipeline for one link:
 *  1. junction angle: angle[0] is road shape at a link boundary, kept unless it is a real
 *     turn (|angle[0]| > junctionMaxDeg) or the start of the route,
 *  2. smearing: every vertex angle rises linearly over its surroundings, giving the
 *     cumulative turning Theta(s), a piecewise linear function of the arc length s,
 *  3. window: net turning |Theta(s + W/2) - Theta(s - W/2)| over the window gives the
 *     radius R = window length / turning; each piece of a section goes to the band of R,
 *  4. c = M3 weighted mean of the band lengths / 2; a serpentine link is raised to serpC;
 *     capped at maxC.
 *
 * In OsmPath the sum of the section costs of the link is multiplied by 1 - c
 * (docs/runtime-curvature-window.md, "Integration into OsmPath / StdPath").
 *
 * Usage:
 *   val c = LinkCurvature().compute(dist, angle, isRouteStart).c
 */
class LinkCurvature(private val params: Params = Params()) {

    data class Params(
        /** window length W in m (40 m ~ SQL radius through points i-2, i, i+2 at a 10 m step) */
        val window: Double = 40.0,
        /** |angle[0]| above this is a real turn at the junction, not road shape */
        val junctionMaxDeg: Double = 90.0,
        /** shorter links get no value, c = 0 (neutral) */
        val minLength: Double = 40.0,
        /** max. distance a vertex angle is smeared to each side, in m */
        val spreadCap: Double = 10.0,
        /** serpentine rule: number of tight bands counted from the hairpin one (2 = R < 60 m) */
        val serpBands: Int = 2,
        /** serpentine rule: min. share of the link length in tight curves */
        val serpShare: Double = 0.2,
        /** serpentine rule: min. length in tight curves, in m */
        val serpMinLength: Double = 35.0,
        /** serpentine rule: c is raised at least to this */
        val serpC: Double = 0.8,
        /** cap of c: the link cost is multiplied by 1 - c, so a link costs at least a tenth */
        val maxC: Double = 0.9,
    )

    /**
     * Result for one link.
     *
     * @property c curvature factor 0.0 - maxC, 0 for a short link
     * @property bands length in m in each radius band, index as in [WEIGHTS]; null for a short link
     * @property serpentine the serpentine rule fired
     */
    class Result(val c: Double, val bands: DoubleArray?, val serpentine: Boolean)

    /**
     * Curvature of one link.
     *
     * @param dist length of section i (point i -> i+1) in m, as rc.calcDistance in OsmPath
     * @param angle signed turn angle at point i in degrees, as CheapAngleMeter.calcAngle;
     *  angle[0] is the turn at the source node relative to the last point of the previous link
     * @param isRouteStart the link starts the route, angle[0] has no meaning
     */
    fun compute(dist: IntArray, angle: DoubleArray, isRouteStart: Boolean): Result {
        val bands = bands(dist, angle, isRouteStart) ?: return Result(0.0, null, false)
        var c = cWeights(bands)
        val serpentine = isSerpentine(bands)
        if (serpentine) {
            c = max(c, params.serpC)
        }
        return Result(min(c, params.maxC), bands, serpentine)
    }

    // ------------------------------------------------------------------ steps 1 - 3

    /** Length of the link in each radius band, null for a link shorter than minLength. */
    fun bands(dist: IntArray, angle: DoubleArray, isRouteStart: Boolean): DoubleArray? {
        val n = dist.size
        val length = dist.sum().toDouble()
        if (length < params.minLength) {
            return null
        }

        // step 1: angle[0] is kept as road shape, except at the route start or a real turn
        val ang = DoubleArray(n) { Math.toRadians(angle[it]) }
        if (isRouteStart || abs(angle[0]) > params.junctionMaxDeg) {
            ang[0] = 0.0
        }

        // step 2: knots of Theta(s). The angle of vertex i rises linearly over
        // [s_i - left, s_i + right], left / right = half of the neighbouring section,
        // capped at spreadCap; vertex 0 has nothing on its left (the previous link is
        // not part of this one). Two knots per vertex plus the start and the end;
        // the knot positions never decrease, so a forward cursor can walk them.
        val ks = DoubleArray(2 * n + 2)
        val kt = DoubleArray(2 * n + 2)
        var k = 1                    // ks[0] = kt[0] = 0
        var s = 0.0
        var t = 0.0
        var prev = 0.0
        for (i in 0 until n) {
            val d = dist[i].toDouble()
            ks[k] = s - min(prev / 2.0, params.spreadCap)
            kt[k++] = t
            t += ang[i]
            ks[k] = s + min(d / 2.0, params.spreadCap)
            kt[k++] = t
            s += d
            prev = d
        }
        ks[k] = length
        kt[k] = t

        // step 3: the window centred in each piece of a section (pieces <= W/2); the net
        // turning in it gives the radius, the piece length goes to the band of the radius.
        // lo and hi only move forward, so two cursors give O(n + number of pieces).
        val half = params.window / 2.0
        val lo = Theta(ks, kt)
        val hi = Theta(ks, kt)
        val bands = DoubleArray(WEIGHTS.size)
        s = 0.0
        for (i in 0 until n) {
            val d = dist[i].toDouble()
            val pieces = max(1, ceil(d / half).toInt())
            val piece = d / pieces
            for (q in 0 until pieces) {
                val x = s + (q + 0.5) * piece
                val a = max(0.0, x - half)
                val b = min(length, x + half)
                val turn = abs(hi.at(b) - lo.at(a))
                bands[bandIndex(b - a, turn)] += piece
            }
            s += d
        }
        return bands
    }

    /**
     * Theta(x) on the knots ks / kt, linear between them, for x that never decreases
     * between calls (the cursor j only moves forward; Python uses bisect instead).
     */
    private class Theta(private val ks: DoubleArray, private val kt: DoubleArray) {
        private var j = 0

        fun at(x: Double): Double {
            // j = last knot with ks[j] <= x (bisect_right - 1 in Python)
            while (j + 1 < ks.size && ks[j + 1] <= x) {
                j++
            }
            if (j + 1 >= ks.size) {
                return kt[j]
            }
            // here ks[j] <= x < ks[j + 1], so the knots differ
            return kt[j] + (kt[j + 1] - kt[j]) * (x - ks[j]) / (ks[j + 1] - ks[j])
        }
    }

    // ------------------------------------------------------------------ step 4

    /** M3: length-weighted mean of the band weights / 2, clipped at 1. */
    private fun cWeights(bands: DoubleArray): Double {
        var sum = 0.0
        var length = 0.0
        for (i in bands.indices) {
            sum += bands[i] * WEIGHTS[i]
            length += bands[i]
        }
        return min(1.0, sum / length / 2.0)
    }

    /**
     * Serpentine rule (hairpin rule of curv_class in sql/functions.sql, adapted to one link):
     * both the share and the length in tight curves must reach the thresholds. The share
     * separates serpentines from long gentle bends, the length a chain of bends from a
     * single junction corner.
     */
    private fun isSerpentine(bands: DoubleArray): Boolean {
        var tight = 0.0
        for (i in 0 until params.serpBands) {
            tight += bands[i]
        }
        val share = tight / bands.sum()
        return share >= params.serpShare && tight >= params.serpMinLength
    }

    companion object {
        /** radius band limits in m: hairpin < 30, sharp < 60, medium < 100, gentle < 175, straight */
        val LIMITS = doubleArrayOf(30.0, 60.0, 100.0, 175.0)

        /** M3 weights per band, hairpin ... straight (curv_bands in sql/functions.sql) */
        val WEIGHTS = doubleArrayOf(2.0, 1.6, 1.3, 1.0, 0.0)

        /**
         * Band of the radius R = windowLength / turn (turn in radians), as band_index in
         * Python. Without the division: R < limit  <=>  turn * limit > windowLength,
         * which also covers turn = 0 (R = infinity, straight).
         */
        fun bandIndex(windowLength: Double, turn: Double): Int {
            for (i in LIMITS.indices) {
                if (turn * LIMITS[i] > windowLength) {
                    return i
                }
            }
            return LIMITS.size
        }
    }
}
