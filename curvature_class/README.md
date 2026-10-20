# curvature_class

Proof of concept of the pseudo-tag `estimated_curvature_class` (curvature of roads
for motorcyclists) and analysis of how BRouter's existing cost model (`turncost`)
treats curvy roads.

Nothing outside this directory is modified; the rest of the repository is only read.

## Layout

| directory   | content |
|-------------|---------|
| `docs/`     | design notes: `metrics.md` (procedure), `sources.md` (background), `tables.md` (source tables of `brouter.sql`), `pgsql-import.md` (how to run the SQL part) |
| `sql/`      | PostGIS part: `lines.sql` (table), `functions.sql` (`curv_*` functions), `curvature_tags.sql` (the tag) |
| `python/`   | `generate_roads.py` (simulated roads), `visualize_curvature.py` (gallery with computed classes) |
| `jvm/`      | Kotlin tests running real BRouter code (turncost, section and link cost) |
| `profiles/` | test `.brf` profiles, see `profiles/README.md` |
| `upstream/` | verbatim copies of code from the repository, see `upstream/README.md` |
| `out/`      | generated outputs (`roads.json`, `roads.svg`, `lines_data.sql`, ...); not in git |

## Related files in the repository

- `misc/scripts/mapcreation/brouter.sql`: the map-creation SQL the tag is meant to be merged into
- `brouter-core/src/main/java/btools/router/StdPath.java`: `processWaySection`, turncost and section cost
- `brouter-core/src/main/java/btools/router/OsmPath.java`: `addAddionalPenalty`, cost of a whole link
- `brouter-util/src/main/java/btools/util/CheapAngleMeter.java`: turn angle and its cosine
- `locus-routing-profiles/`, `misc/profiles2/`: profiles with the current `turncost` values

## Running

SQL and Python: see `docs/pgsql-import.md`, all commands are run from this directory.
The Python scripts always write to `curvature_class/out/`.

JVM tests (Gradle wrapper from the repository root, BRouter is included as a composite build):

```bash
cd jvm
../../gradlew test
```
