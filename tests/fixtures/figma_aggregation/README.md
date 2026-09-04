# Sixth paired design: 聚合管理

This fixed regression input is version 5, `d4e341f9-71f7-4fa7-82b8-e9207f842741`,
of image `42824a80-7d88-4793-99ad-6c22296b9469`. Raw JSON, official schema and
independently captured official editor files belong to the same version.
Resource bytes come only from URLs present in the raw export.

The unchanged fifth-final converter failed on an unexported rotated group.
That first run is preserved in `data/codegen-review/sixth/baseline`; it did not
produce actual HTML and must not be represented as a successful unseen sample.

After repairs, final `sixth/round-04` passes acceptance-v2 with 1250 nodes,
1136 original identities, 458 texts, 214 unchanged image sources and 513 ordinary
class aliases. All five normalized files match, all browser nodes/styles match,
and the complete decoded screenshot has zero differing pixels. The final full
suite contains 1199 passing tests, including the previous five paired gates.

`metadata.json` records original inputs and their hashes. The fixture is an
offline test oracle only; it does not enter production conversion. Tests preload
only original resource bytes and forbid fixture reads during Figma conversion.
Generic geometry tests are additional internal-consistency evidence, not claims
that those synthetic variants were independently exported by Lanhu.
