--  functions for the calculation of the curvature of lines (estimated_curvature_class)
--  requires PostGIS >= 2.5 (ST_LineInterpolatePoints)

SET client_encoding TO UTF8;

-- ---------------------------------------------------------------------------
--  curv_resample
-- ---------------------------------------------------------------------------
--  Resamples a line to points with equal spacing in real meters, as the first
--  step of the curvature calculation.
--  Why: the density of vertices in OSM depends on the mapper, not on the road.
--  Metrics computed from the original vertices would measure the mapping style.
--
--  Input:
--    way         linestring in EPSG:3857 (table lines)
--    merca_coef  scale factor of the Mercator projection for this line (see lines.sql)
--    step        wanted spacing of the points in real meters (default 10)
--
--  Output (one row):
--    x, y        coordinates of the points in real meters, relative to the
--                start point of the line (x = east, y = north), i.e. the first
--                point is always (0, 0) and the last one is the end of the line.
--                The next steps are then plain arithmetic, no PostGIS, no Mercator.
--    step_m      real spacing used: length / n, so the points are equally spaced
--                incl. both ends (no shorter rest at the end)
--
--  Number of points: n + 1, n = greatest(2, round(length / step)).
--  At least 3 points, so even a very short line gets one radius later.
--  The spacing is measured along the line; on curves the straight distance
--  between two points (chord) is slightly shorter, e.g. on a hairpin with
--  R = 7 m and step 10 m the chord is 9.2 m.
--
--  The step defines the smallest curve radius which can be recognized: a sharp
--  corner drawn by one OSM vertex appears as a curve with a radius of about
--  half the step (~5 m for step 10 m).
--
--  NULL geometry, empty / zero length line or a non-linestring => x, y, step_m are NULL.
CREATE OR REPLACE FUNCTION curv_resample (way geometry, merca_coef double precision, step double precision DEFAULT 10, OUT x double precision[], OUT y double precision[], OUT step_m double precision)
LANGUAGE plpgsql
IMMUTABLE PARALLEL SAFE
AS $$
DECLARE
    len_m double precision;
    n integer;
    x0 double precision;
    y0 double precision;
    pts geometry;
BEGIN
    IF way IS NULL OR merca_coef IS NULL OR merca_coef <= 0 OR step IS NULL OR step <= 0 OR GeometryType (way) <> 'LINESTRING' THEN
        RETURN;
    END IF;
    len_m := ST_Length (way) / merca_coef;
    IF len_m = 0 THEN
        RETURN;
    END IF;
    n := greatest (2, round(len_m / step)::integer);
    step_m := len_m / n;
    -- origin of the local coordinates = start point of the line
    x0 := ST_X (ST_StartPoint (way));
    y0 := ST_Y (ST_StartPoint (way));
    -- points at the fractions 1/n, 2/n ... 1 (the start point is not returned)
    pts := ST_LineInterpolatePoints (way, 1.0 / n, TRUE);
    SELECT
        array_agg((ST_X (d.geom) - x0) / merca_coef ORDER BY d.path),
        array_agg((ST_Y (d.geom) - y0) / merca_coef ORDER BY d.path) INTO x,
        y
    FROM
        ST_DumpPoints (pts) AS d;
    -- add the start point
    x := 0::double precision || x;
    y := 0::double precision || y;
    -- by rounding of 1/n the last point (end of the line) may be missing
    -- (tested: ~5 % of n in 2..3000, never an extra point)
    IF array_length(x, 1) < n + 1 THEN
        x := x || (ST_X (ST_EndPoint (way)) - x0) / merca_coef;
        y := y || (ST_Y (ST_EndPoint (way)) - y0) / merca_coef;
    END IF;
END;
$$;

