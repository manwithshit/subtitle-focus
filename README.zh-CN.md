<p align="right">
  <a href="./README.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  <img src="./assets/readme/hero-zh.svg" width="100%" alt="Subtitle Focus：生成黄字语义重点，可选根据参考图校准样式，并在确认后烧录完整视频">
</p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="MIT 许可"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg?logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/FFmpeg-必需-007800.svg?logo=ffmpeg&logoColor=white" alt="需要 FFmpeg"></a>
  <img src="https://img.shields.io/badge/隐私-只处理本机文件-34d399.svg" alt="只处理本机文件">
</p>

**字幕美化与重点烧录（Subtitle Focus）** 是一套面向口播视频的 Agent Skill。它的主旋律是生成黄字语义重点，并在用户确认后烧录到完整视频：

1. **黄字语义重点**：选择完整、真正承载意义的词或短语，直接在完整字幕稿中加粗展示，交给用户确认。
2. **可选样式校准**：用户提供参考截图时，为当前项目调整字幕位置、字号和安全宽度，并保持统一的颜色与底条样式。
3. **确认后烧录全片**：先生成短样片；文字、高亮和样片都确认后，才把字幕烧录到完整视频。

参考截图只用于项目级样式校准，不承诺像素级复刻。词库只提供精确纠正建议，不会未经确认自动改字。Skill 明确从用户导出的 SRT 开始，不转写视频，不调用 Video Use，不运行本地 ASR/OCR，也不根据纯 MD 口播稿猜测时间码。完整视频烧录在本机执行，依赖 Python、FFmpeg 和 FFprobe。

## 真实成片效果

下面来自一个真实的 2160×3850 徽州鱼灯成片。它们展示了样片确认后统一烧录的字幕底条、中英混排和语义重点。截图直接取自最终视频，只裁出字幕区域。

<p align="center">
  <img src="./assets/readme/fish-lantern-cue-02.jpg" width="100%" alt="最终字幕中校正后的项目术语生成华纹以黄色显示">
</p>

<p align="center">
  <img src="./assets/readme/fish-lantern-cue-05.jpg" width="100%" alt="AI 中英混排字幕保持同一基线">
</p>

<p align="center">
  <img src="./assets/readme/fish-lantern-cue-40.jpg" width="100%" alt="3D 被标成黄色重点的最终字幕">
</p>

中文和英文共用一条基线，只有重点词放大，整段文字一次绘制，不会因为逐字描边而产生重叠。用户提供参考截图时，可以只调整当前项目的布局，不改变后续视频继续使用的默认样式。

## 为什么先锁定文字

一个字改动，就可能让所有后续文件过期。上面的真实项目中，字幕 ID 2 和 ID 35 都必须使用项目术语 **生成华纹**。现在 SRT 锁和字幕计划会记录 SHA-256；只要 SRT 发生任何字节变化，旧计划、样片、成片和交付都会直接失效。

<p align="center">
  <img src="./assets/readme/fish-lantern-cue-35.jpg" width="100%" alt="最终视频中第二处生成华纹字幕">
</p>

## 五道确认闸

<p align="center">
  <img src="./assets/readme/workflow-zh.svg" width="100%" alt="校对锁定、高亮确认、样片、最终成片抽帧和交付登记五道流程">
</p>

1. **校对锁定**：逐条核对字幕，只执行用户确认的精确替换，然后按 SHA 锁定 SRT。
2. **高亮确认**：只选择完整、真正承载意义的词或短语，直接在完整字幕稿中加粗展示；任意连续两句至少有一句带重点。
3. **样式与样片**：没有参考图时保持默认高度 82%；收到参考截图时，生成当前项目独立的版本化样式，再渲染短样片等待确认。
4. **全片烧录与抽帧**：样片确认后烧录完整视频，并从该成片中抽取所有修改字幕、所有高亮字幕和首中尾画面。
5. **交付登记**：用唯一 manifest 记录视频、SRT、计划、样式、修改、抽帧和 handoff 的路径与指纹。

文字修改、高亮选择和样片都必须经过用户确认，不能由 Agent 自己跳闸，也不能拿到参考图后直接进入全片烧录。

高亮连续性由脚本确定性检查：最多只能连续一条渲染字幕不带重点。重点必须是完整词、产品名或有意义的短语，不能为了比例拆词，也不能用口水词、连接词凑节奏。短句本身就是一个完整重点时，可以 100% 高亮；长句默认只保留一个主要语义词组，真正并列或对比时才用两个。占比不阻断验证或渲染；长句重点过密时，完整粗体稿后会附上复核提示。

## 分层词库

