#!/usr/bin/env python3
"""Build and render semantically highlighted subtitles from SRT files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont, features


TIMECODE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)
CLAUSE_RE = re.compile(r".*?[，。！？；：,.!?;:](?:\s+|$)?|.+$", re.S)
FONT_CANDIDATES = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
PINGFANG_SC_MEDIUM_INDEX = 7


class FocusError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FocusError(f"Cannot read JSON {path}: {exc}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    refuse_existing(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refuse_existing(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FocusError(f"Refusing to overwrite existing output: {path}")


def ms_from_timecode(value: str) -> int:
    h, m, rest = value.replace(",", ".").split(":")
    seconds, millis = rest.split(".")
    return ((int(h) * 60 + int(m)) * 60 + int(seconds)) * 1000 + int(millis)


def clean_caption(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    return re.sub(r"\s+", " ", text).strip()


def parse_srt(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="gb18030")
    blocks = re.split(r"\r?\n\s*\r?\n", raw.strip())
    cues: list[dict[str, Any]] = []
    for seq, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        time_line = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_line is None:
            continue
        match = TIMECODE_RE.search(lines[time_line])
        if not match:
            raise FocusError(f"Malformed timecode in block {seq}: {lines[time_line]}")
        cue_id = seq
        if time_line > 0 and lines[time_line - 1].strip().isdigit():
            cue_id = int(lines[time_line - 1].strip())
        text = clean_caption(lines[time_line + 1 :])
        if not text:
            continue
        start_ms = ms_from_timecode(match.group("start"))
        end_ms = ms_from_timecode(match.group("end"))
        if end_ms <= start_ms:
            raise FocusError(f"Cue {cue_id} has non-positive duration")
        cues.append({"cue_id": cue_id, "start_ms": start_ms, "end_ms": end_ms, "text": text})
    if not cues:
        raise FocusError(f"No subtitle cues found in {path}")
    return cues


def char_units(ch: str) -> float:
    if ch.isspace():
        return 0.3
    if unicodedata.east_asian_width(ch) in {"W", "F", "A"}:
        return 1.0
    return 0.56


def text_units(text: str) -> float:
    return sum(char_units(ch) for ch in text)


def safe_cut(text: str, target_units: float) -> int:
    total = 0.0
    cut = 0
    preferred = 0
    for idx, ch in enumerate(text, start=1):
        total += char_units(ch)
        if ch in "，。！？；：,.!?;:、/ " or text[max(0, idx - 2) : idx] in {"但是", "所以", "然后"}:
            preferred = idx
        if total > target_units:
            cut = idx - 1
            break
    if cut <= 0:
        cut = min(len(text), max(1, int(target_units)))
    if preferred >= max(1, int(cut * 0.58)):
        cut = preferred
    if 0 < cut < len(text) and text[cut - 1].isspace():
        left = cut - 1
        right = cut
        while left > 0 and text[left - 1].isascii() and (text[left - 1].isalnum() or text[left - 1] in "_.+-/#"):
            left -= 1
        while right < len(text) and text[right].isspace():
            right += 1
        while right < len(text) and text[right].isascii() and (text[right].isalnum() or text[right] in "_.+-/#"):
            right += 1
        if left < cut - 1 and right > cut and text_units(text[:right]) <= target_units * 1.2:
            cut = right
        elif left < cut - 1 and text_units(text[:left]) >= target_units * 0.5:
            cut = left
    while 0 < cut < len(text) and text[cut - 1].isascii() and text[cut - 1].isalnum() and text[cut].isascii() and text[cut].isalnum():
        cut -= 1
    if cut <= 0:
        cut = min(len(text), max(1, int(target_units)))
    return cut


def split_piece(text: str, max_units: float) -> list[str]:
    chunks: list[str] = []
    remainder = text.strip()
    while remainder and text_units(remainder) > max_units:
        if text_units(remainder) <= max_units + 2.0:
            chunks.append(remainder)
            remainder = ""
            break
        bracket_candidates = [
            pos for pos, ch in enumerate(remainder)
            if ch in "（(" and max_units * 0.42 <= text_units(remainder[:pos]) <= max_units
        ]
        if bracket_candidates:
            cut = bracket_candidates[-1]
        else:
            cut = safe_cut(remainder, max_units)
        part = remainder[:cut].strip()
        if not part:
            break
        chunks.append(part)
        remainder = remainder[cut:].strip()
    if remainder:
        chunks.append(remainder)
    return chunks


def split_caption(text: str, max_units: float) -> list[str]:
    clauses = [m.group(0).strip() for m in CLAUSE_RE.finditer(text) if m.group(0).strip()]
    if not clauses:
        clauses = [text]
    result: list[str] = []
    pending = ""
    for clause in clauses:
        candidate = f"{pending}{clause}" if pending else clause
        if text_units(candidate) <= max_units:
            pending = candidate
            continue
        if pending:
            result.append(pending)
            pending = ""
        if text_units(clause) <= max_units:
            pending = clause
        else:
            result.extend(split_piece(clause, max_units))
    if pending:
        result.append(pending)
    return result or [text]


def allocate_times(start_ms: int, end_ms: int, parts: list[str]) -> list[tuple[int, int]]:
    if len(parts) == 1:
        return [(start_ms, end_ms)]
    weights = [max(0.5, text_units(part)) for part in parts]
    total = sum(weights)
    duration = end_ms - start_ms
    boundaries = [start_ms]
    cumulative = 0.0
    for weight in weights[:-1]:
        cumulative += weight
        boundaries.append(start_ms + round(duration * cumulative / total))
    boundaries.append(end_ms)
    for idx in range(1, len(boundaries)):
        boundaries[idx] = max(boundaries[idx], boundaries[idx - 1] + 1)
    boundaries[-1] = end_ms
    return list(zip(boundaries[:-1], boundaries[1:]))


def command_plan(args: argparse.Namespace) -> None:
    srt = Path(args.srt).expanduser().resolve()
    cues = parse_srt(srt)
    segments: list[dict[str, Any]] = []
    for cue in cues:
        parts = split_caption(cue["text"], args.max_chars)
        times = allocate_times(cue["start_ms"], cue["end_ms"], parts)
        for part_no, (text, timing) in enumerate(zip(parts, times), start=1):
            segments.append(
                {
                    "id": f'{cue["cue_id"]}-{part_no}',
                    "cue_id": cue["cue_id"],
                    "start_ms": timing[0],
                    "end_ms": timing[1],
                    "text": text,
                    "highlights": [],
                }
            )
    digest = hashlib.sha256(srt.read_bytes()).hexdigest()
    plan = {
        "version": 1,
        "source_srt": str(srt),
        "source_sha256": digest,
        "segmentation": {"max_chars": args.max_chars, "method": "semantic-punctuation-v1"},
        "statistics": {"cue_count": len(cues), "segment_count": len(segments)},
        "segments": segments,
    }
    write_json(Path(args.output).expanduser().resolve(), plan)
    print(json.dumps(plan["statistics"], ensure_ascii=False))


def find_occurrences(text: str, term: str) -> list[tuple[int, int]]:
    if not term:
        return []
    flags = re.IGNORECASE if any(ch.isascii() and ch.isalpha() for ch in term) else 0
    pattern = re.escape(term)
    if term[0].isascii() and term[0].isalnum():
        pattern = r"(?<![A-Za-z0-9])" + pattern
    if term[-1].isascii() and term[-1].isalnum():
        pattern = pattern + r"(?![A-Za-z0-9])"
    return [(m.start(), m.end()) for m in re.finditer(pattern, text, flags)]


def add_range(segment: dict[str, Any], start: int, end: int) -> None:
    entry = {"start": start, "end": end, "text": segment["text"][start:end]}
    if entry not in segment["highlights"]:
        segment["highlights"].append(entry)


def command_apply(args: argparse.Namespace) -> None:
    plan = load_json(Path(args.plan).expanduser().resolve())
    choices = load_json(Path(args.highlights).expanduser().resolve())
    if plan.get("version") != 1 or choices.get("version") != 1:
        raise FocusError("Only schema version 1 is supported")
    segments = plan.get("segments")
    if not isinstance(segments, list):
        raise FocusError("caption plan has no segments array")
    for segment in segments:
        segment["highlights"] = []
    unmatched: list[str] = []
    for term in choices.get("global_terms", []):
        found = 0
        for segment in segments:
            for start, end in find_occurrences(segment["text"], str(term)):
                add_range(segment, start, end)
                found += 1
        if not found:
            unmatched.append(f'global term "{term}"')
    for item_no, item in enumerate(choices.get("items", []), start=1):
        term = str(item.get("text", ""))
        if "segment_id" in item:
            targets = [s for s in segments if s["id"] == str(item["segment_id"])]
        elif "cue_id" in item:
            targets = [s for s in segments if s["cue_id"] == int(item["cue_id"])]
        else:
            raise FocusError(f"Highlight item {item_no} needs cue_id or segment_id")
        matches: list[tuple[dict[str, Any], int, int]] = []
        for segment in targets:
            matches.extend((segment, start, end) for start, end in find_occurrences(segment["text"], term))
        occurrence = item.get("occurrence", 1)
        selected = matches if occurrence == "all" else matches[int(occurrence) - 1 : int(occurrence)]
        if not targets or not selected:
            unmatched.append(f'item {item_no} "{term}"')
            continue
        for segment, start, end in selected:
            add_range(segment, start, end)
    if unmatched:
        raise FocusError("Unmatched highlights: " + ", ".join(unmatched))
    for segment in segments:
        ordered = sorted(
            segment["highlights"],
            key=lambda item: (item["start"], -(item["end"] - item["start"])),
        )
        normalized: list[dict[str, Any]] = []
        for highlight in ordered:
            if not normalized or highlight["start"] >= normalized[-1]["end"]:
                normalized.append(highlight)
            elif highlight["end"] <= normalized[-1]["end"]:
                continue
            else:
                raise FocusError(f'Partially overlapping highlights in segment {segment["id"]}')
        segment["highlights"] = normalized
        previous_end = -1
        for highlight in segment["highlights"]:
            previous_end = highlight["end"]
    plan["highlight_source"] = str(Path(args.highlights).expanduser().resolve())
    plan["statistics"] = {
        **plan.get("statistics", {}),
        "highlight_segment_count": sum(bool(s["highlights"]) for s in segments),
        "highlight_range_count": sum(len(s["highlights"]) for s in segments),
    }
    write_json(Path(args.output).expanduser().resolve(), plan)
    print(json.dumps(plan["statistics"], ensure_ascii=False))


def validate_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    segments = plan.get("segments")
    if plan.get("version") != 1:
        errors.append("version must be 1")
    if not isinstance(segments, list) or not segments:
        return errors + ["segments must be a non-empty array"]
    ids: set[str] = set()
    for idx, segment in enumerate(segments, start=1):
        label = str(segment.get("id", idx))
        if label in ids:
            errors.append(f"duplicate segment id {label}")
        ids.add(label)
        if int(segment.get("end_ms", 0)) <= int(segment.get("start_ms", 0)):
            errors.append(f"segment {label} has invalid timing")
        text = segment.get("text")
        if not isinstance(text, str) or not text:
            errors.append(f"segment {label} has no text")
            continue
        previous_end = -1
        for highlight in segment.get("highlights", []):
            start, end = int(highlight.get("start", -1)), int(highlight.get("end", -1))
            if not (0 <= start < end <= len(text)):
                errors.append(f"segment {label} highlight is out of bounds")
            elif text[start:end] != highlight.get("text"):
                errors.append(f"segment {label} highlight text no longer matches")
            if start < previous_end:
                errors.append(f"segment {label} highlights overlap")
            previous_end = end
    return errors


def command_validate(args: argparse.Namespace) -> None:
    plan = load_json(Path(args.plan).expanduser().resolve())
    errors = validate_plan(plan)
    if errors:
        raise FocusError("; ".join(errors))
    segments = plan["segments"]
    highlighted_chars = sum(
        h["end"] - h["start"] for segment in segments for h in segment.get("highlights", [])
    )
    visible_chars = sum(len(segment["text"].replace(" ", "")) for segment in segments)
    result = {
        "valid": True,
        "segments": len(segments),
        "highlight_ranges": sum(len(s.get("highlights", [])) for s in segments),
        "highlight_coverage": round(highlighted_chars / max(1, visible_chars), 4),
    }
    print(json.dumps(result, ensure_ascii=False))


def discover_pingfang() -> Path | None:
    direct = Path("/System/Library/Fonts/PingFang.ttc")
    if direct.is_file():
        return direct
    root = Path("/System/Library/AssetsV2")
    if root.is_dir():
        matches = sorted(root.glob("com_apple_MobileAsset_Font8/*/AssetData/PingFang.ttc"))
        for path in matches:
            if path.is_file():
                return path
    return None


def resolve_font(style: dict[str, Any]) -> Path:
    requested = str(style.get("font_path", "")).strip()
    pingfang = discover_pingfang()
    candidates = [requested] if requested else []
    if pingfang:
        candidates.append(str(pingfang))
    candidates.extend(FONT_CANDIDATES)
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        if path.is_file():
            return path
    raise FocusError("No usable CJK font found; set font_path in style JSON")


def load_style_font(style: dict[str, Any], font_size: int) -> ImageFont.FreeTypeFont:
    path = resolve_font(style)
    if "font_index" in style:
        index = int(style.get("font_index") or 0)
    elif path.name.lower().startswith("pingfang"):
        index = PINGFANG_SC_MEDIUM_INDEX
    else:
        index = 0
    try:
        return ImageFont.truetype(str(path), font_size, index=index)
    except OSError:
        if index:
            try:
                return ImageFont.truetype(str(path), font_size, index=0)
            except OSError as exc:
                raise FocusError(f"Cannot open font {path}: {exc}") from exc
        raise FocusError(f"Cannot open font {path} index {index}")


def rgba(value: Iterable[int]) -> tuple[int, int, int, int]:
    parts = tuple(int(v) for v in value)
    if len(parts) != 4 or any(v < 0 or v > 255 for v in parts):
        raise FocusError(f"Invalid RGBA color: {parts}")
    return parts


def highlight_runs(text: str, highlights: list[dict[str, Any]]) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    cursor = 0
    for item in highlights:
        start, end = int(item["start"]), int(item["end"])
        if start > cursor:
            runs.append((text[cursor:start], False))
        runs.append((text[start:end], True))
        cursor = end
    if cursor < len(text):
        runs.append((text[cursor:], False))
    return runs or [(text, False)]


def render_segment_canvas(
    segment: dict[str, Any], style: dict[str, Any], width: int, height: int
) -> Image.Image:
    font_size = int(round(height * float(style.get("font_size_ratio", 0.048))))
    font_size = max(int(style.get("font_size_min", 34)), font_size)
    font_size = min(int(style.get("font_size_max", 112)), font_size)
    highlight_scale = float(style.get("highlight_scale", 1.0))
    highlight_size = max(1, int(round(font_size * highlight_scale)))
    normal_font = load_style_font(style, font_size)
    highlight_font = load_style_font(style, highlight_size) if highlight_scale != 1.0 else normal_font
    stroke = max(1, int(round(highlight_size * float(style.get("highlight_stroke_width_ratio", 0.065)))))
    pad_ref = highlight_size if highlight_scale > 1.0 else font_size
    pad_x = int(round(pad_ref * float(style.get("padding_x_ratio", 0.45))))
    pad_y = int(round(pad_ref * float(style.get("padding_y_ratio", 0.28))))
    scratch = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(scratch)
    ref_box = draw.textbbox((0, 0), "国", font=normal_font, anchor="ls")
    pieces: list[dict[str, Any]] = []
    for run_text, highlighted in highlight_runs(segment["text"], segment.get("highlights", [])):
        font = highlight_font if highlighted else normal_font
        piece_stroke = stroke if highlighted else 0
        sample = run_text if run_text.strip() else "国"
        box = draw.textbbox((0, 0), sample, font=font, stroke_width=piece_stroke, anchor="ls")
        pieces.append(
            {
                "text": run_text,
                "highlighted": highlighted,
                "font": font,
                "stroke": piece_stroke,
                "width": float(draw.textlength(run_text, font=font)) if run_text else 0.0,
                "top": int(box[1]),
                "bottom": int(box[3]),
            }
        )
    if not pieces:
        pieces.append(
            {
                "text": "",
                "highlighted": False,
                "font": normal_font,
                "stroke": 0,
                "width": 0.0,
                "top": int(ref_box[1]),
                "bottom": int(ref_box[3]),
            }
        )
    max_stroke = max((item["stroke"] for item in pieces), default=0)
    content_top = min(item["top"] for item in pieces)
    content_bottom = max(item["bottom"] for item in pieces)
    text_height = content_bottom - content_top
    text_width = sum(item["width"] for item in pieces)
    card_width = int(math.ceil(text_width)) + pad_x * 2 + max_stroke * 2
    card_height = int(math.ceil(text_height)) + pad_y * 2 + max_stroke * 2
    if "bubble_corner_percent" in style:
        radius = int(round(card_height * float(style["bubble_corner_percent"]) / 200.0))
    else:
        radius = int(round(font_size * float(style.get("corner_radius_ratio", 0.34))))
    radius = max(0, min(radius, card_height // 2, card_width // 2))
    safe_width = int(width * float(style.get("safe_width_ratio", 0.9)))
    if card_width > safe_width:
        raise FocusError(
            f'Segment {segment["id"]} is too wide ({card_width}px > {safe_width}px); reduce max-chars or font size'
        )
    center_x = width * float(style.get("center_x_ratio", 0.5))
    center_y = height * float(style.get("center_y_ratio", 0.82))
    left = int(round(center_x - card_width / 2))
    top = int(round(center_y - card_height / 2))
    left = min(max(0, left), width - card_width)
    top = min(max(0, top), height - card_height)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas_draw = ImageDraw.Draw(canvas)
    canvas_draw.rounded_rectangle(
        (left, top, left + card_width, top + card_height),
        radius=radius,
        fill=rgba(style.get("background_color", [45, 45, 45, 145])),
    )
    baseline_y = top + pad_y + max_stroke - content_top
    x = float(left + pad_x + max_stroke)
    normal_fill = rgba(style.get("normal_color", [255, 255, 255, 255]))
    highlight_fill = rgba(style.get("highlight_color", [255, 214, 0, 255]))
    highlight_stroke_fill = rgba(style.get("highlight_stroke_color", [20, 20, 20, 255]))
    for item in pieces:
        if not item["text"]:
            continue
        if item["highlighted"]:
            canvas_draw.text(
                (x, baseline_y),
                item["text"],
                font=item["font"],
                fill=highlight_fill,
                stroke_width=item["stroke"],
                stroke_fill=highlight_stroke_fill,
                anchor="ls",
            )
        else:
            canvas_draw.text(
                (x, baseline_y),
                item["text"],
                font=item["font"],
                fill=normal_fill,
                anchor="ls",
            )
        x += item["width"]
    return canvas


def ms_clock(ms: int) -> str:
    seconds = max(0, int(ms)) / 1000
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:05.2f}"


def command_review(args: argparse.Namespace) -> None:
    plan = load_json(Path(args.plan).expanduser().resolve())
    errors = validate_plan(plan)
    if errors:
        raise FocusError("; ".join(errors))
    segments = plan["segments"]
    highlighted = [s for s in segments if s.get("highlights")]
    plain = [s for s in segments if not s.get("highlights")]
    lines = [
        f"高亮 {len(highlighted)}/{len(segments)} 句",
        "",
        "| # | 时间 | 原文 | 高亮 |",
        "|---|---|---|---|",
    ]
    for segment in highlighted:
        marks = " / ".join(item["text"] for item in segment["highlights"])
        lines.append(
            f"| {segment['cue_id']} | {ms_clock(segment['start_ms'])} | {segment['text']} | {marks} |"
        )
    if plain:
        lines.append("")
        lines.append("未高亮：")
        for segment in plain:
            lines.append(f"- {segment['cue_id']} {segment['text']}")
    text = "\n".join(lines) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        refuse_existing(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def command_preview(args: argparse.Namespace) -> None:
    plan = load_json(Path(args.plan).expanduser().resolve())
    style = load_json(Path(args.style).expanduser().resolve())
    errors = validate_plan(plan)
    if errors:
        raise FocusError("; ".join(errors))
    segments = plan["segments"]
    if args.cue is not None:
        matches = [s for s in segments if s["cue_id"] == args.cue]
        if not matches:
            raise FocusError(f"No segment for cue {args.cue}")
        segment = matches[0]
    else:
        segment = next((s for s in segments if s.get("highlights")), segments[0])
    output = Path(args.output).expanduser().resolve()
    refuse_existing(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    render_segment_canvas(segment, style, args.width, args.height).save(output)
    print(json.dumps({"output": str(output), "segment_id": segment["id"], "cue_id": segment["cue_id"]}, ensure_ascii=False))


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise FocusError(f"ffprobe failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise FocusError(f"No video stream in {path}")
    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "duration": float(data["format"]["duration"]),
        "streams": data.get("streams", []),
    }


def ffconcat_quote(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def build_timeline(
    plan: dict[str, Any], style: dict[str, Any], width: int, height: int,
    clip_start: float, clip_duration: float, workdir: Path
) -> Path:
    blank = workdir / "blank.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank)
    clip_end = clip_start + clip_duration
    intervals: list[tuple[float, float, Path]] = []
    for idx, segment in enumerate(plan["segments"], start=1):
        start = max(clip_start, segment["start_ms"] / 1000)
        end = min(clip_end, segment["end_ms"] / 1000)
        if end <= start:
            continue
        image_path = workdir / f"segment-{idx:05d}.png"
        render_segment_canvas(segment, style, width, height).save(image_path)
        intervals.append((start - clip_start, end - clip_start, image_path))
    entries: list[tuple[Path, float]] = []
    cursor = 0.0
    for start, end, image_path in sorted(intervals):
        start = max(start, cursor)
        if start > cursor + 0.0005:
            entries.append((blank, start - cursor))
        if end > start + 0.0005:
            entries.append((image_path, end - start))
            cursor = end
    if cursor < clip_duration:
        entries.append((blank, clip_duration - cursor))
    if not entries:
        entries.append((blank, clip_duration))
    concat_path = workdir / "overlay.ffconcat"
    lines = ["ffconcat version 1.0"]
    for image_path, duration in entries:
        lines.append(f"file '{ffconcat_quote(image_path)}'")
        lines.append(f"duration {duration:.6f}")
    lines.append(f"file '{ffconcat_quote(entries[-1][0])}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat_path


def command_render(args: argparse.Namespace) -> None:
    video = Path(args.video).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    refuse_existing(output)
    if not video.is_file():
        raise FocusError(f"Video does not exist: {video}")
    plan = load_json(Path(args.plan).expanduser().resolve())
    style = load_json(Path(args.style).expanduser().resolve())
    errors = validate_plan(plan)
    if errors:
        raise FocusError("; ".join(errors))
    probe = probe_video(video)
    clip_start = max(0.0, float(args.start or 0.0))
    if clip_start >= probe["duration"]:
        raise FocusError("--start is beyond video duration")
    clip_duration = float(args.duration) if args.duration else probe["duration"] - clip_start
    clip_duration = min(clip_duration, probe["duration"] - clip_start)
    if clip_duration <= 0:
        raise FocusError("Render duration must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    base_workdir = Path(args.keep_workdir).expanduser().resolve() if args.keep_workdir else None
    if base_workdir:
        refuse_existing(base_workdir)
        base_workdir.mkdir(parents=True)
        work_context = None
        workdir = base_workdir
    else:
        work_context = tempfile.TemporaryDirectory(prefix="subtitle-focus-")
        workdir = Path(work_context.name)
    try:
        concat_path = build_timeline(
            plan, style, probe["width"], probe["height"], clip_start, clip_duration, workdir
        )
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if clip_start:
            command += ["-ss", f"{clip_start:.6f}"]
        command += [
            "-i", str(video),
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-filter_complex", "[1:v]format=rgba[ov];[0:v][ov]overlay=0:0:eof_action=pass:shortest=0[v]",
            "-map", "[v]", "-map", "0:a?", "-t", f"{clip_duration:.6f}",
            "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            if output.exists():
                output.unlink()
            raise FocusError(f"ffmpeg render failed: {result.stderr.strip()}")
    finally:
        if work_context:
            work_context.cleanup()
    rendered = probe_video(output)
    print(json.dumps({"output": str(output), **rendered}, ensure_ascii=False))


def command_doctor(_: argparse.Namespace) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    filter_ok = False
    if ffmpeg:
        result = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True)
        filter_ok = bool(re.search(r"\boverlay\b", result.stdout))
    style = {"font_path": ""}
    font = None
    try:
        font = str(resolve_font(style))
    except FocusError:
        pass
    result = {
        "python": sys.version.split()[0],
        "pillow": Image.__version__ if hasattr(Image, "__version__") else "installed",
        "freetype": features.check("freetype2"),
        "font": font,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "overlay_filter": filter_ok,
        "ready": bool(ffmpeg and ffprobe and filter_ok and font and features.check("freetype2")),
    }
    print(json.dumps(result, ensure_ascii=False))
    if not result["ready"]:
        raise FocusError("Environment is not ready")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="check Pillow, fonts, ffmpeg and overlay support")
    doctor.set_defaults(func=command_doctor)
    plan = sub.add_parser("plan", help="parse and segment an SRT file")
    plan.add_argument("--srt", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--max-chars", type=float, default=16.0)
    plan.set_defaults(func=command_plan)
    apply_cmd = sub.add_parser("apply", help="apply highlight.json to a caption plan")
    apply_cmd.add_argument("--plan", required=True)
    apply_cmd.add_argument("--highlights", required=True)
    apply_cmd.add_argument("--output", required=True)
    apply_cmd.set_defaults(func=command_apply)
    validate = sub.add_parser("validate", help="validate plan timing and highlight offsets")
    validate.add_argument("--plan", required=True)
    validate.set_defaults(func=command_validate)
    review = sub.add_parser("review", help="print a markdown table of highlight decisions")
    review.add_argument("--plan", required=True)
    review.add_argument("--output")
    review.set_defaults(func=command_review)
    preview = sub.add_parser("preview", help="render one highlighted subtitle card as PNG")
    preview.add_argument("--plan", required=True)
    preview.add_argument("--style", required=True)
    preview.add_argument("--output", required=True)
    preview.add_argument("--cue", type=int)
    preview.add_argument("--width", type=int, default=1920)
    preview.add_argument("--height", type=int, default=1080)
    preview.set_defaults(func=command_preview)
    render = sub.add_parser("render", help="burn highlighted subtitles into a video")
    render.add_argument("--video", required=True)
    render.add_argument("--plan", required=True)
    render.add_argument("--style", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--start", type=float)
    render.add_argument("--duration", type=float)
    render.add_argument("--crf", type=int, default=18)
    render.add_argument("--preset", default="medium")
    render.add_argument("--keep-workdir")
    render.set_defaults(func=command_render)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.func(args)
        return 0
    except FocusError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