--  Tests (simulated roads from generate_roads.py):
--
--    -- number of points, spacing, the last point must be the end of the line (end_err_m ~ 0)
--    SELECT
--        osm_id,
--        highway,
--        round((st_length (way) / merca_coef)::numeric, 1) AS len_m,
--        array_length(r.x, 1) AS pts,
--        round(r.step_m::numeric, 2) AS step_m,
--        round(sqrt(power(r.x[array_upper(r.x, 1)] - (ST_X (ST_EndPoint (way)) - ST_X (ST_StartPoint (way))) / merca_coef, 2)
--                 + power(r.y[array_upper(r.y, 1)] - (ST_Y (ST_EndPoint (way)) - ST_Y (ST_StartPoint (way))) / merca_coef, 2))::numeric, 3) AS end_err_m
--    FROM
--        lines,
--        LATERAL curv_resample (way, merca_coef) AS r
--    ORDER BY
--        osm_id;
--
--    -- min / max distance between consecutive points (chord): max = step_m, min < step_m on tight curves
--    SELECT
--        osm_id,
--        round(min(d)::numeric, 2) AS min_chord,
--        round(max(d)::numeric, 2) AS max_chord
--    FROM (
--        SELECT
--            osm_id,
--            sqrt(power(r.x[i + 1] - r.x[i], 2) + power(r.y[i + 1] - r.y[i], 2)) AS d
--        FROM
--            lines,
--            LATERAL curv_resample (way, merca_coef) AS r,
--            generate_series(1, array_length(r.x, 1) - 1) AS i) a
--    GROUP BY
--        osm_id
--    ORDER BY
--        osm_id;
--
--    -- resampled points as geometry, e.g. for QGIS (back to EPSG:3857)
--    SELECT
--        osm_id,
--        i,
--        ST_SetSRID (ST_MakePoint (ST_X (ST_StartPoint (way)) + r.x[i] * merca_coef, ST_Y (ST_StartPoint (way)) + r.y[i] * merca_coef), 3857) AS geom
--    FROM
--        lines,
--        LATERAL curv_resample (way, merca_coef) AS r,
--        generate_series(1, array_length(r.x, 1)) AS i;

-- ---------------------------------------------------------------------------
--  curv_radii
-- ---------------------------------------------------------------------------
--  Radius of the curve in each point of a resampled line (output of curv_resample).
--
--  Input:
--    x, y   coordinates in meters (curv_resample), equally spaced points
--    k      the radius in point i is computed from the points i-k, i, i+k
--           (default 2, base 4 * step; k = 1 = direct neighbours, see the note about k below)
--
--  Output: array with the same length as x
--    r[i]   signed radius in meters: + = left curve, - = right curve
--           'Infinity' for 3 points in a line (straight)
--           |P1 P2| / 2 for a 180 deg turn back (P1 = P3), sign +
--           NULL for the first and last k points (no neighbour on one side)
--
--  Radius of the circle through 3 points P1, P2, P3 (circumscribed circle):
--    a = |P1 P2|, b = |P2 P3|, c = |P1 P3|
--    cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)    (= 2 * signed area of the triangle)
--    R = a * b * c / (2 * |cross|), sign of cross = direction of the curve
--
--  Note about k: a curve in OSM is a polyline, the curvature is concentrated in
--  the vertices. If the vertices are farther apart than the resampling step,
--  3 neighbouring points may all lie on one straight piece => R = Infinity,
--  although the road is curved. A bigger k (wider base 2 * k * step) smooths this,
--  but blurs short tight curves (hairpins).
--
--  Test against the ground truth of the 60 simulated roads (out/roads.json),
--  step 10 m, bands 30 / 60 / 100 / 175 m; "wrong share" = share of the road
--  length assigned to a wrong band (mean over roads):
--     k = 1: 11.0 %  hairpins exact (serpentines 25 % true / 27 % computed),
--                    gentle curves (R 60..175 m) often seen as straight / too tight
--                    (only 33 % of the points with R 100..175 m in the right band)
--     k = 2: 10.9 %  curves R 60..175 m ok (99 %), hairpins slightly overestimated (+5 %),
--                    short roads lose 2 points at each end (a 36 m road has 1 radius)
--     k = 3: 14.2 %  too much smoothing
--  Points inside an arc (window not crossing a straight / arc boundary): median
--  |R| / R_true = 1.00 for all k. The errors come from the boundaries of curves and
--  from the polyline vertices of the generator (vertex spacing R / 4, 3..20 m).
CREATE OR REPLACE FUNCTION curv_radii (x double precision[], y double precision[], k integer DEFAULT 2)
    RETURNS double precision[]
    LANGUAGE plpgsql
    IMMUTABLE PARALLEL SAFE
    AS $$
