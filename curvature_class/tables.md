# Source tables for `brouter.sql`

The tables are created by `osm2pgsql` (flex output) according to the `brouter_cfg.lua` configuration.
The description corresponds to osm2pgsql 1.11 (the locally installed version).

Common properties:

- **SRID 3857** (Web Mercator) for all geometries (`local srid = 3857`).
  Distances and lengths in these coordinates are not real metres, so `brouter.sql`
  converts them using the `merca_coef` coefficient.
- **All attributes from OSM tags are `text`**, including numeric values
  (`maxspeed`, `lanes`, `width`, `population`, `ele`). Conversion to numbers is done only in
  `brouter.sql` (`::numeric`, `::bigint`, `isnumeric()`, regexes).
- **`osm_id` is `text`** (an explicit column filled with `object.id`). Alongside it,
  osm2pgsql automatically adds its own id column of type `int8` (`way_id`,
  `node_id`, `relation_id`, `area_id`), which `brouter.sql` does not use.
- The `natural` column clashes with an SQL keyword (`NATURAL JOIN`), so
  `brouter.sql` always qualifies it with an alias (`li.natural`, `q.natural`, `p.natural`).
- Rows with a `NULL` geometry are not inserted (`not_null = true`), typically
  unclosed ways in `as_polygon()` or relations that are not a multipolygon.
- osm2pgsql creates a GiST index on the geometry column. An index on the id column
  is created only in `--slim` mode.

---

## `lines`

Ways with a `highway`, `waterway` or `natural=coastline` tag.
Definition: `osm2pgsql.define_way_table('lines', ...)`.

| column              | type                         | source (OSM)           | notes |
|---------------------|------------------------------|------------------------|-------|
| `way_id`            | `int8 NOT NULL`              | way id                 | automatic (osm2pgsql) |
| `nodes`             | `jsonb`                      | `object.nodes`         | JSON array of node ids in way order, e.g. `[123, 456, 789]` |
| `name`              | `text`                       | `name`                 | |
| `osm_id`            | `text`                       | way id                 | cast to `::bigint` in SQL |
| `highway`           | `text`                       | `highway`              | |
| `maxspeed`          | `text`                       | `maxspeed`             | may contain `"50 mph"`, `"none"`, `"CZ:urban"`… |
| `waterway`          | `text`                       | `waterway`             | |
| `natural`           | `text`                       | `natural`              | in practice only `coastline` |
| `width`             | `text`                       | `width`                | |
| `oneway`            | `text`                       | `oneway`               | |
| `bridge`            | `text`                       | `bridge`               | |
| `tunnel`            | `text`                       | `tunnel`               | |
| `junction`          | `text`                       | `junction`             | |
| `lanes`             | `text`                       | `lanes`                | |
| `bicycle`           | `text`                       | `bicycle`              | |
| `crossing`          | `text`                       | `crossing`             | |
| `crossing_markings` | `text`                       | `crossing:markings`    | |
| `way`               | `geometry(LineString, 3857) NOT NULL` | `as_linestring()` | |

### Modification at the start of `brouter.sql` (lines 8–57)

The script rebuilds the table right at the start (`SELECT ... INTO lines_bis`, `DROP`,
`RENAME`). The resulting `lines` table that the rest of the script works with:

- **drops** `way_id` and `name`,
- **converts** `maxspeed` from mph to km/h (`"30 mph"` → `"48.30"`, the type stays `text`),
- **adds** `merca_coef` (`float8`), the ratio of the length in 3857 to the real length in metres,
- creates the indexes `lines_osm_id_idx (osm_id)` and `lines_way_idx USING gist (way)`.

Column order after the modification: `osm_id, highway, way, waterway, natural, width, oneway,
tunnel, bridge, nodes, maxspeed, junction, lanes, bicycle, merca_coef, crossing,
crossing_markings`.

---

## `polygons`

Areas from closed ways (`natural` ∈ water/bay/beach/coastline/wetland, or
any `landuse` / `leisure`) and from **all** relations from which a
multipolygon can be built. Definition: `osm2pgsql.define_area_table('polygons', ...)`.

| column         | type                                | source (OSM)       | notes |
|----------------|-------------------------------------|--------------------|-------|
| `area_id`      | `int8 NOT NULL`                     | id                 | automatic; ways positive, relations **negative** |
| `osm_id`       | `text`                              | id                 | always positive, so way and relation ids can collide |
| `type`         | `text`                              | `type`             | |
| `boundary`     | `text`                              | `boundary`         | filled only from relations |
| `name`         | `text`                              | `name`             | |
| `place`        | `text`                              | `place`            | filled only from relations |
| `population`   | `text`                              | `population`       | filled only from relations |
| `landuse`      | `text`                              | `landuse`          | |
| `leisure`      | `text`                              | `leisure`          | |
| `natural`      | `text`                              | `natural`          | |
| `water`        | `text`                              | `water`            | |
| `power`        | `text`                              | `power`            | |
| `plant_method` | `text`                              | `plant:method`     | |
| `plant_source` | `text`                              | `plant:source`     | |
| `aeroway`      | `text`                              | `aeroway`          | |
| `aerodrome`    | `text`                              | `aerodrome`        | |
| `way`          | `geometry(Geometry, 3857) NOT NULL` | `as_polygon()` / `as_multipolygon()` | Polygon or MultiPolygon |

