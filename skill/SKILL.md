---
name: subtitle-focus
description: Use when the user wants to proofread and lock an SRT, burn it onto a video with yellow keyword highlights or a CapCut/Jianying-like caption card, calibrate subtitle placement from a reference screenshot, extract review frames for corrected captions, or register a final subtitle delivery.
---

# Subtitle Focus

Turn a reviewed SRT into short caption cards and a traceable final delivery. The agent decides what the words mean; the bundled script owns exact replacement, source locking, layout, rendering, review frames, and hashes. Source SRT and video are read-only.

Work in five gates. Stop at each confirmation gate.

```text
SRT 校对锁定 → 高亮确认 → 样片确认 → 全片抽帧 → 交付登记
```

## Gate 1 — SRT 校对锁定

1. Run `doctor` before first use on a machine.
2. Run `proofread` and inspect every cue against audio, project vocabulary, product names, capitalization, numbers, pronouns, and user corrections. A glossary may flag known forbidden forms.
3. Draft `corrections.json` using [text-lock-schema.md](references/text-lock-schema.md). Never rewrite silently.
4. Run `correct`; show the cue-level before/after table to the user.
5. After explicit text approval, run `lock --confirmed`.

**STOP.** Do not plan highlights from an unlocked SRT. Any byte change to the SRT invalidates its lock, caption plan, sample, and full render. Regenerate them.

## Gate 2 — 高亮文字

1. Run `plan --lock ...` with `--max-chars 16` unless the user asks otherwise.
2. Draft `highlight.json` using [highlight-schema.md](references/highlight-schema.md).
3. Run `apply`, `validate`, and `review`.
4. Show the Markdown review table. Ask for cue ids to add, drop, or retarget.

Selection: meaning-bearing terms only. Default one phrase per cue; zero is allowed. Keep coverage under about 35% of visible characters. Never rewrite the locked SRT during highlighting.

**STOP.** Do not render until the user confirms the highlight list.

## Gate 3 — 样片与参考图样式

1. Copy [default-style.json](assets/default-style.json) or derive a version with `style`.
2. Keep the default `center_y_ratio` at `0.82` when there is no reference demo.
3. When the user supplies a reference screenshot, inspect it and run `style --reference-image ...` with explicit overrides such as `--center-y-ratio`, `--safe-width-ratio`, or `--font-size-max`. The output records the reference image SHA and dimensions. See [style-calibration.md](references/style-calibration.md).
4. Render a 10–15 second clip starting at the first highlight.
5. Run `preview --video ...` for CJK, Latin, and mixed highlights so stills use the target video's real dimensions.
6. Inspect baseline, overlap, clipping, phone-frame safe area, avatar avoidance, and reference-demo alignment.

**STOP.** Full render is forbidden until the user accepts the sample. Style changes create `style-vN.json`; text changes return to Gate 1.

## Gate 4 — 全片与抽帧

1. Run `render` without `--start` or `--duration`.
2. Run `validate --video ...` against the locked SRT and final video duration.
3. Run `frames` against the final rendered video with `--already-burned`, passing `--corrections` whenever corrections exist. It must include every corrected cue, every highlighted segment, and entry/middle/exit frames.
4. Inspect `contact-sheet.jpg` plus each full-resolution frame. Corrected cues missing from review frames are a delivery failure.

## Gate 5 — 唯一交付

Run `deliver` using the final video, locked SRT, highlighted plan, style, corrections, and review directory. The command writes one `subtitle-focus-delivery` manifest with paths, hashes, video metadata, changed cue ids, reviewed cue ids, reference-demo provenance, and handoff files.

Use `--handoff-dir` to copy the final SRT and generate a transcript. Add `--copy-video` only when the user wants the video copied. Add `--publish-copy` when a finished publishing document already exists. Never invent publishing copy.

See [delivery-schema.md](references/delivery-schema.md).

## Command map

```bash
SCRIPT=skill/scripts/subtitle_focus.py

python3 "$SCRIPT" doctor
python3 "$SCRIPT" proofread --srt /abs/in.srt --glossary /abs/glossary.json --output /abs/text-review.md
python3 "$SCRIPT" correct --srt /abs/in.srt --corrections /abs/corrections.json --output /abs/locked-text.srt --review /abs/corrections-review.md
python3 "$SCRIPT" lock --srt /abs/locked-text.srt --output /abs/srt-lock.json --confirmed
python3 "$SCRIPT" plan --srt /abs/locked-text.srt --lock /abs/srt-lock.json --output /abs/caption-plan.json
python3 "$SCRIPT" apply --plan /abs/caption-plan.json --highlights /abs/highlight.json --output /abs/caption-plan.highlighted.json
python3 "$SCRIPT" validate --plan /abs/caption-plan.highlighted.json --video /abs/input.mp4
python3 "$SCRIPT" review --plan /abs/caption-plan.highlighted.json --output /abs/highlight-review.md
python3 "$SCRIPT" style --base skill/assets/default-style.json --reference-image /abs/demo.png --center-y-ratio 0.73 --output /abs/style-v1.json
python3 "$SCRIPT" preview --video /abs/input.mp4 --plan /abs/caption-plan.highlighted.json --style /abs/style-v1.json --cue 2 --output /abs/cue-2.png
python3 "$SCRIPT" render --video /abs/input.mp4 --plan /abs/caption-plan.highlighted.json --style /abs/style-v1.json --output /abs/edit/final-subtitled.mp4
python3 "$SCRIPT" frames --video /abs/edit/final-subtitled.mp4 --already-burned --plan /abs/caption-plan.highlighted.json --style /abs/style-v1.json --corrections /abs/corrections.json --output-dir /abs/edit/review-frames
python3 "$SCRIPT" deliver --video /abs/edit/final-subtitled.mp4 --srt /abs/locked-text.srt --plan /abs/caption-plan.highlighted.json --style /abs/style-v1.json --corrections /abs/corrections.json --review-dir /abs/edit/review-frames --output /abs/edit/delivery.json
```

Run `python3 scripts/subtitle_focus.py <command> --help` for all flags.

## Drawing contract

Visual numbers and typography rules are in [visual-spec.md](references/visual-spec.md). Do not add agent-side drawing hacks. Keep one shared baseline, enlarge only highlighted runs, keep mixed phrases such as `C 组` together, and draw strings as whole runs.

## Do not

| Excuse | Reality |
|---|---|
| “The SRT only changed by one word” | Its hash changed. Re-lock and regenerate every derived artifact. |
| “Highlights are obvious” | Gate 2 is a user decision. Wait. |
| “The default 82% height is always correct” | Keep 82% only without a reference demo; otherwise use a versioned style override. |
| “A few random frames are enough” | Every corrected cue and highlighted segment must appear in review frames. |
| “The final filename tells us what it contains” | Only the delivery manifest is authoritative. |
