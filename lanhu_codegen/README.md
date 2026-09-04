# Lanhu DDS HTML generator

This directory contains the HTML generator used by the public Lanhu DDS frontend
on 2026-09-03. It is the complete `24c8` generator, including loop expansion,
special slots, dynamic style bindings, conditions, input handling, common flex
classes, and px/rem/vw outputs. `source-manifest.json` records the exact frontend
URLs, hashes, module IDs, and reference output hashes.

The five output files are `index.html`, `index.css`, `index.rem.css`,
`index.response.css`, and `common.css`. Formatting uses the same pinned Prettier
2.5.1 implementation and plugins as frontend wrapper module `6ce9`. Dependencies
are bundled; no npm install, network access, or browser is needed at runtime.
Node.js 18 or later is required.

## JSON bridge

Run `node runner.cjs` with this object on standard input:

```json
{"schema": {}, "options": {"format": true, "rem": 37.5}}
```

Replace the empty `schema` with the downloaded DDS schema. Options are optional.
Standard output contains one JSON object with a `files` filename-to-content map
and generator metadata. Errors go to standard error as JSON and return exit code
1. The exported `generateH5Files(schema, options)` function has the same result.
The supplied schema is copied before the official generator mutates it.

## Compatibility and scope

The sample's `index.html`, `index.css`, and `common.css` match the files copied
from the official DDS editor byte for byte. Pixel fidelity to the source design
is a separate issue: this generator intentionally preserves the official
serializer's behavior and depends on the information present in its DDS input.
Matching one sample does not establish coverage of all possible DDS schemas.
The second “结构” reference also reproduces all five files copied from the
official editor when given its official DDS schema. Its raw Figma-to-DDS
conversion meets the user-approved acceptance-v2 contract described below;
the raw output still uses different ordinary class names and a composite URL.
The third “综合报表” reference reproduces all five official editor files too.
After source-layout repairs its 206-node conversion meets the same contract,
with zero differing screenshot pixels and all earlier sample regressions
passing. Its unchanged first run failed and remains separately recorded.
The fourth “广告网络” reference also reproduces all five official editor files.
Its unchanged first run failed on a missing vector contour. After bounded DDS
projection and layout repairs, all 563 nodes, 121 image sources and the tested
browser pixels match. Only 243 verified class aliases differ in the exports.
The fifth “应用管理” reference failed unchanged on an unexported rotated
hairline. After explicit DDS projection, resource-policy and layout repairs,
all 400 nodes, 59 image sources and tested browser pixels match. The five
exports differ only in 107 verified ordinary class aliases. These are repaired
regression passes, not proof that unseen designs need no further inference.
The sixth “聚合管理” reference also failed unchanged, at a rotated transparent
group with unexported descendants. Bounded projection, containment, source
component and fractional-layout repairs now match all 1250 nodes, 214 unchanged
image sources, five normalized exports and tested browser pixels. Only 513
verified ordinary class aliases differ. The official renderer remains unchanged.

Five original `eval` calls for loop bindings were replaced with strict
own-property path reads. Ordinary dotted properties and simple bracket keys or
indices are supported. Executable expressions, prototype properties, and dynamic
bracket expressions are rejected. Schema data is never evaluated as JavaScript.
The third-party libraries retain their original trusted runtime code.

`generator.cjs` retains all remaining generator logic; only old browser polyfill
imports, the Babel `typeof` helper, and the unsafe object-path evaluation were
removed or replaced. `dependencies.cjs` contains the 13 required transitive
dependency modules and a small module loader. It excludes the application UI,
API clients, analytics, and generators for other frameworks.

See `NOTICE` for the license information found in the inspected assets. Public
access to the official generator does not itself establish an open-source
license.

## Figma export adapter

`figma_to_dds_schema(raw, asset_loader=load_bytes)` reconstructs a DDS tree from
Lanhu's `meta/assets/artboard` Figma export. It normalizes raster coordinates,
flattens harmless wrappers, infers rows/columns, assigns semantic class names,
and composes selected 1x DDS PNGs with Pillow. The injected resource loader gets
only original source URLs. The MCP downloads these with an independent client
without account headers; it caches each input and runs conversion off the event
loop. Omitting the loader retains separate images. The optional `layout="absolute"`
mode retains source hierarchy and fractional geometry for inspection.

