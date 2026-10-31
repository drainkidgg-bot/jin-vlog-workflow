# 更新记录

版本号：`大.中.小`。改了流程或文件格式（老的时间线要改才能用）升中位；加规则、修脚本升小位。

## v0.1.0 · 2026-10-31

首个公开版本。

- 五个阶段 skill：`vlog-pipeline`、`vlog-footage`、`vlog-script`、`vlog-cut`、`vlog-publish`；两个核查子代理：`vlog-fact-checker`、`vlog-video-qa`。
- 每条视频一份 `时间线.json`，分镜脚本、口播稿、提词版、占位样片、精剪都从它生成。
- 脚本：素材体检、HDR 转 SDR、联系表、whisper 转写、时间线、提词版、样片和精剪渲染、实录口播对齐、成片体检、结尾关注动效、抠图。
- 规则来自 Jin（@卷小jin）前两条 vlog 的实际制作，用这两条的成片做过端到端测试。
