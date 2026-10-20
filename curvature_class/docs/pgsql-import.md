# Importing simulated roads into PostgreSQL / PostGIS

How to get `out/lines_data.sql` (output of `generate_roads.py`) into the database,
into the `lines` table (defined in `lines.sql`).

All commands are run from the `curvature_class` directory. The Python scripts
write to `curvature_class/out/` regardless of the current directory.

## Prerequisites

- PostgreSQL with the **PostGIS** extension (`ST_GeomFromText`, `ST_Transform`, `geography`).
- The `psql` client.
- Recommended: **a separate test database**. If the database already contains a `lines`
  table from osm2pgsql, `lines.sql` fails (the table exists) and the simulated data would
  get mixed with the real data.

## Connection

Connection parameters can be given with switches (`-h`, `-p`, `-U`, `-d`) or with environment
variables, which `psql` reads automatically:

```bash
export PGHOST=localhost
export PGPORT=5432
export PGUSER=myuser
export PGDATABASE=curvature_test
```

You don't have to type the password every time; a `~/.pgpass` file is enough (permissions `chmod 600`):

```
localhost:5432:*:myuser:secret_password
```

Alternatively, one-off `PGPASSWORD=... psql ...` (but the password stays in the shell history).

## 1. Database and PostGIS (once)

```bash
createdb curvature_test
psql -d curvature_test -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

## 2. The `lines` table (once)

```bash
psql -d curvature_test -v ON_ERROR_STOP=1 -f sql/lines.sql
```

Creates the `lines` table in the shape `brouter.sql` works with after its initial
rebuild, plus indexes and the helper functions `merca_coef_lat()` and `merca_coef_y()`.
Running it again fails because the table already exists. For a completely clean start,
drop it first: `psql -d curvature_test -c "DROP TABLE lines;"`.

## 3. Generating and importing data (repeatedly)

```bash
python3 python/generate_roads.py --count 60 --seed 1
psql -d curvature_test -v ON_ERROR_STOP=1 -1 -f out/lines_data.sql
```

- `-v ON_ERROR_STOP=1` stops the import at the first error (otherwise `psql` keeps going).
- `-1` runs the whole file in a single transaction. On error, nothing is written.
- The script first deletes the roads from the previous run (only the range of simulated
  `osm_id` starting at `9000000000`), then inserts them again and computes `merca_coef` with the same
  expression as `brouter.sql`. So it can be run repeatedly.

Caution: `DELETE` only removes the id range of the current run. If you first generate 60
roads and then 36, roads `9000000036`–`9000000059` from the first run remain
in the table. Complete cleanup of the simulated data:

```bash
psql -d curvature_test -c "DELETE FROM lines WHERE osm_id LIKE '9%' AND length(osm_id) = 10;"
```

## 4. Checks

```bash
psql -d curvature_test -c "
SELECT
    highway,
    count(*) AS cnt,
    round(min(merca_coef)::numeric, 4) AS min_coef,
    round(max(merca_coef)::numeric, 4) AS max_coef
FROM lines
GROUP BY highway
ORDER BY highway;"
```

`merca_coef` should come out at approximately 1.55–1.56 (latitude 50.0–50.2°).

Length in metres computed three ways: via `merca_coef` (as `brouter.sql` does it),
via `geography` (exact on the ellipsoid) and the length from `out/roads.json`. All of them should
agree to within tenths of a percent:

```bash
psql -d curvature_test -c "
SELECT
    osm_id,
    highway,
    round((st_length (way) / merca_coef)::numeric, 1) AS len_merca_coef,
    round(st_length (ST_Transform (way, 4326)::geography)::numeric, 1) AS len_geography,
    round(merca_coef::numeric, 5) AS merca_coef,
    round(merca_coef_y (ST_Y (ST_Centroid (way)))::numeric, 5) AS merca_coef_approx
FROM lines
ORDER BY osm_id
LIMIT 10;"
```

## 5. Functions and curvature class

```bash
psql -d curvature_test -v ON_ERROR_STOP=1 -f sql/functions.sql
psql -d curvature_test -v ON_ERROR_STOP=1 -f sql/curvature_tags.sql
```

- `functions.sql` loads the functions `curv_resample`, `curv_radii`, `curv_bands`,
  `curv_metrics` and `curv_class` (see `metrics.md` for the procedure). It can be run repeatedly.
  When a function's parameters change, the old version must be dropped first
  (`DROP FUNCTION ...`), otherwise both versions remain in the database side by side.
  For `curv_class`, `functions.sql` does this itself (the old two-parameter version).
- `curvature_tags.sql` creates the table `curvature_tags (losmid, curvature_class)`
  and prints the number of ways in each class. Straight and short ways are not in it.

Score and class for each road:

```bash
psql -d curvature_test -c "
SELECT
    osm_id,
    highway,
    round(m.len_m::numeric) AS len_m,
    round(m.score::numeric, 2) AS score,
    curv_class (m.score) AS class_by_score,
    curv_class (m.score, shares => m.shares, n_radii => m.n_radii, step_m => m.step_m) AS curvature_class
FROM
    lines,
    LATERAL curv_metrics (way, merca_coef) AS m
ORDER BY
    m.score NULLS FIRST;"
```

## 6. Visualizing the result

```bash
python3 python/visualize_curvature.py --db curvature_test
```

Creates `out/roads_curvature.svg`: the same gallery as `out/roads.svg` (column =
road type, same order), but each tile has a badge with the computed class
from `curvature_tags` (light 1 → dark 6; "–" = no tag, "?" = too short).
Below the road are the score, the share and length in hairpins (R < 30 m) and the mark
"↑ hairpin rule" when the class was raised by the hairpin rule. Hovering the mouse
over a tile shows all values.

Values are read via `psql` (`PG*` variables, `~/.pgpass`). Without a database you can use
`--csv` with the output of the `QUERY` query from the script.

## Complete example

```bash
cd curvature_class

createdb curvature_test
psql -d curvature_test -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -d curvature_test -v ON_ERROR_STOP=1 -f sql/lines.sql

python3 python/generate_roads.py
psql -d curvature_test -v ON_ERROR_STOP=1 -1 -f out/lines_data.sql

psql -d curvature_test -c "SELECT count(*) FROM lines;"   # 60

psql -d curvature_test -v ON_ERROR_STOP=1 -f sql/functions.sql
psql -d curvature_test -v ON_ERROR_STOP=1 -f sql/curvature_tags.sql   # 30 ways with a class

python3 python/visualize_curvature.py --db curvature_test   # out/roads_curvature.svg
```

With a remote server, just add the connection parameters, e.g.
`psql -h db.example.com -p 5432 -U myuser -d curvature_test -v ON_ERROR_STOP=1 -1 -f out/lines_data.sql`.

## Viewing in QGIS

Browser → PostgreSQL → new connection to `curvature_test` → layer `lines`.
The geometry is in EPSG:3857, so it lines up directly with an OpenStreetMap basemap (XYZ Tiles).
The roads lie in a grid of roughly 25 × 25 km east of Prague (around Kolín),
50.0–50.2° N and 15.0–15.3° E.
