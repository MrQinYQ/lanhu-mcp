# 应用管理 · 版本 4

第五份用户提供的独立设计稿，image ID `8eacd524-8609-4ad1-aede-2b9cc38c31f1`，
version ID `6244237b-28b5-4421-9788-7a0b77cb9b4f`。

`raw.json` 和 `official-schema.json` 保留同版本响应字节；`official-ui/` 是独立
从官方代码面板读取的五个文件。`metadata.json` 保存输入及资源哈希、版本和
未修改首轮失败事实。`images/` 仅缓存原始 JSON 包含的 URL 所指向的资源，
`image-resources.json` 记录 URL、文件路径和哈希，没有参考专用资源或凭据。

原始 JSON 有 598 个节点，官方 DDS 有 400 个节点、151 个文本、59 张图片。
未修改算法在旋转细线处失败，没有生成 actual schema；修复后的回归使用
`test_figma_application_validation.py` 验证原始身份、内容、几何、图片、五个
官方文件和完整 acceptance-v2。生产转换期间禁止读取 fixture。

完整过程和最终浏览器证据见仓库 `docs/figma-application-validation.md`。
