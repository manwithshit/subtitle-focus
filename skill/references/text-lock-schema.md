# SRT text review and lock schemas

## glossary.json

Use a glossary to flag known wrong forms without changing the SRT.

```json
{
  "version": 1,
  "forbidden_terms": [
    {
      "text": "生成花纹",
      "suggest": "生成华纹",
      "reason": "project term"
    }
  ]
}
```

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
