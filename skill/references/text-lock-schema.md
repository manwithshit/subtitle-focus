# SRT text review and lock schemas

## Layered glossaries

`proofread` requires a timestamped SRT. It does not call ASR, OCR, Video Use, or any speech-cutting Skill. The bundled base glossary loads automatically.

At Gate 1, make one explicit choice for each user-controlled layer:

```bash
# No personal or project glossary for this run.
python3 scripts/subtitle_focus.py proofread \
  --srt /abs/input.srt \
  --no-personal-glossary \
  --no-project-glossary \
  --output /abs/text-review.md

# Use the default personal glossary and a project glossary.
python3 scripts/subtitle_focus.py proofread \
  --srt /abs/input.srt \
  --use-default-personal \
  --project-glossary /abs/project-glossary.json \
  --output /abs/text-review.md
```

The choices are required at project intake, not installation. `proofread` refuses to run when either choice is missing. An explicit personal path may replace `--use-default-personal`.

Precedence is deterministic:

```text
project > legacy custom > personal > base
```

The higher layer replaces a lower-layer entry only when both target the exact same `text`. Glossaries flag known wrong forms without changing the SRT. ASCII terms use token boundaries, so `ai` does not match the middle of `said`.

Create an editable empty glossary:

```bash
python3 scripts/subtitle_focus.py glossary-init --scope personal
python3 scripts/subtitle_focus.py glossary-init --scope project --output /abs/project-glossary.json
```

The default personal location is `~/.config/subtitle-focus/glossary.json`, but it loads only after `--use-default-personal`. Installation never creates or reads it automatically.

The Markdown review records logical layer names, SHA-256 values, and the two explicit choices. It omits glossary absolute paths and user-defined glossary names. Local delivery manifests may still contain operational file paths.

## glossary.json

```json
{
  "version": 1,
  "name": "徽州鱼灯项目词库",
  "forbidden_terms": [
    {
      "text": "生成花纹",
      "suggest": "生成华纹",
      "reason": "project term",
      "category": "project"
    }
  ]
}
```

`text` is an exact known-wrong form. `suggest` is the proposed canonical form. `reason` and `category` are optional audit metadata. Do not put a correct canonical term in `text`, and do not use full-sentence libraries for automatic rewriting.

There is no general capitalization, number/unit, pronoun, punctuation, or CJK/Latin spacing engine. Add only concrete variants requested by users or evidenced by real projects. The existing mixed-script renderer and segmentation behavior stay separate from text correction.

## corrections.json

Every correction targets one cue and one exact string. `occurrence` is `"all"` or a 1-based integer; default is `1`.

```json
{
  "version": 1,
  "items": [
    {
      "cue_id": 35,
      "find": "生成花纹",
      "replace": "生成华纹",
      "occurrence": 1,
      "reason": "confirmed project term"
    }
  ]
}
```

`correct` changes only the declared exact strings and serializes the original cue ids and timecodes unchanged. Unmentioned internal line breaks and repeated spaces remain intact. It fails when the cue or exact source text cannot be found. The later caption plan may derive a single display line for the existing mixed-script layout; that derived layout does not rewrite the locked SRT.

## srt-lock.json

`lock --confirmed` writes this manifest after user approval:

```json
{
  "version": 1,
  "kind": "subtitle-focus-srt-lock",
  "confirmed": true,
  "locked_at": "2026-09-01T00:00:00+00:00",
  "source": {
    "path": "/abs/locked.srt",
    "sha256": "...",
    "cue_count": 57,
    "first_start_ms": 500,
    "last_end_ms": 90333
  }
}
```

The caption plan embeds the lock SHA and source SHA. `apply`, `validate`, `review`, `preview`, `render`, `frames`, and `deliver` fail when the source SRT changes.
