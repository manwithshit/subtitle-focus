# Highlight and caption plan schemas

## highlight.json

```json
{
  "version": 1,
  "global_terms": ["Claude Code"],
  "items": [
    {
      "cue_id": 14,
      "text": "Obsidian",
      "occurrence": "all",
      "reason": "本句关键产品"
    },
    {
      "segment_id": "15-1",
      "text": "Gemini CLI",
      "occurrence": 1,
      "reason": "教程对象"
    }
  ]
}
```

Rules:

- One of `cue_id` or `segment_id` is required for each item.
- `text` must occur verbatim in the target caption. Latin text matching is case-insensitive.
- `occurrence` is `"all"` or a 1-based integer. Default: `1`.
- `reason` is optional and is never rendered.
- `global_terms` applies to every exact occurrence. Keep it empty unless repetition is intentional.
- Multiple items may share one `cue_id` when two phrases both deserve emphasis (`卡顿感` and `不衔接感`).
- Highlight the headword, not the qualifier: `Prompt` not `第二段 Prompt`, unless the qualifier is the point.
- The policy is evaluated on rendered caption segments, not raw SRT blocks. Every pair of adjacent segments must include at least one segment with a highlight; two consecutive plain segments fail validation.
- Highlights must be complete words, product names, or meaning-bearing phrases. Never cut `鲸鱼` down to `鲸` merely to reduce coverage.
- A short semantically atomic segment may be highlighted in full. Coverage is still recorded per segment and for the whole plan, but it is informational and never fails validation.
- Do not highlight filler, transitions, or low-information words solely to satisfy cadence. If no meaningful phrase exists, leave the cadence conflict visible for user review.
- `apply` always writes the candidate plan so `review` can show the complete manuscript with proposed highlights rendered as Markdown bold. It must not output a separate keyword list or keyword-first table. Policy violations appear after the manuscript. `validate`, `preview`, `render`, `frames`, and `deliver` reject a plan that violates cadence. Real fit is checked separately from semantic coverage using actual video pixels and the selected style.

## caption_plan.json

The script owns this schema. Generate it only from a confirmed SRT lock. Do not hand-edit timecodes, source hashes, lock metadata, or highlight offsets.

```json
{
  "version": 1,
  "source_srt": "/absolute/input.srt",
  "source_sha256": "...",
  "source_lock": {
    "path": "/absolute/srt-lock.json",
    "sha256": "...",
    "confirmed": true,
    "source_sha256": "..."
  },
  "segments": [
    {
      "id": "15-1",
      "cue_id": 15,
      "start_ms": 23666,
      "end_ms": 26700,
      "text": "去嵌入Gemini的CLI命令行版本",
      "highlights": [
        {"start": 3, "end": 9, "text": "Gemini"}
      ]
    }
  ]
}
```

`start` is inclusive and `end` is exclusive, using Python/JSON string character offsets. The renderer verifies that `text[start:end]` still equals the stored highlight text.

Every downstream command also verifies the current source SRT SHA. If the SRT changes, discard the plan and regenerate it from a new confirmed lock.

Applied plans also record this deterministic policy:

```json
{
  "highlight_policy": {
    "version": 2,
    "coverage_mode": "informational",
    "max_consecutive_plain_segments": 1
  }
}
```
