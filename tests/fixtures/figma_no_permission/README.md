# Versioned raw Figma fixtures

Both files belong to the user's example image `b3fa36d9-f781-4497-9e86-236db04187a8`.
These raw inputs must not be confused with each other or with the DDS schema.

- `v4.json`: user-supplied `https://assets.lanhuapp.com/FigmaJSONb08b3251287a781afccc63066c65c5b9.json`, version `fe42c66d-dcc5-4591-a4b4-386e820428b6`. It has no `ddsImage` resources. The official DDS endpoint returned business code `10011` (version data absent) for this version on 2026-09-03. Missing vector data is expected to produce an explicit adapter error.
- `v5.json`: `https://assets.lanhuapp.com/FigmaJSONc59fbc264569196cb2d362b8bd073949.json`, the current version underlying `../official_no_permission/schema.json`. It has 15 `ddsImage` resources; the conservative adapter uses 13 of these and one explicit grouped image export, preserving eight text nodes and the 1640×2298 canvas.

Both inputs contain 92 nodes and 83 rectangle-only path entries. Complex vectors therefore require the supplied exported resources. Version 5 can be converted to a DDS-compatible fixed-layout tree; that tree deliberately does not claim equality with Lanhu's inferred and regrouped schema.
