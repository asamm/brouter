--  calculation of the new tag estimated_curvature_class (proof of concept)
--  requires functions.sql
--
--  Same shape as noise_tags, river_tags... in brouter.sql: one row per way with
--  a class '1'..'6', no row for straight / too short ways (no tag).
--  To be merged into all_tags in brouter.sql:
--      ... NATURAL FULL OUTER JOIN curvature_tags
--
--  Only roads for motor vehicles. lines contains also waterway / coastline.
--  *_link are left out: motorway ramps and loops look like hairpins, but are no fun.
--  Hairpin rule of curv_class: >= 25 % and >= 100 m in R < 30 m => at least class '5'.
SELECT
    now();

DROP TABLE IF EXISTS curvature_tags;

SELECT
    losmid,
    curvature_class INTO TABLE curvature_tags
FROM (
    SELECT
        l.osm_id::bigint AS losmid,
        curv_class (m.score, shares => m.shares, n_radii => m.n_radii, step_m => m.step_m) AS curvature_class
    FROM
        lines l,
        LATERAL curv_metrics (l.way, l.merca_coef) AS m
    WHERE
        l.highway IN ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'living_street')) AS q
WHERE
    curvature_class IS NOT NULL
ORDER BY
    curvature_class;

SELECT
    now();

ANALYZE curvature_tags;

SELECT
    count(*)
FROM
    curvature_tags;

SELECT
    curvature_class,
    count(*)
FROM
    curvature_tags
GROUP BY
    curvature_class
ORDER BY
    curvature_class;
