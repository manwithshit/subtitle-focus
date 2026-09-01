# SRT text review and lock schemas

## Layered glossaries

`proofread` requires a timestamped SRT. It does not call ASR, OCR, Video Use, or any speech-cutting Skill. The bundled base glossary loads automatically; add `--domain ai`, a personal glossary, or a project glossary when relevant.

Precedence is deterministic:

```text
project > legacy custom > personal > domain > base
```

The higher layer replaces a lower-layer entry only when both target the exact same `text`. Glossaries flag known wrong forms without changing the SRT. ASCII terms use token boundaries, so `ai` does not match the middle of `said`.

Create an editable empty glossary:

```bash
python3 scripts/subtitle_focus.py glossary-init --scope personal
python3 scripts/subtitle_focus.py glossary-init --scope project --output /abs/project-glossary.json
```

The default personal location is `~/.config/subtitle-focus/glossary.json` and loads automatically when it exists. An explicit `--personal-glossary` replaces that default path for the run.

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

`correct` changes text only and serializes the original cue ids and timecodes unchanged. It fails when the cue or exact source text cannot be found.

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
