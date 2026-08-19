<p align="right">
  <a href="./README.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  <img src="./assets/readme/hero-zh.svg" width="100%" alt="subtitle-focus：把 SRT 烧成黄字重点字幕条，不经过剪映或 CapCut">
</p>

<p align="center">
  <a href="https://github.com/manwithshit/subtitle-focus/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="开源协议"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg?logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/FFmpeg-依赖必需-007800.svg?logo=ffmpeg&logoColor=white" alt="需要 FFmpeg"></a>
  <img src="https://img.shields.io/badge/隐私-只走本机文件-34d399.svg" alt="只走本机文件">
</p>

---

## 这是什么

**`subtitle-focus`** 是一套 Agent Skill + 小型 Python 渲染器。它把 SRT 切成短字幕条，只把真正有意义的词标成黄字，再用 Pillow 和 FFmpeg 烧进视频。

Agent 决定 *标哪些词*。脚本决定 *画在哪、怎么画*。原 SRT 和原片只读，不会被覆盖，也不会上传。

---

## 为什么要做

剪映 / CapCut 能做黄白混排字幕，但样式锁在编辑器里。这套 skill 把同一套语法留在本机：白字、黄重点、灰色圆角条。

- 中文和英文共用一条基线
- 只有高亮词会放大
- `C 组`、`AI 生成` 这类中英混排不拆开
- 整词一次画出去，描边不会把字母糊在一起

---

## 三道闸

<p align="center">
  <img src="./assets/readme/workflow-zh.svg" width="100%" alt="先对高亮词，再看样片，最后才烧全片">
</p>

1. **文字** — `plan` → 写 `highlight.json` → `apply` → `review`。用户确认词表，或按 cue 号改完之前，不渲。
2. **样片** — 烧 10–15 秒试片，并补中文 / 英文 / 中英混排静帧。观感通过之前，不进全片。
3. **全片** — 样片过了，再渲完整成片。

Skill 禁止因为「我觉得静帧没问题」就跳闸。

---

## 安装成 Agent Skill

```bash
git clone https://github.com/manwithshit/subtitle-focus.git
cd subtitle-focus

# Grok
ln -s "$(pwd)/skill" ~/.grok/skills/subtitle-focus

# Claude Code
ln -s "$(pwd)/skill" ~/.claude/skills/subtitle-focus

# Codex / 其他运行时
ln -s "$(pwd)/skill" ~/.agents/skills/subtitle-focus
```

软链目录名必须和 `skill/SKILL.md` 里的 `name` 一致。

### 依赖

- Python 3.9+
- 带 FreeType 的 Pillow
- `ffmpeg` / `ffprobe`，且带 `overlay` 滤镜

```bash
python3 skill/scripts/subtitle_focus.py doctor
```

---

## 第一次跑通

```bash
SCRIPT=skill/scripts/subtitle_focus.py
STYLE=skill/assets/default-style.json

python3 "$SCRIPT" plan \
  --srt /abs/input.srt \
  --output /abs/work/caption_plan.json

# 写好 highlight.json 之后：
python3 "$SCRIPT" apply \
  --plan /abs/work/caption_plan.json \
  --highlights /abs/work/highlight.json \
  --output /abs/work/caption_plan.highlighted.json

python3 "$SCRIPT" review \
  --plan /abs/work/caption_plan.highlighted.json
```

把这张表给用户看。确认之后：

```bash
python3 "$SCRIPT" render \
  --video /abs/input.mp4 \
  --plan /abs/work/caption_plan.highlighted.json \
  --style "$STYLE" \
  --output /abs/work/edit/subtitle-focus-preview-v1.mp4 \
  --start 20 --duration 12
```

样片通过后，去掉 `--start` 和 `--duration` 再渲全片。输出用版本号，不要覆盖源文件。

高亮 JSON：[highlight-schema.md](./skill/references/highlight-schema.md)  
样式与画法：[visual-spec.md](./skill/references/visual-spec.md)

---

## 默认样式

| 项 | 值 |
| --- | --- |
| 字体 | 系统苹方 SC Medium |
| 正文字号 | 画面高度的 4.8% |
| 高亮 | 正文 1.34 倍，`#FFD600`，深色描边 |
| 底条 | `#505050`、69% 透明、28% 边距、剪映式 40% 圆角 |

---

## 边界

- 原 SRT 和原片永远只读。
- 渲染需要一款能画中文的字体。macOS 上会自动找苹方。
- 接近 4K 的整片编码要几分钟；所以先用 10–15 秒样片抓布局问题。
- 仓库不带示例成片。用你自己的本机文件。

---

## 许可

[MIT](./LICENSE)
