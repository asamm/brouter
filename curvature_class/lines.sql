--  table "lines" as rebuilt at the beginning of brouter.sql (lines 8-57)
--  = the table the rest of brouter.sql really works with
--  column order and types match the result of "SELECT ... INTO TABLE lines_bis FROM lines"
--  (SELECT INTO keeps the type incl. typmod of plain columns, but no NOT NULL constraints)

SET client_encoding TO UTF8;

CREATE TABLE lines (
    osm_id text,
    highway text,
    way geometry(LineString, 3857),
    waterway text,
    "natural" text, -- reserved word: must be quoted here, in brouter.sql always used as li.natural
    width text,
    oneway text,
    tunnel text,
    bridge text,
    nodes jsonb, -- array of node ids, e.g. [123, 456, 789]
    maxspeed text, -- already converted from mph to km/h (e.g. '48.30')
    junction text,
    lanes text,
    bicycle text,
    merca_coef double precision, -- st_length(way) / st_length(ST_Transform(way, 4326)::geography)
    crossing text,
    crossing_markings text
);

CREATE INDEX lines_osm_id_idx ON lines (osm_id) WITH (fillfactor = '100');

CREATE INDEX lines_way_idx ON public.lines USING gist (way) WITH (fillfactor = '100');

-- ---------------------------------------------------------------------------
--  merca_coef
-- ---------------------------------------------------------------------------
--  Meaning:
--    merca_coef = (length in EPSG:3857 units) / (real length in meters)
--    = local scale factor of the Web Mercator projection
--    = how many "Mercator meters" correspond to 1 real meter at this place.
--
--  Why: all geometries are in 3857 and planar functions (st_length, st_distance,
--  ST_Buffer, ST_DWithin) on them are fast and use the GiST index, but
--  3857 distances are inflated with growing latitude. The coefficient converts
--  between both units:
--    real meters  -> 3857 units : multiply  e.g. ST_Buffer(way, 75 * merca_coef)  = 75 real m
--    3857 units   -> real meters: divide    e.g. st_distance(a, b) / merca_coef  = distance in m
--  (geography based calculation gives the same result, but is ~7 x slower, see brouter.sql)
--
--  Calculation from the latitude (outside the table):
--    Web Mercator projects WGS84 lon/lat as if the earth were a sphere with R = 6378137 m:
--      x = R * lon_rad
--      y = R * ln(tan(pi/4 + lat_rad/2))
--    hence the scale factor depends only on the latitude:
--      merca_coef ~ 1 / cos(lat)
--    or directly from the 3857 y coordinate (no ST_Transform needed):
--      merca_coef ~ cosh(y / 6378137)
--
--      lat    1/cos(lat)
--       0°    1.000
--      30°    1.155
--      45°    1.414
--      50°    1.556   (Czech Republic: ~1.51 .. 1.59)
--      60°    2.000
--      70°    2.924
--
--  Accuracy: brouter.sql measures the real length on the WGS84 ellipsoid (geography),
--  so the exact value differs slightly from 1/cos(lat) and also depends on the direction:
--      east-west line:   sqrt(1 - e2 * sin(lat)^2) / cos(lat)
--      north-south line: (1 - e2 * sin(lat)^2)^1.5 / ((1 - e2) * cos(lat))
--      e2 = 0.00669438 (WGS84 eccentricity squared)
--    At 50° this gives 1.5527 (E-W) and 1.5570 (N-S) vs. 1.5557 for 1/cos(lat),
--    i.e. 1/cos(lat) differs by less than 0.7 % anywhere (0.3 % in Central Europe).
--    That is negligible for thresholds like "within 75 m".
--  The table value is an average along the whole line, which is why brouter.sql
--  ignores lines longer than 40 km.
--
--  Helper functions for tests:

--  merca_coef from the latitude in degrees (WGS84), spherical approximation 1 / cos(lat)
CREATE OR REPLACE FUNCTION merca_coef_lat (lat double precision)
    RETURNS double precision
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        1 / cos(radians(lat));
$$;

--  merca_coef from the y coordinate in EPSG:3857 (meters), = 1 / cos(lat),
--  because lat = 2 * atan(exp(y / R)) - pi / 2, R = 6378137 (Web Mercator sphere)
CREATE OR REPLACE FUNCTION merca_coef_y (y double precision)
    RETURNS double precision
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        cosh(y / 6378137);
$$;

--  Examples:
--    SELECT merca_coef_lat(50);                              -- 1.5557
--    SELECT merca_coef_y(ST_Y(ST_Centroid(way))) FROM lines; -- per line, from 3857 coordinates
--
--    -- compare with the value brouter.sql stores in the table:
--    SELECT
--        osm_id,
--        ST_Y (ST_Transform (ST_Centroid (way), 4326)) AS lat,
--        merca_coef,
--        merca_coef_y (ST_Y (ST_Centroid (way))) AS merca_coef_approx,
--        (merca_coef_y (ST_Y (ST_Centroid (way))) / merca_coef - 1) * 100 AS diff_pct
--    FROM
--        lines
--    LIMIT 20;