DECLARE
    n integer := array_length(x, 1);
    r double precision[];
    a double precision;
    b double precision;
    c double precision;
    cross_p double precision;
BEGIN
    IF n IS NULL OR k IS NULL OR k < 1 THEN
        RETURN NULL;
    END IF;
    r := array_fill(NULL::double precision, ARRAY[n]);
    FOR i IN k + 1..n - k LOOP
        a := sqrt(power(x[i] - x[i - k], 2) + power(y[i] - y[i - k], 2));
        b := sqrt(power(x[i + k] - x[i], 2) + power(y[i + k] - y[i], 2));
        c := sqrt(power(x[i + k] - x[i - k], 2) + power(y[i + k] - y[i - k], 2));
        cross_p := (x[i] - x[i - k]) * (y[i + k] - y[i - k]) - (y[i] - y[i - k]) * (x[i + k] - x[i - k]);
        IF cross_p = 0 AND (x[i] - x[i - k]) * (x[i + k] - x[i]) + (y[i] - y[i - k]) * (y[i + k] - y[i]) < 0 THEN
            -- points in a line, but the road goes back (180 deg turn): the tightest
            -- possible curve, circle with the diameter |P1 P2|; direction unknown => +
            r[i] := (a + b) / 4;
        ELSIF cross_p = 0 THEN
            r[i] := 'Infinity';
        ELSE
            r[i] := sign(cross_p) * a * b * c / (2 * abs(cross_p));
        END IF;
    END LOOP;
    RETURN r;
END;
$$;

--  Tests:
--
--    -- radii of the simulated roads (|R| in m, rounded)
--    SELECT
--        osm_id,
--        highway,
--        (
--            SELECT
--                array_agg(round(abs(v)::numeric) ORDER BY i)
--            FROM
--                unnest(curv_radii (r.x, r.y)) WITH ORDINALITY AS u (v, i)) AS radii
--    FROM
--        lines,
--        LATERAL curv_resample (way, merca_coef) AS r
--    ORDER BY
--        osm_id;

-- ---------------------------------------------------------------------------
--  curv_bands
-- ---------------------------------------------------------------------------
--  Shares of the line length in radius bands + weighted score (metric M3, see metrics.md).
--
--  Input:
--    r        radii from curv_radii (signed, 'Infinity' = straight, NULL = no radius)
--    limits   upper limits of the bands in meters, ascending (n limits => n + 1 bands)
--             default {30, 60, 100, 175}: bands <30 | 30-60 | 60-100 | 100-175 | >=175
--    weights  weight of each band (n + 1 values), default {2, 1.6, 1.3, 1, 0}
--             (bands and weights from the project Curvature, see sources.md)
--    min_radii  minimal number of radii for a result (default 5, see below)
--
--  Output (one row):
--    shares   share of the length in each band (0..1, sum = 1), same order as weights
--    score    weighted share = sum(shares[i] * weights[i]), 0 = straight,
--             max = max(weights) (whole line in the tightest band)
--    n_radii  number of points with a radius (= points used for the shares)
--
--  Each resampled point represents the same length (step), so the share of the
--  length = share of the points. Points without a radius (first and last k
--  points of the line) are ignored.
--  min_radii: with fewer radii the result is not reliable (e.g. a 36 m street
--  with one corner would get the max. score) => shares, score NULL
--  (curvature class undefined), n_radii is returned anyway.
--  Default 5 = line of ~90 m with step 10 m and k = 2.
--  Limits and weights are parameters, so they can be tuned without changing the code.
CREATE OR REPLACE FUNCTION curv_bands (r double precision[], limits double precision[] DEFAULT '{30, 60, 100, 175}', weights double precision[] DEFAULT '{2, 1.6, 1.3, 1, 0}', min_radii integer DEFAULT 5, OUT shares double precision[], OUT score double precision, OUT n_radii integer)
LANGUAGE plpgsql
IMMUTABLE PARALLEL SAFE
AS $$
DECLARE
    nb integer := array_length(limits, 1) + 1;
    cnt integer[];
    v double precision;
    b integer;
