# Reference-demo style calibration

The bundled default stays at `center_y_ratio: 0.82`. A user-provided screenshot is an explicit reason to create a versioned override; it does not change the global default.

## Workflow

1. Inspect the screenshot and target video together.
2. Estimate the caption-card center as a ratio of full image height.
3. Check the phone frame, lower controls, avatar, and other protected regions.
4. Derive a style with the reference image plus explicit numeric overrides.
5. Preview on the actual video dimensions with `preview --video`.

```bash
python3 scripts/subtitle_focus.py style \
  --base assets/default-style.json \
  --reference-image /abs/demo.png \
  --center-y-ratio 0.73 \
  --safe-width-ratio 0.76 \
  --font-size-max 88 \
  --output /abs/style-v1.json
```

When the layout reserves a fixed caption band (for example a strip between a demo window and a portrait window), add its edges so oversized fonts fail before any sample render:

```bash
python3 scripts/subtitle_focus.py style \
  --base assets/default-style.json \
  --center-y-ratio 0.62 \
  --band-top-ratio 0.58125 \
  --band-bottom-ratio 0.665625 \
  --output /abs/style-v1.json
```

Ratios are edge pixels divided by video height (1116/1920, 1278/1920 here). `validate --style` then reports `band_margin_top_min`, `band_margin_bottom_min`, `card_height_max` and the widest segment.

The generated style records the reference path, SHA-256, dimensions, base-style SHA, and overrides under `_meta`. The renderer ignores `_meta`; the delivery manifest preserves it as provenance.

Do not infer a permanent default from one project's demo. Keep each adjustment in `style-vN.json`.
