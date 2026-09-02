---
name: subtitle-focus
description: Use when the user has a timestamped SRT and wants to proofread it with layered glossaries, lock confirmed text, burn yellow keyword highlights or a CapCut/Jianying-like caption card, calibrate placement from a reference screenshot, review final-video frames, or register delivery. It does not transcribe video, run ASR/OCR, or accept a plain transcript as timeline input.
---

# Subtitle Focus

Turn a reviewed, timestamped SRT into short caption cards and a traceable final delivery. The agent decides what the words mean from SRT context, loaded glossaries, project evidence, and user corrections; the bundled script owns deterministic flags, exact replacement, source locking, mixed CJK/Latin layout, rendering, review frames, and hashes. Source SRT and video are read-only.

Require an exported SRT. A video-only input or a plain line-by-line MD transcript has no accepted timeline in this Skill. Stop and ask the user to export SRT; do not call Video Use, 剪口播, local Whisper, ASR, or OCR.

Work in five gates. Stop at each confirmation gate.

```text
SRT 校对锁定 → 高亮确认 → 样片确认 → 全片抽帧 → 交付登记
```

## Gate 1 — SRT 校对锁定

1. Run `doctor` before first use on a machine.
2. Require a timestamped SRT. Reject plain MD/transcript input and video-only transcription requests.
3. Ask for two explicit choices at project intake: use a personal glossary or explicitly skip it; use a project glossary or explicitly skip it. Do not ask during installation, and do not start formal proofreading until both choices are recorded by the `proofread` flags.
4. Run `proofread`. The base glossary loads automatically; add `--domain ai` when relevant. Read [text-lock-schema.md](references/text-lock-schema.md) for the explicit choices, layering, privacy behavior, and schema.
   The base/domain boundary and public-source review policy are documented in [glossary-sources.md](references/glossary-sources.md).
5. Inspect every cue using SRT neighbors, loaded glossary provenance, project vocabulary, product names, project files, and user corrections. Only apply spelling, capitalization, number, unit, pronoun, or spacing rules when an actual user/project rule or enumerated glossary entry exists. Do not invent a general normalization policy.
6. Draft `corrections.json`. Glossary matches are suggestions, never automatic edits. Never rewrite silently.
7. Run `correct`; show the cue-level before/after table to the user. The output must preserve unmentioned line breaks and repeated spaces in the SRT text.
8. After explicit text approval, run `lock --confirmed`.

**STOP.** Do not plan highlights from an unlocked SRT. Any byte change to the SRT invalidates its lock, caption plan, sample, and full render. Regenerate them.

## Gate 2 — 高亮文字

1. Run `plan --lock ...` with `--max-chars 16` unless the user asks otherwise.
2. Draft `highlight.json` using [highlight-schema.md](references/highlight-schema.md).
3. Run `apply` and `review`. Adjust the choices until the cadence report passes, then run `validate`.
4. Send the user the complete caption manuscript in timeline order, with every proposed highlight marked directly in the sentence using Markdown bold. Do not send a separate keyword list or highlight table first. Ask the user to confirm the bold locations or name the sentences that need retargeting.

Selection: meaning-bearing complete words or phrases only. Treat each rendered caption segment as one sentence. Every adjacent pair must contain at least one highlighted segment, so a run of unhighlighted sentences can be at most one. Highlighting every sentence is allowed when it improves continuity, and a short semantically atomic sentence may be highlighted in full. Do not split a word, product name, or phrase merely to reduce a percentage. Do not highlight filler, transitions, or low-information words just to satisfy cadence. Coverage is reported for review but never blocks a plan. If cadence cannot be satisfied with a meaningful highlight, report the conflicting segment ids for user review. Never rewrite the locked SRT during highlighting.

**STOP.** Do not render until the user confirms the bolded complete manuscript.

## Gate 3 — 样片与参考图样式

1. Copy [default-style.json](assets/default-style.json) or derive a version with `style`.
2. Keep the default `center_y_ratio` at `0.82` when there is no reference demo.
3. When the user supplies a reference screenshot, inspect it and run `style --reference-image ...` with explicit overrides such as `--center-y-ratio`, `--safe-width-ratio`, or `--font-size-max`. The output records the reference image SHA and dimensions. See [style-calibration.md](references/style-calibration.md).
4. Render a 10–15 second clip starting at the first highlight.
5. Run `preview --video ...` for CJK, Latin, and mixed highlights so stills use the target video's real dimensions.
6. Inspect baseline, overlap, clipping, phone-frame safe area, avatar avoidance, and reference-demo alignment.
7. Run `validate --video ... --style ...` to measure every caption with the actual video dimensions and selected font. The renderer may shrink a caption to `font_size_min`; a caption that still exceeds the safe pixel width fails.

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
python3 "$SCRIPT" glossary-init --scope personal
python3 "$SCRIPT" proofread --srt /abs/in.srt --domain ai --no-personal-glossary --no-project-glossary --output /abs/text-review.md
python3 "$SCRIPT" correct --srt /abs/in.srt --corrections /abs/corrections.json --output /abs/locked-text.srt --review /abs/corrections-review.md
python3 "$SCRIPT" lock --srt /abs/locked-text.srt --output /abs/srt-lock.json --confirmed
python3 "$SCRIPT" plan --srt /abs/locked-text.srt --lock /abs/srt-lock.json --output /abs/caption-plan.json
python3 "$SCRIPT" apply --plan /abs/caption-plan.json --highlights /abs/highlight.json --output /abs/caption-plan.highlighted.json
python3 "$SCRIPT" review --plan /abs/caption-plan.highlighted.json --output /abs/highlight-review.md
python3 "$SCRIPT" style --base skill/assets/default-style.json --reference-image /abs/demo.png --center-y-ratio 0.73 --output /abs/style-v1.json
python3 "$SCRIPT" validate --plan /abs/caption-plan.highlighted.json --video /abs/input.mp4 --style /abs/style-v1.json
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
| “The video or MD is enough to recover timing” | This Skill requires exported SRT and does not run ASR/OCR. |
| “A glossary match is certainly correct” | It is a sourced suggestion. Show it and wait for text approval. |
| “No glossary file means no decision is needed” | Gate 1 still requires explicit personal and project skip choices. |
| “General typography rules are obvious” | Preserve the SRT. Add only user-requested or enumerated rules. |
| “Flattening SRT lines is harmless” | The render plan may derive one display line, but the locked SRT must preserve unmentioned whitespace. |
| “Four plain sentences in a row are acceptable” | Every adjacent pair needs at least one highlighted segment; validation blocks longer plain runs. |
| “A short sentence cannot be highlighted in full” | It may be fully highlighted when the whole sentence is one meaningful point; coverage remains informational. |