This Python algorithm was reconstructed from paired exports. It is not official
upstream server source. The v5 reference produces the same 38-node structure and
four identical CSS files; HTML differs only in the two composed image sources,
whose decoded pixels are identical. Synthetic IDs and storage URLs intentionally
remain independent. No reference-schema lookup occurs during conversion.

Missing vector contours without an export, mixed rich text and unsupported
unrasterized effects are explicit errors, apart from a narrowly checked DDS
rect-envelope projection described in `FIGMA_SCHEMA.md`. That projection emits
an explicit warning and reproduces an observed official fallback; it does not
recover a polygon contour. A rectangle name plus placeholder path is only a
weak legacy hint; it cannot establish an arbitrary vector's shape.
The observed per-edge-to-uniform border compatibility rule is reported as a
conversion warning. Failed optional image merges retain individual images and
record their reason. Passing one paired sample does not prove general coverage.

The independent “结构” sample failed the unchanged adapter. It prompted support
for box shadows, no-offset single-line vertical centering and transparent
mirrored DDS wrappers. Subsequent inference repairs reproduce all 158 nodes,
their hierarchy, semantics, geometry and tested browser painting. CSS property
order also matches. Raw HTML/CSS bytes still differ in 35 ordinary container
aliases and one pixel-identical composite URL. These are the only differences
permitted by the user-approved acceptance-v2 contract; they do not imply that
the original files are byte-identical or that the first unchanged run passed.
Default inferred mode uses `figma_dds_layout` and `figma_dds_semantics` to follow
observed DDS frame partitioning and semantic boundaries. The
`border_layout="source"` option preserves the conservative `figma_layout`
paint-order checks and compensates CSS border insets. Both paths have public
adapter regression tests; the latest evidence is in the repository's
`docs/figma-dds-inference.md`.

The fourth sample adds bounded repeated-view scope for ImageText inference,
including a two-pixel leading-icon height tolerance under existing paint checks.
Repeated image sources stay separate. These are empirical compatibility rules;
their conditions and counterexamples are documented in `FIGMA_SCHEMA.md`.

## Acceptance-v2

The offline acceptance first verifies the entire tree's parent/child positions,
order, types, semantic roles, geometry and original layer identities. Only then
may it construct a one-to-one class-name mapping at corresponding tree positions.
Composite source URLs may be mapped only after matching image dimensions and
every decoded RGBA pixel. No other source URL is ignored or replaced.

After these two bounded normalizations, all five HTML/CSS files must still be
byte-identical. Changes to DOM structure, text, other attributes, CSS values,
declaration order, whitespace or image pixels must fail acceptance. The complex
sample also has zero differing pixels in the recorded browser screenshot under
the tested conditions. This is paired-sample evidence, not a universal coverage
claim. Neither the reference schema nor either mapping enters production
conversion; runtime inputs remain the original JSON and original image bytes.

The latest aggregation-design evidence and 1199-test full-suite log are in
[`data/codegen-review/sixth/round-04/`](../data/codegen-review/sixth/round-04/),
with the findings in the repository's `docs/figma-aggregation-validation.md`.
All five earlier paired-sample gates pass in that full run. Historical fifth
sample evidence remains in [`fifth/round-04/`](../data/codegen-review/fifth/round-04/); fourth
sample evidence remains in [`fourth/round-05/`](../data/codegen-review/fourth/round-05/); third
sample evidence remains in [`third/round-02/`](../data/codegen-review/third/round-02/).
Earlier acceptance evidence remains in
[`data/codegen-review/inference/acceptance-v2/`](../data/codegen-review/inference/acceptance-v2/).
The earlier `round-04` raw-byte report and its `335 passed, 1 xfailed` result remain
unchanged as historical records.

`python -m lanhu_codegen.schema_compare reference.json actual.json -o diff.json`
provides a strict offline, field-level diagnostic. It deliberately reports
different synthetic IDs and serialized style metadata even when the generated
HTML/CSS is equivalent. Pair that report with export and pixel comparisons.

`scripts/check_export_equivalence.py SNAPSHOT --asset-manifest MANIFEST` performs
the complete acceptance-v2 check offline. It verifies tree identity before
renaming, actual HTML/schema bindings, single-frame PNG pixels and all five
normalized exports. It returns nonzero for inequivalence or invalid inputs.