Use in `brouter.sql`: airports (`aeroway`, `aerodrome`), water bodies and coastline
(`natural`, `water`), greenery (`landuse`, `leisure`), industry and retail (`landuse`,
`plant_method`, `plant_source`).

---

## `cities`

Nodes with `place` ∈ city/town/village/municipality (unless they have `area=no`).
Definition: `osm2pgsql.define_node_table('cities', ...)`.

| column        | type                                | source (OSM)  | notes |
|---------------|-------------------------------------|---------------|-------|
| `node_id`     | `int8 NOT NULL`                     | node id       | automatic |
| `name`        | `text`                              | `name`        | |
| `name_en`     | `text`                              | `name:en`     | |
| `place`       | `text`                              | `place`       | |
| `admin_level` | `text`                              | `admin_level` | |
| `osm_id`      | `text`                              | node id       | |
| `population`  | `text`                              | `population`  | cleaned in SQL (`replace('.', '')`, `isnumeric`); `brouter.sql` writes `0` into it |
| `way`         | `geometry(Geometry, 3857) NOT NULL` | `as_point()`  | in practice always Point |

---

## `cities_rel`

Relations with `type=boundary`. Definition: `osm2pgsql.define_relation_table('cities_rel', ...)`.

| column        | type                                | source (OSM)         | notes |
|---------------|-------------------------------------|----------------------|-------|
| `relation_id` | `int8 NOT NULL`                     | relation id          | automatic |
| `reltype`     | `text`                              | `relation_type` (!)  | always `NULL`, see notes |
| `admin_level` | `text`                              | `admin_level`        | compared as text (`= '8'`) |
| `boundary`    | `text`                              | `boundary`           | SQL filters `administrative`, `ceremonial` |
| `name`        | `text`                              | `name`               | |
| `name_en`     | `text`                              | `name:en`            | |
| `place`       | `text`                              | `place`              | |
| `osm_id`      | `text`                              | relation id          | |
| `population`  | `text`                              | `population`         | same as in `cities` |
| `way`         | `geometry(Geometry, 3857) NOT NULL` | `as_multipolygon()`  | MultiPolygon |

---

## `peak`

Nodes with `natural=peak`. Definition: `osm2pgsql.define_node_table('peak', ...)`.

| column    | type                                | source (OSM) | notes |
|-----------|-------------------------------------|--------------|-------|
| `node_id` | `int8 NOT NULL`                     | node id      | automatic |
| `name`    | `text`                              | `name`       | |
| `natural` | `text`                              | `natural`    | always `peak` |
| `osm_id`  | `text`                              | node id      | |
| `ele`     | `text`                              | `ele`        | in SQL only values matching `'^[0-9\.]+$'`, then `::decimal` |
| `way`     | `geometry(Geometry, 3857) NOT NULL` | `as_point()` | in practice always Point |

---

## `nodes`

Nodes relevant for crossings and traffic lights (`highway=traffic_signals`,
`railway=level_crossing`, `crossing=*signals/zebra/island`, `crossing:island=yes`,
`crossing:signals=yes`, `crossing:markings=zebra`, or the presence of `crossing_ref`,
`button_operated`, `traffic_signals`). Definition: `osm2pgsql.define_table{ name = 'nodes', ... }`.

Unlike the other tables, it **has no text `osm_id`**. The id columns are generated by
osm2pgsql (`ids = { type = 'any', ... }`) and all tags are stored in `jsonb`.

| column     | type                             | source (OSM) | notes |
|------------|----------------------------------|--------------|-------|
| `osm_type` | `char(1) NOT NULL`               | object type  | always `'N'` |
| `osm_id`   | `int8 NOT NULL`                  | node id      | `brouter.sql` adds the index `nodes_idx (osm_id)` |
| `tags`     | `jsonb`                          | all tags     | queried via `tags ->> 'crossing'` etc. |
| `geom`     | `geometry(Point, 3857)`          | `as_point()` | the only table where the geometry is named `geom` and is not `NOT NULL` |

Link to `lines`: `lines.nodes` (jsonb array of ids) ↔ `nodes.osm_id` (int8).

---

## Notes and potential problems

1. **`cities_rel.reltype` is always `NULL`.** Lua fills
   `reltype = object.tags.relation_type`, but no such tag commonly exists in OSM.
   Moreover, the `type` tag was previously removed by calling `object:grab_tag('type')`, whose
   result is in the `relation_type` variable. It was probably meant to be
   `reltype = relation_type`. `brouter.sql` does not use the column, so it does not matter.
2. **Inconsistent id types.** `osm_id` is `text` in all tables except
   `nodes`, where it is `int8`. SQL handles this by casting (`osm_id::bigint`,
   `osm_id::numeric`), which prevents index use in joins on the cast column.
   The automatic `way_id`/`node_id` (`int8`) could have been used instead of the text `osm_id`.
3. **`polygons.osm_id` does not distinguish a way from a relation** (both positive). The distinction
   is carried only by the automatic `area_id` (relations negative).
4. **`ST_StartPoint` on polygons works** (computing `merca_coef` for `polygons`,
   `cities_all`, `poly_industri`, `poly_airportnew`…). Verified on PostGIS 3.6.4:
   for a Polygon it returns the first point of the exterior ring, for a MultiPolygon the first point of the
   first polygon (`POLYGON((5 5,6 5,…))` → `POINT(5 5)`). The helper line
   start → centroid is therefore valid and `merca_coef` is computed. The earlier concern that it returns
   `NULL` was not confirmed. On older PostGIS versions I recommend verifying this with the same
   query.
