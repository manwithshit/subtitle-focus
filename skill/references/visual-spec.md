# Visual spec

Numbers live in [default-style.json](../assets/default-style.json). Copy that file into the work folder as `style-vN.json` only when iterating. Do not invent a parallel theme.

## Theme

- Font: system PingFang, `font_index` 7 = PingFang SC Medium. Empty `font_path` lets the script discover PingFang.ttc.
- Body size: `font_size_ratio` 0.048 of frame height, capped by `font_size_max` on the *body* size.
- Highlight: 1.34× body size, yellow fill, dark outline.
- Body: white, no outline.
- Bubble: gray `[80,80,80]` at alpha 176 (69% opacity). Padding 28% of the highlight size on both axes. Corner radius is Jianying-style `bubble_corner_percent` 40 — 40% of half the bubble height.
- Default position: `center_y_ratio` 0.82. Keep this default when no reference demo is supplied.

## Reference-demo overrides

When the user provides a screenshot demo, create a versioned style with the `style` command and explicit measured overrides. Record the screenshot with `--reference-image`; do not edit `default-style.json` for one project. Preview with `--video` so the still uses the real target dimensions. See [style-calibration.md](style-calibration.md).

## Drawing contract

The renderer owns these rules. Do not reintroduce them as agent-side hacks, and do not “improve” them in the script without a new user decision.

- One shared baseline for every run. Highlighted glyphs grow upward. Latin descenders may sit slightly below the Chinese baseline; that is correct.
- Only highlighted runs use the larger font and the outline.
- Unhighlighted Latin stays at body size on the same baseline. `A 组呢…` must not enlarge `A`.
- Never split one highlight into Latin vs CJK for alignment. `C 组` and `AI 生成` are one run: same size, same baseline.
- Draw each run as a whole string. Do not letter-space character by character; that overlaps outlines.

## Sample stills

When making the review clip, also render stills with `preview --cue` for:

1. A CJK-only highlight
2. A Latin-only highlight, if any exist
3. A mixed CJK+Latin highlight, if any exist
