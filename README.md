# Jin's Vlog Workflow

**卷小jin 的 vlog 工作流**：用 Claude Code，把"现场拍了一堆素材"剪成一条 1 分钟左右、自己出镜口播的竖屏短视频。

这是 Jin（小红书、抖音 [@卷小jin](#关于作者)）自己做 vlog 的方法。每一条规则都来自真实发布过的视频，是一次次修改意见攒下来的；现在整理成通用的流程、规范和脚本，你填上自己的账号设置就能用。

## 它能做什么

| 你做 | Claude 做 |
|---|---|
| 把现场素材发过去，讲讲背景 | 复制、体检、HDR 转 SDR、逐段抽帧看画面、转写原声，整理成素材盘点 |
| 选一个角度 | 给 2–3 个角度和钩子；写口播、排时间线、出分镜脚本和占位样片，事实和措辞先过一遍核查 |
| 对着提词版录一条出镜口播 | 出提词版视频：整段显示、当前句高亮、预告下一句 |
| 把录好的视频发过去 | 转写实录、逐句对齐、按你实际说的重排画面，出无字幕的精剪（含口播和现场原声），自查跳帧、响度、打码 |
| 在剪映里加字幕和 BGM | 准备封面候选帧和抠图、标题、小红书和抖音的发布文案，查审核红线 |
| 点发布 | 归档、写记录、复盘 |

## 流程

```
素材盘点 → 角度和结构 → 口播和分镜（占位样片）→ 提词版，你录口播 → 按实录精剪 → 你在剪映收尾 → 封面和发布 → 归档复盘
```

每个阶段是一个 Claude Code skill，按你说的话自动触发；每到需要你拍板的地方（选角度、审稿、录口播、看精剪、挑封面），Claude 会停下来等你。

| skill / 子代理 | 管什么 |
|---|---|
| `vlog-pipeline` | 总流程、分工、文件约定、你的关口；整套流程的脚本在它的 `scripts/` 里 |
| `vlog-footage` | 素材盘点 |
| `vlog-script` | 角度和钩子、口播、时间线、分镜脚本、占位样片、提词版 |
| `vlog-cut` | 按实录口播精剪、画质和声音、交付 |
| `vlog-publish` | 封面、标题、发布文案、红线检查、归档、复盘 |
| `vlog-fact-checker`（子代理） | 交稿前独立核查事实和措辞 |
| `vlog-video-qa`（子代理） | 交付前独立检查成片 |

核心是每条视频一份 `时间线.json`：口播、分镜脚本、提词版、样片、精剪都从它生成，改稿只改这一份，几样东西永远对得上。

## 快速开始

**需要：**

- [Claude Code](https://claude.com/claude-code)（终端或桌面 App 都行）
- ffmpeg（带 libx264）：macOS 用 `brew install ffmpeg`
- Python 3 和 Pillow：`pip3 install pillow`
- 转写：Apple 芯片的 Mac 用 mlx-whisper，其他电脑用 faster-whisper。Claude 会在临时目录里建环境，第一次要下载约 1.6 GB 的模型
- 推荐 macOS：iPhone 的 HDR 视频转换用系统自带的 `avconvert`，封面抠图用系统的 Vision（macOS 14+）。别的系统也能用，这两步要换办法

**开始：**

1. 下载这个仓库（右上角 Code → Download ZIP，或 `git clone`），用 Claude Code 打开这个文件夹。
2. 说「第一次用，帮我设置账号」。Claude 会问你账号定位、你是谁、结尾口号等，填好 `docs/账号配置.md`；再要一张头像，生成结尾的关注动效。
3. 做第一条：把素材文件拖进对话，说「开始做一条新视频」，讲讲这是什么场合、你想表达什么。
4. 你的意见如果是通用的（比如"开头不要超过一句话"），让 Claude 写回规范里，下一条就不用再说。

## 文件夹里有什么

```
.claude/skills/vlog-pipeline/   总流程，以及所有脚本（scripts/）
.claude/skills/vlog-footage/    素材盘点
.claude/skills/vlog-script/     角度、口播、时间线、提词版
.claude/skills/vlog-cut/        精剪
.claude/skills/vlog-publish/    封面、发布、归档、复盘
.claude/agents/                 两个核查子代理
docs/账号配置.md                你的账号设置（第一次用时填）
CLAUDE.md                       给 Claude 的项目说明
inputs/  outputs/  assets/      素材、每条视频的交付物、复用素材（不进 git）
```

## 更新到新版本

新版本的改动写在 [CHANGELOG.md](CHANGELOG.md)。更新时只替换这两处，你自己的东西不会被覆盖：

- `.claude/skills/vlog-*`
- `.claude/agents/vlog-*`

`docs/账号配置.md`、`CLAUDE.md`、`inputs/`、`outputs/`、`assets/` 是你的，保留不动。如果你在 skill 里写了自己的规则，更新前先把它们挪到账号配置里，或者更新后再合并回去。

## 几条原则

- 事实不夸大，名人的话不确定就写"引用"；外部事实给出来源。
- 不用 AI 合成真人的脸和声音，不用 AI 超分处理人脸。
- 引用别人的片段用官方来源、保留署名、只截几秒。
- 开头要短。

## 关于作者

Jin，设计师，用 AI 做产品。小红书、抖音搜 **@卷小jin**，看这套工作流做出来的视频。

有问题、建议或者用它做出了视频，欢迎在 [Issues](../../issues) 里告诉我。

## 许可

[MIT](LICENSE)。可以自由使用、修改、分享；转载或基于它改出自己的版本时，请保留署名：**基于 Jin's Vlog Workflow（@卷小jin）**。
