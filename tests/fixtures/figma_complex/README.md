# Complex paired design fixture

This is the Lanhu design named “结构”, image
`b4706be3-c700-482b-9a2b-07ecbab9796f`, version 5
`7703002a-81e1-4653-9494-8638902c1f37`. `metadata.json` records the source URLs
and SHA256 hashes. The raw Figma JSON and official DDS belong to that version.

The five files in `official-ui/` were independently captured from the official
code panel. Each exactly matches the fixed official generator applied to
`official-schema.json`.

Only `assets/header-left.png` and `assets/header-right.png` are input resources.
The converted composite is compared against `assets/header-official.png`;
that oracle PNG and the reference schema never enter conversion. Their URLs,
paths and hashes are recorded separately in `image-resources.json`.

The unchanged implementation's first run failed on an unexported shadow at
layer `247:6018`. After the supported-shadow/alignment capability changes, the
same raw input converts and preserves original node identities, global bounds,
all text and image resources, but grouping and class naming still differ.
Border-origin compatibility is tracked separately through the DDS/source layout
option. This repaired example is not an independent first-run
success. Full HTML/CSS parity remains a strict expected-failure test; it must be
promoted to an ordinary acceptance test when the remaining differences are fixed.

No expected total output node count is locked: legitimate grouping improvements
must remain possible. The 122 original DDS layer IDs, 41 text nodes and 46 images
are verified against the reference rather than reducing correctness to counts.
