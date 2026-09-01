# Delivery manifest

`deliver` writes one authoritative JSON record after rendering and frame review.

Required evidence:

- final video path, SHA-256, dimensions, and duration;
- locked SRT path, SHA-256, cue count, and time range;
- highlighted plan path, SHA-256, and highlight count;
- style path, SHA-256, vertical position, and reference-demo provenance;
- correction file and changed cue ids when corrections exist;
- review directory, reviewed cue ids, contact sheet, and the final-video SHA used for extraction;
- handoff copies when requested.

The command rejects delivery when a corrected cue has no review frame, review frames were not extracted from the already-burned final video, the review-video SHA differs from the delivery-video SHA, or the SRT extends beyond the video.

Example handoff:

```bash
python3 scripts/subtitle_focus.py deliver \
  --video /abs/final.mp4 \
  --srt /abs/locked.srt \
  --plan /abs/caption-plan.highlighted.json \
  --style /abs/style-v1.json \
  --corrections /abs/corrections.json \
  --review-dir /abs/review-frames \
  --output /abs/delivery.json \
  --handoff-dir /abs/50_Temp/drafts/project \
  --name Final \
  --copy-video \
  --publish-copy /abs/publish-copy.md
```

The handoff directory receives `Final.mp4`, `Final.srt`, `Final-transcript.md`, `Final-publish-copy.md`, and `Final-delivery.json`. Existing files are never overwritten.
