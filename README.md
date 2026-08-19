<p align="right">
  <strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="subtitle-focus: burn an SRT as yellow-keyword caption cards without CapCut or Jianying">
</p>

<p align="center">
  <a href="https://github.com/manwithshit/subtitle-focus/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg?logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/FFmpeg-Required-007800.svg?logo=ffmpeg&logoColor=white" alt="FFmpeg required"></a>
  <img src="https://img.shields.io/badge/Privacy-Local_files_only-34d399.svg" alt="Local files only">
</p>

---

## What this is

**`subtitle-focus`** is an Agent Skill plus a small Python renderer. It turns an SRT into short caption cards, marks only the words that matter in yellow, and burns the result onto a video with Pillow and FFmpeg.

The agent decides *which words matter*. The script decides *where and how they are drawn*. Source SRT and video stay read-only. Nothing is uploaded.

---

## Why it exists

CapCut / Jianying can do mixed-color captions, but the look is locked inside those editors. This skill keeps the same grammar — white body, yellow keyword, gray pill — as a repeatable local pipeline:

- one shared baseline for Chinese and Latin
- only highlighted text gets larger
- mixed phrases such as `C 组` or `AI 生成` stay one run
- words are drawn as whole strings so outlines do not overlap

---

## Three gates

<p align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="Confirm highlight words, review a short sample, then burn the full video">
</p>

1. **Text** — `plan` → draft `highlight.json` → `apply` → `review`. Stop until the user confirms the table, or sends cue-level edits.
2. **Sample** — burn a 10–15 second clip plus stills for CJK, Latin, and mixed highlights. Stop until the look is accepted.
3. **Full cut** — render the whole video only after the sample passes.

The skill forbids skipping a gate because the stills “look fine” to the agent.

---

## Install as an Agent Skill

```bash
git clone https://github.com/manwithshit/subtitle-focus.git
cd subtitle-focus

# Grok
ln -s "$(pwd)/skill" ~/.grok/skills/subtitle-focus

# Claude Code
ln -s "$(pwd)/skill" ~/.claude/skills/subtitle-focus

# Codex / other agent runtimes
ln -s "$(pwd)/skill" ~/.agents/skills/subtitle-focus
```

The symlink name must match the `name` field in `skill/SKILL.md`.

### Prerequisites

- Python 3.9+
- Pillow with FreeType
- `ffmpeg` and `ffprobe`, with the `overlay` filter

```bash
python3 skill/scripts/subtitle_focus.py doctor
```

---

## First successful run

```bash
SCRIPT=skill/scripts/subtitle_focus.py
STYLE=skill/assets/default-style.json

python3 "$SCRIPT" plan \
  --srt /abs/input.srt \
  --output /abs/work/caption_plan.json

# draft highlight.json, then:
python3 "$SCRIPT" apply \
  --plan /abs/work/caption_plan.json \
  --highlights /abs/work/highlight.json \
  --output /abs/work/caption_plan.highlighted.json

python3 "$SCRIPT" review \
  --plan /abs/work/caption_plan.highlighted.json
```

Show that table to the human. After they confirm:

```bash
python3 "$SCRIPT" render \
  --video /abs/input.mp4 \
  --plan /abs/work/caption_plan.highlighted.json \
  --style "$STYLE" \
  --output /abs/work/edit/subtitle-focus-preview-v1.mp4 \
  --start 20 --duration 12
```

After the sample is accepted, drop `--start` and `--duration` for the full cut. Version every output. Never overwrite the source.

Highlight JSON schema: [`skill/references/highlight-schema.md`](./skill/references/highlight-schema.md).  
Visual numbers and drawing contract: [`skill/references/visual-spec.md`](./skill/references/visual-spec.md).

---

## Defaults

| Token | Value |
| --- | --- |
| Font | System PingFang SC Medium |
| Body size | 4.8% of frame height |
| Highlight | 1.34× body, `#FFD600`, dark outline |
| Bubble | `#505050` at 69% opacity, 28% padding, Jianying-style 40% corner |

---

## Limits

- Source SRT and video are never replaced.
- The renderer needs a CJK-capable font. On macOS it discovers PingFang automatically.
- Full-length encodes of 4K-class files take a few minutes; the 10–15s sample exists so you do not find layout bugs after that wait.
- This repository does not include example footage. Bring your own local files.

---

## License

[MIT](./LICENSE)
