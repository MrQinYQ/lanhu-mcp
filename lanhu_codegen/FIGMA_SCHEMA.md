# Raw Figma adapter: scope and limits

`figma_to_dds_schema(data, asset_loader=load_bytes)` accepts the Lanhu Figma
plugin's `meta/assets/artboard` export and reconstructs a DDS tree for the pinned
official HTML generator. Default inferred layout expands harmless containers,
groups rows/columns and image-text pairs, merges selected DDS PNGs, and assigns
semantic classes. These rules were inferred from paired exports; they are not
Lanhu's upstream server source. Generated schema IDs and storage URLs are not
recreated. `layout="absolute"` remains available for source-geometry inspection.

## Current acceptance contract

The user-approved acceptance-v2 contract permits naming/address differences only
when visual output is unchanged and those differences have been independently
verified. It first checks the full tree's hierarchy, order, node types, semantic
roles, geometry and original layer identities, then permits a one-to-one class
mapping at the corresponding tree positions. A composite src may be mapped only
after its dimensions and every decoded RGBA pixel match the reference image.

After these two normalizations, all five HTML/CSS files must be byte-identical.
Other DOM, content, attribute, CSS value, declaration-order, whitespace or image
pixel changes remain failures. Production conversion receives neither the
reference schema nor these acceptance mappings. Strict schema diagnostics still
report differing synthetic IDs and serialized metadata.

All six paired samples meet these conditions after the documented repairs;
the complex, report, network, application and aggregation samples also have zero differing screenshot pixels.
The latest full suite has 1199 passing tests, including all earlier paired gates,
recorded in [`sixth/round-04/pytest.log`](../data/codegen-review/sixth/round-04/pytest.log).
The earlier `round-04` reports, including `335 passed, 1 xfailed` under the old
raw-byte criterion, are retained separately and are not overwritten.

## Inputs and versioning

The user's supplied JSON is version 4 of the example image:
`fe42c66d-dcc5-4591-a4b4-386e820428b6`. It contains rectangle-only bounding paths
for complex vectors and no `ddsImage` resources. It fails explicitly at layer
`253:37568` (`形状结合`); drawing a rectangle there would invent missing geometry.
The official DDS endpoint also returned code `10011` for this version (version
data absent) when checked on 2026-09-03.

The current design is version 5:
`8d67d279-89a6-4f5d-ac2c-f32225c146cf`. Its raw JSON has 15 DDS image exports in
addition to the ordinary image export. The adapter now produces the same
38-node structure as the official schema: 16 blocks, 8 texts, 13 images and the
page, including seven newly inferred containers. Four CSS outputs are identical;
HTML differs only in two composite source URLs. Both composite PNGs have the
same decoded RGBA pixels as the official files. Tests separately preserve
strict reporting of differing IDs and serialized metadata.

See `tests/fixtures/figma_no_permission` for versioned source inputs. Neither
fixture nor runtime code contains a credentials dependency.

A second, independently supplied design, “结构” (version
`7703002a-81e1-4653-9494-8638902c1f37`), failed the unchanged adapter at an
unexported shadow. After capability and inference repairs, all 158 nodes match
the official hierarchy, order, type, semantic role and bounds, including all
122 original layer IDs, 41 texts and 46 images. Computed node styles and full
page screenshots match in the tested browser. Exact exports still differ in
35 ordinary container aliases and one pixel-identical composite URL. Under
acceptance-v2, the verified one-to-one aliases and pixel-identical source are
the only permitted normalizations; all remaining export bytes match. See
`tests/fixtures/figma_complex` and `docs/figma-dds-inference.md` in the repository.

A third design, “综合报表” (version `a6179157-7c24-4153-ab4c-7b7c803b49b5`),
initially produced 216 rather than 206 nodes and 7,851 differing screenshot
pixels. Repairs infer a once-promoted overflowing table column and its absolute
paint panel, explicit checkbox component roles, adjacent suffix icons and
full-width titles. All 206 nodes now match, including 184 original identities,
80 texts and 38 images. Only 32 class aliases and one pixel-identical composite
URL differ; the five normalized files and tested browser pixels match exactly.
This is a repaired regression pass, not an unchanged first-run success. See
`tests/fixtures/figma_report` and `docs/figma-report-validation.md`.

The fourth design, “广告网络” (version `83600518-4304-44ba-9c39-cdf6079c6ab0`),
initially failed before producing a schema because four unexported rotated
shapes lack contours. The bounded projection below and repeated-resource,
semantic-scope, overlay and spacing repairs reproduce all 563 nodes, including
512 original identities, 192 texts and 121 unchanged image sources. Only 243
verified class aliases differ in the five exports; all other bytes and tested
browser pixels match. This is another repaired regression pass. See
`tests/fixtures/figma_network` and `docs/figma-network-validation.md`.

