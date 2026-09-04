# DDS composition pixel fixtures

These small PNG resources belong to the same v5 design represented by
`../figma_no_permission/v5.json` and `../official_no_permission/schema.json`.
Source PNGs are input to the pure local composer; the two `*-official.png` files
are test expectations only and are never used by production code.

| Local file | Public resource URL |
|---|---|
| header-left.png | https://lanhu-oss-2537-2.lanhuapp.com/FigmaDDSSlicePNG75a0418c3e91f2917cb9a254282053ca.png |
| header-right.png | https://lanhu-oss-2537-2.lanhuapp.com/FigmaDDSSlicePNG15f8e56a253d23d48d84247fe6066a53.png |
| header-official.png | https://lanhu-dds-backend.oss-cn-beijing.aliyuncs.com/merge_image/imgs/24990592d7ea40b598ddc09f1930670e_mergeImage.png |
| illustration-ground.png | https://lanhu-oss-2537-2.lanhuapp.com/FigmaDDSSlicePNG9df5b2d42d26dd1d42c9ecedfc6e8f7f.png |
| illustration-lock.png | https://lanhu-oss-2537-2.lanhuapp.com/FigmaDDSSlicePNGcb2cd0f68f7b82a0912a149eee3a6d18.png |
| illustration-official.png | https://lanhu-dds-backend.oss-cn-beijing.aliyuncs.com/merge_image/imgs/ef9b265b63954499bb0c31a84c32fc00_mergeImage.png |

The regression compares decoded RGBA pixels, not PNG compression or remote URLs.
Header merges two 16×16 images with a 20px gap into 52×16. Illustration merges
105×34 ground at (0,45) and 63×65 lock at (22,0) into 105×79. The boxes come from
independently ceiling the raw global coordinates and dimensions, then taking
the raster-box union. The compositor does not select which images to combine.
