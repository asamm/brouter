# Verbatim copies from the repository

Pieces of code copied from elsewhere in the repository (SQL from `brouter.sql`,
expressions from profiles, ...), used only when the original cannot be called directly.
The JVM tests call the real BRouter classes, so Java code is not copied here.

Each file starts with a header:

```
-- source: misc/scripts/mapcreation/brouter.sql, lines 120-145
-- commit: <hash> (<date>)
-- changes: none | <what was changed and why>
```

When the source changes upstream, the header shows which copies are outdated.
