---
name: subtitle-focus
description: Use when the user wants SRT burned onto a video with yellow keyword highlights, mixed-color caption cards, or a CapCut/Jianying-like subtitle look without those editors.
---

# Subtitle Focus

Turn an SRT into short caption cards. The agent decides *which words matter*; the bundled script decides *where and how they are drawn*. Source SRT and video are read-only.

Work in three gates. Stop at each gate until the user confirms. Do not skip ahead because the stills look fine to you.

```
文字确认 → 样片确认 → 全片
```

## Gate 1 — 文字

1. `doctor` before first use on a machine.
2. `plan` the SRT (`--max-chars 16` unless the user asks otherwise).
3. Draft `highlight.json` from the plan using [highlight-schema.md](references/highlight-schema.md).
4. `apply` then `validate`. If a phrase is unmatched, fix `highlight.json` and apply again.
5. `review` and show the user the markdown table. Ask them to reply with cue ids to add, drop, or retarget.

**STOP.** Do not render a clip or a still until the user confirms the highlight list, or sends specific cue-level edits.

Selection: meaning-bearing terms only (product names, commands, numbers, outcomes, contrasts). Default one phrase per cue; zero is allowed. Coverage stays under ~35% of visible characters. Never rewrite SRT text.

## Gate 2 — 样片

After highlight confirmation:

1. Copy [default-style.json](assets/default-style.json) into the work folder. Visual numbers and the drawing contract are in [visual-spec.md](references/visual-spec.md).
2. Render a 10–15s clip that starts at the first highlighted cue. Also render stills for one CJK highlight, one Latin highlight, and one mixed highlight when those exist (`preview --cue`).
3. Inspect the clip and stills: no letter overlap, unhighlighted Latin not enlarged, mixed phrases on one baseline, Chinese glyphs intact, bubble not clipped.

**STOP.** Full-length render is forbidden until the user accepts the sample. Style nits go into a new `style-vN.json`; highlight nits go back to Gate 1. Version every output. Put new media under the work folder's `edit/` directory.

## Gate 3 — 全片

Omit `--start` and `--duration`. After ffmpeg:

- `validate` the highlighted plan
- `ffprobe` video and audio duration
- Extract entry, a mid highlight, an exit frame, plus any cue the user previously flagged

Report missing fonts, unmatched highlights, and render failures explicitly.

## Commands

Run `python3 scripts/subtitle_focus.py <command> --help` for flags.

```bash
python3 scripts/subtitle_focus.py doctor
python3 scripts/subtitle_focus.py plan --srt /abs/in.srt --output /abs/caption_plan.json
python3 scripts/subtitle_focus.py apply --plan /abs/caption_plan.json --highlights /abs/highlight.json --output /abs/caption_plan.highlighted.json
python3 scripts/subtitle_focus.py validate --plan /abs/caption_plan.highlighted.json
python3 scripts/subtitle_focus.py review --plan /abs/caption_plan.highlighted.json
python3 scripts/subtitle_focus.py preview --plan /abs/caption_plan.highlighted.json --style /abs/style.json --output /abs/card.png --cue 57
python3 scripts/subtitle_focus.py render --video /abs/in.mp4 --plan /abs/caption_plan.highlighted.json --style /abs/style.json --output /abs/edit/subtitle-focus-preview-v1.mp4 --start 20 --duration 12
```

Full render: same `render` command without `--start` / `--duration`.

## Do not

| Excuse | Reality |
|---|---|
| “Highlights are obvious, I'll preview first” | Gate 1 is the product decision. Wait. |
| “Stills look good, I'll just cut the full film” | Gate 2 is for the user, not for you. |
| “Latin should top-align / track tighter” | That overlap and mixed-baseline bugs. See visual-spec. |
| “I'll split `C 组` so C looks Latin” | One highlight = one run. |