The fifth design, “应用管理” (version `6244237b-28b5-4421-9788-7a0b77cb9b4f`),
failed unchanged at an unexported rotated hairline. The repaired adapter matches
all 400 nodes, 323 original identities, 151 texts and 59 unchanged image sources.
Only 107 verified ordinary class aliases differ; all five normalized exports,
400 browser rectangles/computed styles and full-page pixels match. See
`tests/fixtures/figma_application` and `docs/figma-application-validation.md`.

The sixth design, “聚合管理” (version `d4e341f9-71f7-4fa7-82b8-e9207f842741`),
failed unchanged at a rotated transparent group. The repaired conversion matches
1250 nodes, 1136 original identities, 458 texts and 214 unchanged image sources.
Only 513 verified ordinary class aliases differ; all five normalized files,
browser rectangles/computed styles and full-page pixels match. See
`tests/fixtures/figma_aggregation` and `docs/figma-aggregation-validation.md`.
Its source rules include validated half-turn and transparent rect envelopes,
strict zero-height DDS-shape omission, source-derived overlay anchors, raw-edge
checks for ceil-only overlaps and bounded source component pairing. These remain
empirical compatibility rules; projection/omission warnings explicitly preserve
their limitations. Known forced overlays are excluded from static-paint proofs,
and negative trailing gaps do not establish illustration-caption centering.

## Supported representation

- Normalize the artboard origin and ceil individual raster frame fields.
  `Web @2x` does not halve this geometry. Keep meaningful paint/clip/opacity
  containers. DDS mode partitions exported layout rectangles, without using
  shadows as row extents. Unknown effects still prevent unsafe inference.
  Ambiguous overlap clusters retain absolute positioning.
- DDS compatibility restores bounded contained-image attachments, local baked
  image overlays and singleton text rows in a matrix context. Separate ordinary
  image-export markers provide evidence for adjacent text semantic groups.
  A standalone text header followed by multiple content rows gets a page-width
  remainder container with the observed inclusive last pixel. These rules have
  paired-example and synthetic counterexample tests, not universal guarantees.
- Explicit checkbox component roles are inherited through source wrappers and
  excluded from generic icon pairing. Suffix icons use centered geometry and
  a gap bounded by the text frame height, with paint-obstacle checks. Contiguous
  painted edge columns with a matching in-panel row grid may be promoted once;
  clipped/effected panels and overlapping duplicate cohorts are protected.
  Full-width titles do not acquire redundant singleton rows. These DDS rules
  do not change the separate source-paint-preserving layout.
- In repeated complete-view siblings, generic ImageText pairing is suppressed
  within those source subtrees. The empirical scope requires disjoint same-size
  views with a painted full-width image/text header and multiple nested body
  control columns; simple repeated cards do not establish it. Standalone
  annotations remain eligible for pairing. A centered leading icon may exceed
  the text line frame height by at most two pixels under the existing spacing
  and paint-obstacle checks. Both rules are inferred compatibility behavior,
  not recovered official source, and do not affect source layout mode.
- Prefer a marked `ddsImage` export over a marked ordinary `image` export.
  Render that export once, without painting its effects or children again.
  Parent opacity is retained; an exported node's own opacity/effects are already
  part of the exported pixels. A full-artboard image is rejected as a structural
  fallback. Prefer DDS descendants over ordinary parent slices when the entire
  subtree is expressible; otherwise retain the complete parent slice.
- Merge eligible 1x DDS PNGs using their ceil bounds and source-over alpha.
  DDS compatibility keeps a source separate when its URL occurs in multiple
  visible image nodes; repeated resources are not merged independently per view.
  Following siblings of the merge group's source ancestors also veto merging
  when their known paint overlaps, or their paint bounds are unknown.
  The injected loader is called only for selected merge inputs. Ordinary 2x/SVG
  exports stay separate. Optional merge failures retain source images and record
  `layoutWarnings`; no loader means no compositing. Proximity thresholds are
  documented heuristics, not established general server behavior.
- Solid fills, duplicated opacity fields, per-corner radius, rectangular
  clipping and solid inside borders, including `width`/`widths`, are supported.
  DDS compatibility truncates fractional corner radii to integer pixels;
  source and absolute inspection preserve fractional radii.
  Inferred mode defaults to the observed DDS per-edge-to-uniform paint and
  outer-frame child offset conventions, reporting their deviation from source
  appearance. Bordered rows with two symmetric endpoints use space-between
  and keep the outer edge margins. `border_layout="source"` uses conservative
  grouping and compensates content offsets once, retaining source positions
  and painter order through shadows and positioned descendants.
  Absolute mode retains both per-edge borders and source child positions.
- Ordinary box shadows with explicit offset, nonnegative blur, spread, boolean
  inset and normal blending are supported, including multiple shadows and
  duplicate alpha fields. Unknown effects remain explicit failures. In source
  mode known shadow bounds constrain reordering. DDS mode follows the observed
  official frame partitioning, which can produce a different shadow order.