BEGIN
    IF array_length(weights, 1) IS DISTINCT FROM nb THEN
        RAISE EXCEPTION 'curv_bands: % limits need % weights, got %', nb - 1, nb, coalesce(array_length(weights, 1), 0);
    END IF;
    cnt := array_fill(0, ARRAY[nb]);
    n_radii := 0;
    FOREACH v IN ARRAY coalesce(r, '{}') LOOP
        CONTINUE WHEN v IS NULL;
        -- band = first limit bigger than |R|, else the last band (straight)
        b := nb;
        FOR j IN 1..nb - 1 LOOP
            IF abs(v) < limits[j] THEN
                b := j;
                EXIT;
            END IF;
        END LOOP;
        cnt[b] := cnt[b] + 1;
        n_radii := n_radii + 1;
    END LOOP;
    IF n_radii = 0 OR n_radii < min_radii THEN
        RETURN;
    END IF;
    shares := array_fill(0::double precision, ARRAY[nb]);
    score := 0;
    FOR j IN 1..nb LOOP
        shares[j] := cnt[j]::double precision / n_radii;
        score := score + shares[j] * weights[j];
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
--  curv_metrics
-- ---------------------------------------------------------------------------
--  All steps for one line: curv_resample -> curv_radii -> curv_bands.
--
--    SELECT osm_id, m.*
--    FROM lines, LATERAL curv_metrics (way, merca_coef) AS m;
--
--  Input:
--    way, merca_coef    line in EPSG:3857 and its scale factor (table lines)
--    step               resampling step in meters (curv_resample)
--    k                  neighbour distance for the radius (curv_radii)
--    limits, weights, min_radii    bands and weights (curv_bands)
--
--  Output: len_m (real length), step_m, shares, score, n_radii (see curv_bands).
--  score NULL = curvature class undefined (line too short, n_radii < min_radii),
--  also all NULL for an invalid input (see curv_resample).
--  The class is computed from the score by curv_class.
CREATE OR REPLACE FUNCTION curv_metrics (way geometry, merca_coef double precision, step double precision DEFAULT 10, k integer DEFAULT 2, limits double precision[] DEFAULT '{30, 60, 100, 175}', weights double precision[] DEFAULT '{2, 1.6, 1.3, 1, 0}', min_radii integer DEFAULT 5, OUT len_m double precision, OUT step_m double precision, OUT shares double precision[], OUT score double precision, OUT n_radii integer)
LANGUAGE plpgsql
IMMUTABLE PARALLEL SAFE
AS $$
DECLARE
    rs record;
    bd record;
BEGIN
    rs := curv_resample (way, merca_coef, step);
    IF rs.x IS NULL THEN
        RETURN;
    END IF;
    len_m := ST_Length (way) / merca_coef;
    step_m := rs.step_m;
    bd := curv_bands (curv_radii (rs.x, rs.y, k), limits, weights, min_radii);
    shares := bd.shares;
    score := bd.score;
    n_radii := bd.n_radii;
END;
$$;

--  Tests:
--
--    -- shares in % and score per road
--    SELECT
--        osm_id,
--        highway,
--        round(m.len_m::numeric) AS len_m,
--        (
--            SELECT
--                array_agg(round((100 * s)::numeric) ORDER BY i)
--            FROM
--                unnest(m.shares) WITH ORDINALITY AS u (s, i)) AS shares_pct,
--        round(m.score::numeric, 2) AS score
--    FROM
--        lines,
--        LATERAL curv_metrics (way, merca_coef) AS m
--    ORDER BY
--        m.score;
--
--    -- other bands / weights, e.g. hairpins below 15 m separately
--    SELECT osm_id, m.*
--    FROM lines, LATERAL curv_metrics (way, merca_coef, limits => '{15, 30, 60, 100, 175}', weights => '{2.5, 2, 1.6, 1.3, 1, 0}') AS m;