公开仓库只内置一个有内容的词库：350 条基础词，其中包含 307 条中文常见混淆和 43 条高频英文／产品写法。长期使用的个人词放在 `~/.config/subtitle-focus/glossary.json`；当前视频独有的词汇——包括 AI 产品名——通过项目词库传入。个人词库和项目词库默认为空，由用户自己维护，安装时不会要求提供。

基础词库参考 Apache-2.0 的 [pycorrector](https://github.com/shibing624/pycorrector) 和 [macro-correct](https://github.com/yongzhuo/macro-correct)，但不整库导入；只保留逐条筛选后、不依赖视频声音也能明确判断的精确映射。详见 [词库来源说明](./skill/references/glossary-sources.md)。

```text
项目 > 旧版自定义 > 个人 > 基础
```

词库保存“已知错误形式 → 标准写法”。它只生成带来源的纠正建议，绝不自动改写 SRT。同一个错误形式发生冲突时，项目词库覆盖低优先级词库。

进入 Gate 1 前，用户必须分别明确选择“使用／不使用”个人词库和项目词库。需要的是明确决定，不是强制创建文件。校对报告只显示逻辑层级和 SHA-256，不公开词库绝对路径或用户自定义名称。

项目不开发通用的大小写、数字／单位、代词、标点或中英空格规则引擎。只有用户提出或真实项目验证过的规则，才通过枚举加入。现有中英混排分段和共同基线绘制保持不变。

```bash
python3 skill/scripts/subtitle_focus.py glossary-init --scope personal
python3 skill/scripts/subtitle_focus.py glossary-init \
  --scope project --output /abs/project-glossary.json
```

## 安装

```bash
git clone https://github.com/manwithshit/subtitle-focus.git
cd subtitle-focus

# Codex / 兼容的 Agent 运行时
ln -s "$(pwd)/skill" ~/.agents/skills/subtitle-focus

# Claude Code
ln -s "$(pwd)/skill" ~/.claude/skills/subtitle-focus
```

软链目录名必须与 [skill/SKILL.md](./skill/SKILL.md) 里的 `name` 一致。

打包文件：[dist/subtitle-focus.skill](./dist/subtitle-focus.skill)。

### 环境要求

- Python 3.9+
- 带 FreeType 的 Pillow
- 带 `overlay` 滤镜的 `ffmpeg` 与 `ffprobe`

```bash
python3 skill/scripts/subtitle_focus.py doctor
```

## 第一次跑通

```bash
SCRIPT=skill/scripts/subtitle_focus.py
WORK=/abs/work

python3 "$SCRIPT" proofread \
  --srt /abs/input.srt \
  --no-personal-glossary \
  --no-project-glossary \
  --output "$WORK/text-review.md"

# 根据 SRT 前后文、词库来源、项目资料和用户纠正整理 corrections.json。
python3 "$SCRIPT" correct \
  --srt /abs/input.srt \
  --corrections "$WORK/corrections.json" \
  --output "$WORK/locked-text.srt" \
  --review "$WORK/corrections-review.md"

# 修改表经用户确认后才能执行。
python3 "$SCRIPT" lock \
  --srt "$WORK/locked-text.srt" \
  --output "$WORK/srt-lock.json" \
  --confirmed

python3 "$SCRIPT" plan \
  --srt "$WORK/locked-text.srt" \
  --lock "$WORK/srt-lock.json" \
  --output "$WORK/caption-plan.json"

python3 "$SCRIPT" apply \
  --plan "$WORK/caption-plan.json" \
  --highlights "$WORK/highlight.json" \
  --output "$WORK/caption-plan.highlighted.json"

python3 "$SCRIPT" review \
  --plan "$WORK/caption-plan.highlighted.json" \
  --output "$WORK/highlight-review.md"

python3 "$SCRIPT" validate \
  --plan "$WORK/caption-plan.highlighted.json" \
  --video /abs/input.mp4
```

先把字幕修改表交给用户确认。进入高亮确认时，直接发送重点已加粗的完整字幕稿，不先发送关键词清单或高亮表。确认前不渲染。

## 参考图样式

默认值仍然是 `center_y_ratio: 0.82`。只有用户提交参考截图时，才为当前项目生成一个版本化样式，不改全局默认值。

```bash
python3 "$SCRIPT" style \
  --base skill/assets/default-style.json \
  --reference-image /abs/demo.png \
  --center-y-ratio 0.73 \
  --safe-width-ratio 0.76 \
  --font-size-max 88 \
  --output "$WORK/style-v1.json"

python3 "$SCRIPT" preview \
  --video /abs/input.mp4 \
  --plan "$WORK/caption-plan.highlighted.json" \
  --style "$WORK/style-v1.json" \
  --cue 2 \
  --output "$WORK/cue-2.png"

python3 "$SCRIPT" validate \
  --plan "$WORK/caption-plan.highlighted.json" \
  --video /abs/input.mp4 \
  --style "$WORK/style-v1.json"
```

样式文件会保存参考图路径、SHA-256、尺寸、基础样式指纹和所有明确覆盖值。

## 烧录、抽帧、交付

```bash
python3 "$SCRIPT" render \
  --video /abs/input.mp4 \
  --plan "$WORK/caption-plan.highlighted.json" \
  --style "$WORK/style-v1.json" \
  --output "$WORK/final-subtitled.mp4"

python3 "$SCRIPT" frames \
  --video "$WORK/final-subtitled.mp4" \
  --already-burned \
  --plan "$WORK/caption-plan.highlighted.json" \
  --style "$WORK/style-v1.json" \
  --corrections "$WORK/corrections.json" \
  --output-dir "$WORK/review-frames"

python3 "$SCRIPT" deliver \
  --video "$WORK/final-subtitled.mp4" \
  --srt "$WORK/locked-text.srt" \
  --plan "$WORK/caption-plan.highlighted.json" \
  --style "$WORK/style-v1.json" \
  --corrections "$WORK/corrections.json" \
  --review-dir "$WORK/review-frames" \
  --output "$WORK/delivery.json"
```

`frames` 会生成全尺寸 PNG、`contact-sheet.jpg`、`index.md` 和 `index.json`。如果修改字幕缺少抽帧，或者抽帧不是来自同一个最终成片 SHA，`deliver` 会拒绝交付。

可选 handoff 能复制最终 SRT、生成口播稿、复制已有发布文案；只有显式传入 `--copy-video` 才复制视频。已有文件永不覆盖。

## 命令表

| 命令 | 作用 |
| --- | --- |
| `doctor` | 检查 Pillow、字体、FFmpeg、FFprobe 和 overlay |
| `glossary-init` | 创建可编辑的空白个人词库或项目词库 |
| `proofread` | 使用分层词库输出逐条、带来源的纠正建议 |
| `correct` | 只执行已确认的精确文字替换，不改时间轴 |
| `lock` | 用内容指纹锁定确认后的 SRT |
| `plan` | 把锁定 SRT 切成字幕段 |
| `apply` / `review` | 应用并审核语义高亮 |
| `style` / `preview` | 生成并检查版本化样式 |
| `render` | 烧录字幕 |
| `frames` | 从最终成片抽取修改与高亮证据 |
| `deliver` | 登记唯一交付和可选 handoff |

结构与规则：

- [SRT 文字锁](./skill/references/text-lock-schema.md)
- [高亮计划](./skill/references/highlight-schema.md)
- [参考图样式校准](./skill/references/style-calibration.md)
- [视觉绘制合同](./skill/references/visual-spec.md)
- [交付 manifest](./skill/references/delivery-schema.md)

## 验证仓库

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile skill/scripts/subtitle_focus.py
python3 scripts/build_skill_package.py
```

18 项测试覆盖高亮连续性、短句 100% 高亮、长句过密提示不阻断、竖屏真实像素自动缩放、公开包只含 350 条基础词、词库显式选择、SRT 格式保留、纯 MD 拒绝、真实 FFmpeg 端到端烧录、旧 SRT 失效、参考图来源、抽帧、交付 SHA 和 handoff。

## 默认值与边界

| 项 | 默认值 |
| --- | --- |
| 字体 | 系统苹方 SC Medium |
| 正文字号 | 从画面高度的 4.8% 起算，超出安全宽度时自动缩小 |
| 字幕中心 | 画面高度的 82% |
| 高亮 | 正文 1.34 倍、`#FFD600`、深色描边 |
| 高亮连续性 | 最多连续一条字幕无重点 |
| 重点密度 | 不阻断；语义完整的短句可 100% 高亮，长句过密时提示复核 |
| 底条 | `#505050`、69% 不透明度、28% 边距、40% 圆角 |

- 原 SRT 和原视频永远不覆盖。
- 必须提供带时间码的 SRT；纯 MD 和只有视频的输入会在第一阶段前停止。
- 不调用 Video Use、剪口播、Whisper、ASR 或 OCR。
- Gate 1 必须明确选择使用或跳过个人词库和项目词库。
- Git 会忽略名为 `personal-glossary.json`、`project-glossary.json` 或 `*.private-glossary.json` 的本地词库文件。
- 纠错会保留未涉及的 SRT 换行和连续空格；后续中英混排布局只生成派生计划，不改写锁定 SRT。
- 渲染需要能显示中文的字体。
- 接近 4K 的完整编码需要时间，先用样片抓布局错误。
- 仓库不包含源视频；README 只保留裁切后的最终效果截图。
- 音频混音明确不属于这个 Skill。

## 许可

[MIT](./LICENSE)
