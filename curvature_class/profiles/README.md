# Test profiles

BRouter profiles (`.brf`) used by the JVM tests in `../jvm` and for manual routing.
Usually a copy of a profile from `locus-routing-profiles/` or `misc/profiles2/`
with a modified value (e.g. `turncost`).

Start each file with a comment saying where it comes from and what was changed:

```
# source: locus-routing-profiles/LoMTB.brf @ <commit>
# change: turncost = -20 (instead of 90 / 60 / 30)
```
