# Curvature metrics

Goal: a pseudo-tag `estimated_curvature_class` for motorcyclists, computed in PostGIS
the same way as the other classes in `brouter.sql`. Proof of concept.

## Possible approaches

| | metric | computation | weaknesses |
|---|---|---|---|
| M1 | sinuosity | length / straight-line distance between ends (GraphHopper uses the inverse) | an S-bend comes out almost like a straight road; closed line; sensitive to how the way is split |
| M2 | turning density | sum of \|heading changes\| / length [°/km] | does not distinguish a sharp bend from a long sweeping one; overrates short segments |
| M3 | **share of length in radius bands** | local radius at each point → % of length in bands | depends on the resampling step and on the choice of bands |
| M4 | number of bends / hairpins | continuous segments with the same direction and small R | most complex SQL, many thresholds |
| M5 | sharpest window | max. turning in any 100 m window | just a single number, says nothing about the rest of the road |

The Curvature project (roadcurvature.com) uses an approach similar to M3, see `sources.md`.
It sums the absolute weighted length, though, not a share.

## Chosen approach: M3

Why:
- **Local metric:** the radius is computed from three neighbouring points, so it does not depend on
  where OSM split the way. Every piece of a bend still keeps its small radius.
- **Share instead of absolute length:** the class applies to a single way and brouter multiplies it by
  the way's length. A share makes sense even for short ways, where °/km (M2) exaggerates.
- **Distinguishes sharpness:** a hairpin and a long sweeping curve with the same angle fall into different bands.
- **Verifiable:** the simulated roads have the true radius of every arc in `out/roads.json`.

Computed **per individual way**, without merging. Merging short ways with their
neighbours will be added only if a splitting test shows instability.

## Computation steps

1. **Resampling** (`curv_resample`, done in `functions.sql`): points evenly
   spaced about 10 m apart in real metres, local coordinates `x[]`, `y[]`.
   Independent of OSM node density. The step determines the smallest resolvable radius (~5 m).
2. **Radius at a point** (`curv_radii`, done): radius of the circle circumscribed through points
   i−k, i, i+k, `R = a·b·c / (4·area)`. For three collinear points R = ∞.
   Chosen **k = 2** (base 4 × step): gentle curves R 60–175 m come out correctly,
   hairpins are slightly overestimated (+5 %). The first and last k points have no radius.
3. **Bands:** the length around each point (= step) is added to a band according to R.
   Default bands taken from the Curvature project, to be tuned on simulated data:

   | band | R |
   |---|---|
   | straight | > 175 m |
   | gentle | 100–175 m |
   | medium | 60–100 m |
   | sharp | 30–60 m |
   | hairpin | < 30 m |

4. **Per-way output** (`curv_bands`, `curv_metrics`, done): share of length in each
   band (sum = 100 %) and a weighted score `score = Σ share × weight` (0 = straight,
   max. 2 = the whole way in hairpins). Bands and weights are function parameters.
   Test on simulated roads: correlation with the true score 0.89. Short sharp
   bends (hairpins, urban corners) are overestimated because the k = 2 window (40 m)
   "spreads" the bend onto neighbouring points. This will later be solved using knowledge of the surroundings
   (`estimated_town_class`).
   **Minimum number of radii** `min_radii` (default 5, way ~90 m): below it
   neither shares nor score are computed (NULL) and the curvature class is **undefined**.
5. **Class** (`curv_class`, done): the score is cut by thresholds into `'1'`–`'6'`, just like
   the other classes in `brouter.sql`. The thresholds are the `limits` parameter (default
   `{0.1, 0.25, 0.45, 0.7, 1.0, 1.3}`); on real OSM they will be tuned according to the distribution.
   Straight ways (score < 0.1) and undefined ways get no tag (NULL, no row).

   | class | score | meaning | simulated roads |
   |---|---|---|---|
   | no tag | < 0.10 / NULL | straight, short | straight, gentle, 2× winding, 9 short |
   | 1 | 0.10–0.25 | occasional bend | winding |
   | 2 | 0.25–0.45 | undulating | winding, short urban |
   | 3 | 0.45–0.70 | twisty | urban |
   | 4 | 0.70–1.00 | very twisty | 1× urban |
   | 5 | 1.00–1.30 / hairpins | mountain | mountain, serpentines (hairpin rule) |
   | 6 | ≥ 1.30 | extreme | mountain |

   The table `curvature_tags (losmid, curvature_class)` is created in `curvature_tags.sql`
   (only roads for cars, without `*_link`) and is joined into `all_tags` via
   `NATURAL FULL OUTER JOIN curvature_tags`.
   **Hairpin rule** (in `curv_class`, parameters `hairpin_*`): by score alone,
   serpentines come out 1–2 classes lower than mountain roads (there are straights
   between the hairpins). Therefore: share of the R < 30 m band ≥ 25 % **and at the same time** length in it
   ≥ 100 m → at least class 5. The share alone is not enough, because a short urban street
   with one or two corners also has ≥ 25 % (the k = 2 window spreads a corner onto ~3 points),
   but only 30–60 m. Simulated roads: serpentines 26–34 % / 120–460 m → class 5,
   urban 28 % / 50–60 m unchanged. The margin is small (60 vs. 120 m) and the serpentine
   share is just above the threshold; both thresholds will be tuned on real OSM.
   The rule is enabled by passing `shares`, `n_radii` and `step_m` from `curv_metrics`.

## Open questions

- Bands and weights: take them from Curvature, or adjust (e.g. separate hairpins < 15 m)?
- Resampling step 10 m: is it enough for hairpins with R 7–15 m? Verify on serpentines.
- Should the class be purely geometric (towns and traffic are handled by the profile via `estimated_town_class`
  and `estimated_traffic_class`), or already "fun-oriented" with exceptions for urban corners?
- Stability for short ways: test by splitting simulated roads into random pieces.