- Pure axis-mirrored containers can flatten when their visible descendants
  are entirely baked DDS images and the wrapper adds no paint, clipping or
  opacity. Exact reflected image corner anchors are corrected only when the
  exported realFrame corroborates the correction. Near-axis rotations and
  arbitrary rotations keep the original export frame convention.
  DDS-only swapped-axis wrappers additionally require validated realFrame
  anchors and entirely baked DDS-image descendants before flattening.
- Uniform text styles preserve content, font, weight, color, line height,
  letter spacing, horizontal alignment, italics, underline and strikethrough.
  Text is HTML-escaped, including braces that could otherwise be interpreted as
  DDS expressions. Numeric entities keep formatting from changing explicit
  newlines, tabs or wrapped-text spaces; wrapped text uses `pre-wrap` when
  whitespace preservation is needed. DDS output omits that declaration for
  content containing no whitespace, following the observed official output.
  DDS line boxes at least twice the font size do not acquire the single-line
  nowrap hint merely because explicit line-height equals their height.
  Vertical center is supported only for a single explicit line whose lineHeight
  equals the frame height; larger/multiline/auto-height cases remain unsupported.

There is a legacy **explicit geometry heuristic**: an unexported `shapeLayer` with a
single `rect` path is accepted when `shapeType` explicitly identifies a
rectangle, or its name follows the export convention `Rectangle…` / `矩形…`.
Names alone cannot prove geometry: a user can rename a vector to `Rectangle`.
This convention is sufficient for the supplied version-5 separator but is not
a universal correctness guarantee. Arbitrarily named or vector/path/boolean
shapes require an exported asset. For strict verification, supply explicit
primitive types or exported resources instead of relying on layer names.

A separate DDS-only rect-envelope projection reproduces four observed fallback
blocks in the fourth sample. It requires a leaf with no explicit primitive,
one rectangle bounding stub whose frame matches the positive square source
frame, a realFrame corroborating the rotated corner-anchor offset, uniform
radius, a corroborated pure quarter-turn, one opaque solid fill and
no exported image, clipping, effects, border or nonnormal blend. The adapter
emits `dds_rect_envelope_projection` warnings, keeps the ceil source rectangle
and drops rotation for this projection. It does not reconstruct the missing
polygon. Source/absolute modes still reject this case; unrelated vectors and
ambiguous transforms remain errors. Names, IDs, fixed sizes and literal colors
do not select this fallback.

A similarly bounded DDS-only hairline projection accepts a zero-radius
rectangle whose short edge is at most one CSS pixel and whose longer edge,
pure quarter-turn and true rotated realFrame agree. It emits
`dds_rotated_hairline_projection`, retaining the unrotated source rectangle,
as the official DDS does. A projected line escaping an earlier safe subtree
can force an intersected later card into absolute layout at its original parent;
crossing later paint or entering effects/clipping remains blocked.

Two further DDS image policies intentionally reproduce source-to-official
differences and carry warnings: exact zero-width DDS exports are omitted;
exported no-paint, no-child rounded rectangle stubs satisfying the explicit
empty-shape predicate become empty blocks. Neither policy assumes the PNG is
transparent: exported pixels are discarded to match DDS. Positive fractional
widths are retained, and source/absolute modes keep their image behavior.
Empty-shape attachment uses a unique geometric anchor and source-wrapper cohort,
with full ancestor paint containment and ordering checks. Annotation overlays
may cross only a later known shadow extension, with a separate
`dds_annotation_shadow_order` warning; actual content intersections remain
protected.

## Coordinates and official serializer behavior

The official serializer uses `parseInt` for legacy physical geometry and text
metric fields. Inferred mode follows observed ceil raster geometry. In absolute
mode, fractional geometry uses one standard logical
property per dimension (`insetInlineStart`, `insetBlockStart`, `inlineSize`,
`blockSize`) instead of emitting competing physical and logical properties.
`rowDims` then retains the numeric source bounds. Fractional text metrics use a single
CSS `font` shorthand instead of competing font-size/line-height declarations.

Logical pixel overrides in absolute mode are not converted by the official
rem/vw exporters; use px output for that inspection mode. Inferred mode emits
ordinary dimensions that follow the official rem/vw transformation. Matching
the sample's responsive CSS does not recover missing responsive design intent.

## Failure behavior

`UnsupportedFigmaFeature` includes `layer_id`, `layer_name` and `feature`.
Unexported complex vectors, missing marked resources, masks affecting siblings,
nontrivial unbaked transforms, blend modes, multiple fills/borders, gradients,
text/unknown shadows, blurs, center/outside strokes, mixed text styles, incomplete text ranges and
unhandled text layout effects fail explicitly. Unsupported effects inside a
complete image export are represented by that export's pixels. Invisible
layers are omitted because they have no visual contribution.

The adapter never inserts the full design image underneath incomplete nodes.
Apart from the explicitly documented and warned DDS projections/omissions,
unsupported visible data remains a conversion error. Adding
features requires source evidence plus a visual or semantic regression check.