-- ---------------------------------------------------------------------------
--  curv_class
-- ---------------------------------------------------------------------------
--  Converts the score (curv_bands / curv_metrics) to estimated_curvature_class.
--
--    limits      ascending lower bounds of the classes '1', '2', ... (default 6 classes)
--
--  Default limits (calibrated on the simulated roads, to be tuned on real OSM data):
--
--    score         class   meaning                 simulated roads
--    < 0.10        NULL    straight / gentle       straight, gentle, slightly winding
--    0.10 - 0.25   '1'     occasional curve        winding
--    0.25 - 0.45   '2'     wavy                    winding
--    0.45 - 0.70   '3'     curvy                   urban
--    0.70 - 1.00   '4'     very curvy              urban (serpentine without the hairpin rule)
--    1.00 - 1.30   '5'     mountain road           mountain, serpentine (hairpin rule)
--    >= 1.30       '6'     extreme                 mountain
--
--  NULL (no tag) for a straight line and for an undefined score (line too short),
--  like the other classes in brouter.sql, where low values get no row in *_tags.
--
--  Hairpin rule (optional, off when shares is NULL):
--    shares, n_radii, step_m   output of curv_metrics
--    hairpin_share   min. share of the first band (R < 30 m with the default bands)
--    hairpin_min_m   min. length in the first band in meters (shares[1] * n_radii * step_m)
--    hairpin_class   the class is raised at least to this value
--  Why: serpentines have a lower score than mountain roads (long straights between
--  the hairpins), but they are as much fun. Both conditions are needed: a short
--  urban street with one or two corners has also >= 25 % "hairpins" (the window
--  k = 2 spreads a corner to ~3 points), but only 30..60 m of them.
--  Simulated roads (step 10 m, k = 2): serpentines 26..34 %, 120..460 m => class 5;
--  urban 28 % / 50..60 m and 17 % / 90 m => unchanged.
--  With other bands (e.g. {15, 30, ...}) shares[1] is only the tightest band.
--
--  The old version with 2 parameters must be dropped, otherwise curv_class (score)
--  is ambiguous (both versions match with their defaults).
DROP FUNCTION IF EXISTS curv_class (double precision, double precision[]);

CREATE OR REPLACE FUNCTION curv_class (score double precision, limits double precision[] DEFAULT '{0.1, 0.25, 0.45, 0.7, 1.0, 1.3}', shares double precision[] DEFAULT NULL, n_radii integer DEFAULT NULL, step_m double precision DEFAULT NULL, hairpin_share double precision DEFAULT 0.25, hairpin_min_m double precision DEFAULT 100, hairpin_class integer DEFAULT 5)
    RETURNS text
    LANGUAGE plpgsql
    IMMUTABLE PARALLEL SAFE
    AS $$
DECLARE
    cls integer := 0;
BEGIN
    IF score IS NULL THEN
        RETURN NULL;
    END IF;
    FOR j IN 1..coalesce(array_length(limits, 1), 0) LOOP
        IF score >= limits[j] THEN
            cls := j;
        END IF;
    END LOOP;
    -- many hairpins: at least hairpin_class (NULL shares / n_radii / step_m => rule off)
    IF shares[1] >= hairpin_share AND shares[1] * n_radii * step_m >= hairpin_min_m THEN
        cls := greatest (cls, hairpin_class);
    END IF;
    IF cls = 0 THEN
        RETURN NULL;
    END IF;
    RETURN cls::text;
END;
$$;

--  Tests:
--
--    SELECT s, curv_class (s)
--    FROM unnest('{NULL, 0, 0.0999, 0.1, 0.25, 0.449, 0.7, 1.0, 1.3, 2}'::double precision[]) AS s;
--
--    -- hairpin rule: expected '5', '3' (only 60 m), '3' (only 20 %), '6' (never lowered), '3' (rule off)
--    SELECT
--        curv_class (0.6, shares => '{0.3, 0, 0, 0, 0.7}', n_radii => 50, step_m => 10),
--        curv_class (0.6, shares => '{0.3, 0, 0, 0, 0.7}', n_radii => 20, step_m => 10),
--        curv_class (0.6, shares => '{0.2, 0, 0, 0, 0.8}', n_radii => 100, step_m => 10),
--        curv_class (1.5, shares => '{0.3, 0, 0, 0, 0.7}', n_radii => 50, step_m => 10),
--        curv_class (0.6);
--
--    -- roads where the hairpin rule changes the class
--    SELECT osm_id, highway, curv_class (m.score) AS by_score,
--        curv_class (m.score, shares => m.shares, n_radii => m.n_radii, step_m => m.step_m) AS with_rule
--    FROM lines, LATERAL curv_metrics (way, merca_coef) AS m
--    WHERE curv_class (m.score) IS DISTINCT FROM curv_class (m.score, shares => m.shares, n_radii => m.n_radii, step_m => m.step_m);
