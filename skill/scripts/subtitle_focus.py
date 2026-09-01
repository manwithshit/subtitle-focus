#!/usr/bin/env python3
"""Build and render semantically highlighted subtitles from SRT files."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

from PIL import Image, ImageDraw, ImageFont, ImageOps, features


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
SKILL_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_GLOSSARY_DIR = SKILL_ROOT / "assets" / "glossaries"
DEFAULT_PERSONAL_GLOSSARY = Path("~/.config/subtitle-focus/glossary.json").expanduser()
BUILTIN_GLOSSARIES = {"base", "ai"}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        raise FocusError(
            f"No timed subtitle cues found in {path}; a timestamped SRT is required. "
            "Plain MD/transcript input and local ASR/OCR are not supported."
        )
    return cues


def format_timecode(ms: int) -> str:
    hours, remainder = divmod(int(ms), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def serialize_srt(cues: list[dict[str, Any]]) -> str:
    blocks = []
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    str(cue["cue_id"]),
                    f'{format_timecode(cue["start_ms"])} --> {format_timecode(cue["end_ms"])}',
                    cue["text"],
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def source_snapshot(path: Path) -> dict[str, Any]:
    cues = parse_srt(path)
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "cue_count": len(cues),
        "first_start_ms": cues[0]["start_ms"],
        "last_end_ms": cues[-1]["end_ms"],
    }


def verify_lock(lock: dict[str, Any], srt: Path) -> dict[str, Any]:
    if lock.get("version") != 1 or lock.get("kind") != "subtitle-focus-srt-lock":
        raise FocusError("Invalid SRT lock manifest")
    if not lock.get("confirmed"):
        raise FocusError("SRT lock is not human-confirmed")
    actual = source_snapshot(srt)
    expected = lock.get("source", {})
    for key in ("sha256", "cue_count", "first_start_ms", "last_end_ms"):
        if expected.get(key) != actual.get(key):
            raise FocusError(f"SRT lock mismatch for {key}: expected {expected.get(key)!r}, got {actual.get(key)!r}")
    return actual


def verify_plan_source(plan: dict[str, Any], srt_override: Path | None = None) -> dict[str, Any]:
    source_value = str(srt_override or plan.get("source_srt", "")).strip()
    if not source_value:
        raise FocusError("Caption plan has no source_srt")
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise FocusError(f"Caption plan source SRT does not exist: {source}")
    actual = source_snapshot(source)
    expected_sha = str(plan.get("source_sha256", ""))
    if not expected_sha:
        raise FocusError("Caption plan has no source_sha256; regenerate it from a locked SRT")
    if actual["sha256"] != expected_sha:
        raise FocusError(
            "Source SRT changed after planning; discard the stale plan and regenerate from the confirmed lock"
        )
    lock_info = plan.get("source_lock")
    if not isinstance(lock_info, dict) or not lock_info.get("confirmed"):
        raise FocusError("Caption plan is not tied to a confirmed SRT lock")
    if lock_info.get("source_sha256") != actual["sha256"]:
        raise FocusError("Caption plan lock SHA does not match the current SRT")
    expected_cues = int(plan.get("statistics", {}).get("cue_count", 0))
    if expected_cues and actual["cue_count"] != expected_cues:
        raise FocusError("Caption plan cue count no longer matches the current SRT")
    return actual


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


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def load_glossary_layer(path: Path, fallback_name: str, priority: int) -> dict[str, Any]:
    glossary = load_json(path)
    if glossary.get("version") != 1:
        raise FocusError(f"Only glossary schema version 1 is supported: {path}")
    forbidden = glossary.get("forbidden_terms", [])
    if not isinstance(forbidden, list):
        raise FocusError(f"glossary forbidden_terms must be an array: {path}")
    name = str(glossary.get("name", fallback_name)).strip() or fallback_name
    items: list[dict[str, Any]] = []
    for index, item in enumerate(forbidden, start=1):
        if not isinstance(item, dict):
            raise FocusError(f"Glossary item {index} must be an object: {path}")
        term = str(item.get("text", ""))
        suggestion = str(item.get("suggest", "")).strip()
        if not term:
            raise FocusError(f"Glossary item {index} has an empty text: {path}")
        if suggestion == term:
            raise FocusError(f"Glossary item {index} suggests the same text: {path}")
        items.append(
            {
                "text": term,
                "suggest": suggestion,
                "reason": str(item.get("reason", "")).strip(),
                "category": str(item.get("category", "")).strip(),
                "source": name,
                "source_path": str(path),
                "priority": priority,
            }
        )
    return {"name": name, "path": str(path), "priority": priority, "items": items}


def proofread_glossary_layers(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layers: list[dict[str, Any]] = []
    layers.append(
        load_glossary_layer(BUILTIN_GLOSSARY_DIR / "base.json", "基础词库", priority=10)
    )
    domains = list(dict.fromkeys(getattr(args, "domains", None) or []))
    for domain in domains:
        if domain not in BUILTIN_GLOSSARIES or domain == "base":
            raise FocusError(f"Unknown glossary domain: {domain}")
        layers.append(
            load_glossary_layer(
                BUILTIN_GLOSSARY_DIR / f"{domain}.json",
                f"{domain} 词库",
                priority=20,
            )
        )

    personal_value = getattr(args, "personal_glossary", None)
    use_default_personal = bool(getattr(args, "use_default_personal", True))
    if personal_value:
        personal_path = Path(personal_value).expanduser().resolve()
        layers.append(load_glossary_layer(personal_path, "个人词库", priority=30))
    elif use_default_personal and DEFAULT_PERSONAL_GLOSSARY.is_file():
        layers.append(
            load_glossary_layer(DEFAULT_PERSONAL_GLOSSARY.resolve(), "个人词库", priority=30)
        )

    legacy_value = getattr(args, "glossary", None)
    if legacy_value:
        legacy_path = Path(legacy_value).expanduser().resolve()
        layers.append(load_glossary_layer(legacy_path, "自定义词库", priority=35))

    project_value = getattr(args, "project_glossary", None)
    if project_value:
        project_path = Path(project_value).expanduser().resolve()
        layers.append(load_glossary_layer(project_path, "项目词库", priority=40))

    merged: dict[str, dict[str, Any]] = {}
    for layer in sorted(layers, key=lambda item: int(item["priority"])):
        for item in layer["items"]:
            merged[item["text"]] = item
    return layers, list(merged.values())


def glossary_term_occurs(text: str, term: str) -> bool:
    if term.isascii() and any(ch.isalnum() for ch in term):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        return re.search(pattern, text) is not None
    return term in text


def command_proofread(args: argparse.Namespace) -> None:
    srt = Path(args.srt).expanduser().resolve()
    cues = parse_srt(srt)
    layers, forbidden = proofread_glossary_layers(args)
    lines = [
        "# SRT 文字校对",
        "",
        f"- 文件：`{srt}`",
        f"- SHA-256：`{sha256_file(srt)}`",
        f"- 字幕：{len(cues)} 条",
        "- 输入边界：只校对带时间码的 SRT；未调用本地 ASR、OCR、Video Use 或剪口播。",
        "- 词库优先级：项目 > 自定义 > 个人 > 场景 > 基础。词库只给建议，不自动改字。",
        "- 已加载词库：" + "；".join(
            f'{layer["name"]}（`{layer["path"]}`）' for layer in layers
        ),
        "",
        "| ID | 时间 | 原文 | 建议 | 来源 |",
        "|---:|---|---|---|---|",
    ]
    flagged = 0
    for cue in cues:
        notes = []
        sources = []
        for item in forbidden:
            term = str(item.get("text", ""))
            if term and glossary_term_occurs(cue["text"], term):
                suggestion = str(item.get("suggest", "")).strip()
                reason = str(item.get("reason", "")).strip()
                note = f"`{term}`"
                if suggestion:
                    note += f" → `{suggestion}`"
                if reason:
                    note += f"（{reason}）"
                notes.append(note)
                sources.append(str(item.get("source", "")))
        if notes:
            flagged += 1
        lines.append(
            f'| {cue["cue_id"]} | {ms_clock(cue["start_ms"])}–{ms_clock(cue["end_ms"])} '
            f'| {markdown_cell(cue["text"])} | {markdown_cell("；".join(notes))} '
            f'| {markdown_cell("；".join(dict.fromkeys(sources)))} |'
        )
    lines.extend(
        [
            "",
            f"标记 {flagged}/{len(cues)} 条。Agent 只能结合 SRT 前后文、已加载词库、项目资料和用户反馈提出建议；脚本不会擅自改字，也不会把视频音频当作已核验文字来源。",
        ]
    )
    output = Path(args.output).expanduser().resolve()
    refuse_existing(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cues": len(cues), "flagged": flagged}, ensure_ascii=False))


def command_glossary_init(args: argparse.Namespace) -> None:
    scope = str(args.scope)
    output_value = getattr(args, "output", None)
    if output_value:
        output = Path(output_value).expanduser().resolve()
    elif scope == "personal":
        output = DEFAULT_PERSONAL_GLOSSARY.resolve()
    else:
        raise FocusError("--output is required for a project glossary")
    name = "个人词库" if scope == "personal" else "项目词库"
    write_json(output, {"version": 1, "name": name, "forbidden_terms": []})
    print(json.dumps({"output": str(output), "scope": scope}, ensure_ascii=False))


def replace_occurrence(text: str, find: str, replacement: str, occurrence: Any) -> tuple[str, int]:
    matches = [match.start() for match in re.finditer(re.escape(find), text)]
    if not matches:
        return text, 0
    if occurrence == "all":
        return text.replace(find, replacement), len(matches)
    try:
        selected = int(occurrence)
    except (TypeError, ValueError) as exc:
        raise FocusError(f"Invalid correction occurrence: {occurrence!r}") from exc
    if selected < 1 or selected > len(matches):
        return text, 0
    start = matches[selected - 1]
    end = start + len(find)
    return text[:start] + replacement + text[end:], 1


def command_correct(args: argparse.Namespace) -> None:
    srt = Path(args.srt).expanduser().resolve()
    cues = parse_srt(srt)
    corrections_path = Path(args.corrections).expanduser().resolve()
    corrections = load_json(corrections_path)
    if corrections.get("version") != 1 or not isinstance(corrections.get("items"), list):
        raise FocusError("Corrections must use schema version 1 with an items array")
    by_id = {int(cue["cue_id"]): cue for cue in cues}
    changes: list[dict[str, Any]] = []
    for index, item in enumerate(corrections["items"], start=1):
        cue_id = int(item.get("cue_id", -1))
        if cue_id not in by_id:
            raise FocusError(f"Correction {index} targets missing cue {cue_id}")
        find = str(item.get("find", ""))
        replacement = str(item.get("replace", ""))
        if not find:
            raise FocusError(f"Correction {index} has an empty find string")
        if find == replacement:
            raise FocusError(f"Correction {index} does not change the text")
        cue = by_id[cue_id]
        before = cue["text"]
        after, count = replace_occurrence(before, find, replacement, item.get("occurrence", 1))
        if count == 0:
            raise FocusError(f'Correction {index} cannot find "{find}" in cue {cue_id}')
        cue["text"] = after
        changes.append(
            {
                "cue_id": cue_id,
                "start_ms": cue["start_ms"],
                "end_ms": cue["end_ms"],
                "before": before,
                "after": after,
                "find": find,
                "replace": replacement,
                "occurrences": count,
                "reason": str(item.get("reason", "")),
            }
        )
    output = Path(args.output).expanduser().resolve()
    review = Path(args.review).expanduser().resolve()
    refuse_existing(output)
    refuse_existing(review)
    output.parent.mkdir(parents=True, exist_ok=True)
    review.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialize_srt(cues), encoding="utf-8")
    lines = [
        "# SRT 修改确认",
        "",
        f"- 原文件：`{srt}`",
        f"- 新文件：`{output}`",
        f"- 时间轴：未修改",
        "",
        "| ID | 时间 | 修改前 | 修改后 | 原因 |",
        "|---:|---|---|---|---|",
    ]
    for change in changes:
        lines.append(
            f'| {change["cue_id"]} | {ms_clock(change["start_ms"])} '
            f'| {markdown_cell(change["before"])} | {markdown_cell(change["after"])} '
            f'| {markdown_cell(change["reason"])} |'
        )
    review.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "review": str(review),
                "changed_cue_ids": sorted({item["cue_id"] for item in changes}),
                "source_sha256": sha256_file(srt),
                "output_sha256": sha256_file(output),
            },
            ensure_ascii=False,
        )
    )


def command_lock(args: argparse.Namespace) -> None:
    if not args.confirmed:
        raise FocusError("Refusing to lock SRT without --confirmed after human text review")
    srt = Path(args.srt).expanduser().resolve()
    snapshot = source_snapshot(srt)
    output = Path(args.output).expanduser().resolve()
    manifest = {
        "version": 1,
        "kind": "subtitle-focus-srt-lock",
        "confirmed": True,
        "locked_at": utc_now(),
        "source": snapshot,
    }
    write_json(output, manifest)
    print(json.dumps({"output": str(output), **snapshot}, ensure_ascii=False))


def command_plan(args: argparse.Namespace) -> None:
    srt = Path(args.srt).expanduser().resolve()
    lock_path = Path(args.lock).expanduser().resolve()
    lock = load_json(lock_path)
    snapshot = verify_lock(lock, srt)
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
    plan = {
        "version": 1,
        "source_srt": str(srt),
        "source_sha256": snapshot["sha256"],
        "source_lock": {
            "path": str(lock_path),
            "sha256": sha256_file(lock_path),
            "confirmed": True,
            "source_sha256": snapshot["sha256"],
        },
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
    verify_plan_source(plan)
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
    previous_start = -1
    for idx, segment in enumerate(segments, start=1):
        label = str(segment.get("id", idx))
        if label in ids:
            errors.append(f"duplicate segment id {label}")
        ids.add(label)
        start_ms = int(segment.get("start_ms", 0))
        end_ms = int(segment.get("end_ms", 0))
        if end_ms <= start_ms:
            errors.append(f"segment {label} has invalid timing")
        if start_ms < previous_start:
            errors.append(f"segment {label} is out of chronological order")
        previous_start = start_ms
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
    source = verify_plan_source(
        plan, Path(args.srt).expanduser().resolve() if args.srt else None
    )
    segments = plan["segments"]
    video_result = None
    if args.video:
        video = Path(args.video).expanduser().resolve()
        video_result = probe_video(video)
        if source["last_end_ms"] > round(video_result["duration"] * 1000) + int(args.tolerance_ms):
            raise FocusError(
                f'SRT ends at {source["last_end_ms"]}ms but video ends at '
                f'{round(video_result["duration"] * 1000)}ms'
            )
    highlighted_chars = sum(
        h["end"] - h["start"] for segment in segments for h in segment.get("highlights", [])
    )
    visible_chars = sum(len(segment["text"].replace(" ", "")) for segment in segments)
    result = {
        "valid": True,
        "segments": len(segments),
        "highlight_ranges": sum(len(s.get("highlights", [])) for s in segments),
        "highlight_coverage": round(highlighted_chars / max(1, visible_chars), 4),
        "source_srt_sha256": source["sha256"],
        "cue_count": source["cue_count"],
    }
    if video_result:
        result["video"] = {
            "width": video_result["width"],
            "height": video_result["height"],
            "duration": video_result["duration"],
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


def validate_style(style: dict[str, Any]) -> None:
    for key in ("center_x_ratio", "center_y_ratio", "safe_width_ratio"):
        value = float(style.get(key, 0.5 if key != "safe_width_ratio" else 0.9))
        if not 0 < value <= 1:
            raise FocusError(f"Style {key} must be within (0, 1]")
    if float(style.get("font_size_ratio", 0.048)) <= 0:
        raise FocusError("Style font_size_ratio must be positive")
    if int(style.get("font_size_min", 34)) <= 0 or int(style.get("font_size_max", 112)) <= 0:
        raise FocusError("Style font sizes must be positive")
    if int(style.get("font_size_min", 34)) > int(style.get("font_size_max", 112)):
        raise FocusError("Style font_size_min cannot exceed font_size_max")


def command_style(args: argparse.Namespace) -> None:
    base_path = Path(args.base).expanduser().resolve()
    style = load_json(base_path)
    overrides = {
        "center_x_ratio": args.center_x_ratio,
        "center_y_ratio": args.center_y_ratio,
        "safe_width_ratio": args.safe_width_ratio,
        "font_size_ratio": args.font_size_ratio,
        "font_size_min": args.font_size_min,
        "font_size_max": args.font_size_max,
    }
    applied = {key: value for key, value in overrides.items() if value is not None}
    style.update(applied)
    reference = None
    if args.reference_image:
        image_path = Path(args.reference_image).expanduser().resolve()
        if not image_path.is_file():
            raise FocusError(f"Reference image does not exist: {image_path}")
        with Image.open(image_path) as image:
            reference = {
                "path": str(image_path),
                "sha256": sha256_file(image_path),
                "width": image.width,
                "height": image.height,
            }
    validate_style(style)
    style["_meta"] = {
        "base_style": str(base_path),
        "base_sha256": sha256_file(base_path),
        "reference_demo": reference,
        "overrides": applied,
        "created_at": utc_now(),
    }
    output = Path(args.output).expanduser().resolve()
    write_json(output, style)
    print(
        json.dumps(
            {
                "output": str(output),
                "center_y_ratio": style.get("center_y_ratio", 0.82),
                "reference_demo": reference,
                "overrides": applied,
            },
            ensure_ascii=False,
        )
    )


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
    verify_plan_source(plan)
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
    verify_plan_source(plan)
    validate_style(style)
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
    if args.video:
        if args.width or args.height:
            raise FocusError("Use either --video or --width/--height, not both")
        probe = probe_video(Path(args.video).expanduser().resolve())
        width, height = probe["width"], probe["height"]
    else:
        width, height = int(args.width or 1920), int(args.height or 1080)
    render_segment_canvas(segment, style, width, height).save(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "segment_id": segment["id"],
                "cue_id": segment["cue_id"],
                "width": width,
                "height": height,
            },
            ensure_ascii=False,
        )
    )


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
    source = verify_plan_source(plan)
    validate_style(style)
    probe = probe_video(video)
    if source["last_end_ms"] > round(probe["duration"] * 1000) + int(args.tolerance_ms):
        raise FocusError(
            f'SRT ends at {source["last_end_ms"]}ms but video ends at '
            f'{round(probe["duration"] * 1000)}ms'
        )
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


def correction_cue_ids(path: Path | None) -> set[int]:
    if path is None:
        return set()
    data = load_json(path)
    if data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise FocusError("Corrections must use schema version 1 with an items array")
    return {int(item["cue_id"]) for item in data["items"]}


def validate_corrections_applied(path: Path | None, cues: list[dict[str, Any]]) -> None:
    if path is None:
        return
    data = load_json(path)
    by_id = {int(cue["cue_id"]): cue["text"] for cue in cues}
    for index, item in enumerate(data.get("items", []), start=1):
        cue_id = int(item.get("cue_id", -1))
        replacement = str(item.get("replace", ""))
        if cue_id not in by_id:
            raise FocusError(f"Correction {index} targets missing final cue {cue_id}")
        if replacement and replacement not in by_id[cue_id]:
            raise FocusError(
                f'Correction {index} replacement "{replacement}" is absent from final cue {cue_id}'
            )


def select_review_segments(
    plan: dict[str, Any], corrected_cues: set[int]
) -> list[tuple[dict[str, Any], list[str]]]:
    segments = plan["segments"]
    reasons: dict[str, set[str]] = {}
    by_id = {segment["id"]: segment for segment in segments}

    def add(segment: dict[str, Any], reason: str) -> None:
        reasons.setdefault(segment["id"], set()).add(reason)

    for segment in segments:
        if segment.get("highlights"):
            add(segment, "highlighted")
        if int(segment["cue_id"]) in corrected_cues:
            add(segment, "corrected")
    add(segments[0], "entry")
    add(segments[-1], "exit")
    total_mid = (int(segments[0]["start_ms"]) + int(segments[-1]["end_ms"])) / 2
    middle = min(
        segments,
        key=lambda segment: abs(
            (int(segment["start_ms"]) + int(segment["end_ms"])) / 2 - total_mid
        ),
    )
    add(middle, "middle")
    selected = [(by_id[key], sorted(value)) for key, value in reasons.items()]
    return sorted(selected, key=lambda item: (int(item[0]["start_ms"]), item[0]["id"]))


def extract_video_frame(video: Path, timestamp_s: float, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FocusError("ffmpeg is required to extract review frames")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp_s:.6f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-y",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise FocusError(f"ffmpeg frame extraction failed: {result.stderr.strip()}")


def build_contact_sheet(
    entries: list[dict[str, Any]], style: dict[str, Any], output: Path
) -> None:
    columns = 4
    cell_width = 340
    thumb_height = 560
    label_height = 86
    gap = 18
    rows = math.ceil(len(entries) / columns)
    canvas_width = columns * cell_width + (columns + 1) * gap
    canvas_height = rows * (thumb_height + label_height) + (rows + 1) * gap
    canvas = Image.new("RGB", (canvas_width, canvas_height), (20, 20, 22))
    draw = ImageDraw.Draw(canvas)
    font = load_style_font(style, 22)
    small = load_style_font(style, 18)
    for index, entry in enumerate(entries):
        row, column = divmod(index, columns)
        x = gap + column * (cell_width + gap)
        y = gap + row * (thumb_height + label_height + gap)
        with Image.open(entry["path"]) as image:
            thumb = ImageOps.contain(image.convert("RGB"), (cell_width, thumb_height))
            image_x = x + (cell_width - thumb.width) // 2
            image_y = y + (thumb_height - thumb.height) // 2
            canvas.paste(thumb, (image_x, image_y))
        label_y = y + thumb_height + 8
        draw.text(
            (x, label_y),
            f'ID {entry["cue_id"]} · {ms_clock(entry["timestamp_ms"])}',
            font=font,
            fill=(255, 214, 0),
        )
        caption = str(entry["text"])
        if len(caption) > 22:
            caption = caption[:21] + "…"
        draw.text((x, label_y + 32), caption, font=small, fill=(238, 238, 238))
    canvas.save(output, quality=92)


def command_frames(args: argparse.Namespace) -> None:
    video = Path(args.video).expanduser().resolve()
    plan = load_json(Path(args.plan).expanduser().resolve())
    style = load_json(Path(args.style).expanduser().resolve())
    errors = validate_plan(plan)
    if errors:
        raise FocusError("; ".join(errors))
    source = verify_plan_source(plan)
    validate_style(style)
    probe = probe_video(video)
    if source["last_end_ms"] > round(probe["duration"] * 1000) + int(args.tolerance_ms):
        raise FocusError("SRT extends beyond the review video")
    corrections = Path(args.corrections).expanduser().resolve() if args.corrections else None
    corrected_cues = correction_cue_ids(corrections)
    selected = select_review_segments(plan, corrected_cues)
    output_dir = Path(args.output_dir).expanduser().resolve()
    refuse_existing(output_dir)
    output_dir.mkdir(parents=True)
    entries: list[dict[str, Any]] = []
    for index, (segment, reasons) in enumerate(selected, start=1):
        timestamp_ms = round((int(segment["start_ms"]) + int(segment["end_ms"])) / 2)
        raw_path = output_dir / f".raw-{index:03d}.png"
        image_path = output_dir / f'frame-{index:03d}-cue-{int(segment["cue_id"]):03d}.png'
        extract_video_frame(video, timestamp_ms / 1000, raw_path)
        with Image.open(raw_path) as base:
            rgba_base = base.convert("RGBA")
            if args.already_burned:
                rgba_base.convert("RGB").save(image_path, quality=95)
            else:
                overlay = render_segment_canvas(segment, style, rgba_base.width, rgba_base.height)
                Image.alpha_composite(rgba_base, overlay).convert("RGB").save(image_path, quality=95)
        raw_path.unlink(missing_ok=True)
        entries.append(
            {
                "path": str(image_path),
                "filename": image_path.name,
                "segment_id": segment["id"],
                "cue_id": int(segment["cue_id"]),
                "timestamp_ms": timestamp_ms,
                "text": segment["text"],
                "reasons": reasons,
            }
        )
    contact_sheet = output_dir / "contact-sheet.jpg"
    build_contact_sheet(entries, style, contact_sheet)
    index_data = {
        "version": 1,
        "kind": "subtitle-focus-review-frames",
        "created_at": utc_now(),
        "video": {"path": str(video), "sha256": sha256_file(video)},
        "already_burned": bool(args.already_burned),
        "plan": {"source_srt_sha256": source["sha256"]},
        "corrections": str(corrections) if corrections else None,
        "corrected_cue_ids": sorted(corrected_cues),
        "frames": entries,
        "contact_sheet": str(contact_sheet),
    }
    (output_dir / "index.json").write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# 字幕抽帧检查", "", f"![字幕联系表](./{contact_sheet.name})", ""]
    for entry in entries:
        lines.append(
            f'- ID {entry["cue_id"]} · {ms_clock(entry["timestamp_ms"])} · '
            f'{", ".join(entry["reasons"])} · [{entry["text"]}](./{entry["filename"]})'
        )
    (output_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "frames": len(entries),
                "corrected_cue_ids": sorted(corrected_cues),
                "contact_sheet": str(contact_sheet),
            },
            ensure_ascii=False,
        )
    )


def copy_refuse(source: Path, destination: Path) -> None:
    refuse_existing(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def command_deliver(args: argparse.Namespace) -> None:
    video = Path(args.video).expanduser().resolve()
    srt = Path(args.srt).expanduser().resolve()
    plan_path = Path(args.plan).expanduser().resolve()
    style_path = Path(args.style).expanduser().resolve()
    plan = load_json(plan_path)
    style = load_json(style_path)
    errors = validate_plan(plan)
    if errors:
        raise FocusError("; ".join(errors))
    source = verify_plan_source(plan, srt)
    validate_style(style)
    cues = parse_srt(srt)
    probe = probe_video(video)
    if source["last_end_ms"] > round(probe["duration"] * 1000) + int(args.tolerance_ms):
        raise FocusError("SRT extends beyond the delivery video")
    corrections_path = Path(args.corrections).expanduser().resolve() if args.corrections else None
    corrected_cues = correction_cue_ids(corrections_path)
    validate_corrections_applied(corrections_path, cues)
    review_dir = Path(args.review_dir).expanduser().resolve() if args.review_dir else None
    reviewed_cues: set[int] = set()
    review_index = None
    if review_dir:
        review_index_path = review_dir / "index.json"
        review_index = load_json(review_index_path)
        reviewed_cues = {int(item["cue_id"]) for item in review_index.get("frames", [])}
        reviewed_segments = {str(item["segment_id"]) for item in review_index.get("frames", [])}
        if not review_index.get("already_burned"):
            raise FocusError("Delivery review frames must come from the already-burned final video")
        if review_index.get("video", {}).get("sha256") != sha256_file(video):
            raise FocusError("Review frames were not extracted from this final delivery video")
        if review_index.get("plan", {}).get("source_srt_sha256") != source["sha256"]:
            raise FocusError("Review frames were generated from a different locked SRT")
        required_segments = {
            segment["id"] for segment, _ in select_review_segments(plan, corrected_cues)
        }
        missing_segments = required_segments - reviewed_segments
        if missing_segments:
            raise FocusError(f"Required review segments are missing: {sorted(missing_segments)}")
    elif corrected_cues:
        raise FocusError("A review frame directory is required when corrections are present")

    output = Path(args.output).expanduser().resolve()
    refuse_existing(output)
    handoff: dict[str, Any] | None = None
    destinations: list[tuple[Path, Path]] = []
    transcript_destination = None
    handoff_manifest = None
    if args.handoff_dir:
        handoff_dir = Path(args.handoff_dir).expanduser().resolve()
        name = args.name or video.stem
        handoff_dir.mkdir(parents=True, exist_ok=True)
        srt_destination = handoff_dir / f"{name}.srt"
        transcript_destination = handoff_dir / f"{name}-transcript.md"
        handoff_manifest = handoff_dir / f"{name}-delivery.json"
        for candidate in (srt_destination, transcript_destination, handoff_manifest):
            refuse_existing(candidate)
        destinations.append((srt, srt_destination))
        video_destination = None
        if args.copy_video:
            video_destination = handoff_dir / f"{name}{video.suffix.lower()}"
            refuse_existing(video_destination)
            destinations.append((video, video_destination))
        publish_destination = None
        if args.publish_copy:
            publish_source = Path(args.publish_copy).expanduser().resolve()
            publish_destination = handoff_dir / f"{name}-publish-copy{publish_source.suffix or '.md'}"
            refuse_existing(publish_destination)
            destinations.append((publish_source, publish_destination))
        handoff = {
            "directory": str(handoff_dir),
            "video": str(video_destination) if video_destination else None,
            "srt": str(srt_destination),
            "transcript": str(transcript_destination),
            "publish_copy": str(publish_destination) if publish_destination else None,
            "manifest": str(handoff_manifest),
        }

    for source_path, destination in destinations:
        copy_refuse(source_path, destination)
    if transcript_destination:
        transcript = "# 口播稿\n\n" + "\n\n".join(cue["text"] for cue in cues) + "\n"
        transcript_destination.write_text(transcript, encoding="utf-8")

    manifest = {
        "version": 1,
        "kind": "subtitle-focus-delivery",
        "created_at": utc_now(),
        "includes": ["burned_subtitles", "locked_srt", "highlight_plan", "style", "review_frames"],
        "video": {
            "path": str(video),
            "sha256": sha256_file(video),
            "width": probe["width"],
            "height": probe["height"],
            "duration": probe["duration"],
        },
        "srt": source,
        "plan": {
            "path": str(plan_path),
            "sha256": sha256_file(plan_path),
            "highlight_ranges": sum(len(item.get("highlights", [])) for item in plan["segments"]),
        },
        "style": {
            "path": str(style_path),
            "sha256": sha256_file(style_path),
            "center_y_ratio": float(style.get("center_y_ratio", 0.82)),
            "reference_demo": style.get("_meta", {}).get("reference_demo"),
        },
        "corrections": {
            "path": str(corrections_path) if corrections_path else None,
            "sha256": sha256_file(corrections_path) if corrections_path else None,
            "changed_cue_ids": sorted(corrected_cues),
        },
        "review": {
            "directory": str(review_dir) if review_dir else None,
            "reviewed_cue_ids": sorted(reviewed_cues),
            "contact_sheet": review_index.get("contact_sheet") if review_index else None,
        },
        "handoff": handoff,
        "errors": [],
    }
    write_json(output, manifest)
    if handoff_manifest:
        copy_refuse(output, handoff_manifest)
    print(
        json.dumps(
            {
                "output": str(output),
                "video_sha256": manifest["video"]["sha256"],
                "srt_sha256": source["sha256"],
                "changed_cue_ids": sorted(corrected_cues),
                "handoff": handoff,
            },
            ensure_ascii=False,
        )
    )


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
    proofread = sub.add_parser("proofread", help="build a cue-by-cue text review table")
    proofread.add_argument("--srt", required=True)
    proofread.add_argument("--domain", dest="domains", action="append", choices=["ai"])
    proofread.add_argument("--personal-glossary")
    proofread.add_argument("--project-glossary")
    proofread.add_argument("--glossary", help="legacy custom glossary; prefer the personal/project flags")
    proofread.add_argument(
        "--no-default-personal",
        dest="use_default_personal",
        action="store_false",
        default=True,
        help=f"do not auto-load {DEFAULT_PERSONAL_GLOSSARY}",
    )
    proofread.add_argument("--output", required=True)
    proofread.set_defaults(func=command_proofread)
    glossary_init = sub.add_parser("glossary-init", help="create an empty personal or project glossary")
    glossary_init.add_argument("--scope", choices=["personal", "project"], required=True)
    glossary_init.add_argument("--output")
    glossary_init.set_defaults(func=command_glossary_init)
    correct = sub.add_parser("correct", help="apply confirmed exact-text SRT corrections")
    correct.add_argument("--srt", required=True)
    correct.add_argument("--corrections", required=True)
    correct.add_argument("--output", required=True)
    correct.add_argument("--review", required=True)
    correct.set_defaults(func=command_correct)
    lock = sub.add_parser("lock", help="lock a human-confirmed SRT by content hash")
    lock.add_argument("--srt", required=True)
    lock.add_argument("--output", required=True)
    lock.add_argument("--confirmed", action="store_true")
    lock.set_defaults(func=command_lock)
    plan = sub.add_parser("plan", help="parse and segment a locked SRT file")
    plan.add_argument("--srt", required=True)
    plan.add_argument("--lock", required=True)
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
    validate.add_argument("--srt")
    validate.add_argument("--video")
    validate.add_argument("--tolerance-ms", type=int, default=100)
    validate.set_defaults(func=command_validate)
    review = sub.add_parser("review", help="print a markdown table of highlight decisions")
    review.add_argument("--plan", required=True)
    review.add_argument("--output")
    review.set_defaults(func=command_review)
    style = sub.add_parser("style", help="derive a configurable style, optionally from a reference demo")
    style.add_argument("--base", required=True)
    style.add_argument("--output", required=True)
    style.add_argument("--reference-image")
    style.add_argument("--center-x-ratio", type=float)
    style.add_argument("--center-y-ratio", type=float)
    style.add_argument("--safe-width-ratio", type=float)
    style.add_argument("--font-size-ratio", type=float)
    style.add_argument("--font-size-min", type=int)
    style.add_argument("--font-size-max", type=int)
    style.set_defaults(func=command_style)
    preview = sub.add_parser("preview", help="render one highlighted subtitle card as PNG")
    preview.add_argument("--plan", required=True)
    preview.add_argument("--style", required=True)
    preview.add_argument("--output", required=True)
    preview.add_argument("--cue", type=int)
    preview.add_argument("--video")
    preview.add_argument("--width", type=int)
    preview.add_argument("--height", type=int)
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
    render.add_argument("--tolerance-ms", type=int, default=100)
    render.set_defaults(func=command_render)
    frames = sub.add_parser("frames", help="extract corrected, highlighted, entry, middle and exit review frames")
    frames.add_argument("--video", required=True)
    frames.add_argument("--plan", required=True)
    frames.add_argument("--style", required=True)
    frames.add_argument("--corrections")
    frames.add_argument("--output-dir", required=True)
    frames.add_argument("--already-burned", action="store_true")
    frames.add_argument("--tolerance-ms", type=int, default=100)
    frames.set_defaults(func=command_frames)
    deliver = sub.add_parser("deliver", help="validate and register one canonical subtitle delivery")
    deliver.add_argument("--video", required=True)
    deliver.add_argument("--srt", required=True)
    deliver.add_argument("--plan", required=True)
    deliver.add_argument("--style", required=True)
    deliver.add_argument("--corrections")
    deliver.add_argument("--review-dir", required=True)
    deliver.add_argument("--output", required=True)
    deliver.add_argument("--handoff-dir")
    deliver.add_argument("--name")
    deliver.add_argument("--copy-video", action="store_true")
    deliver.add_argument("--publish-copy")
    deliver.add_argument("--tolerance-ms", type=int, default=100)
    deliver.set_defaults(func=command_deliver)
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
