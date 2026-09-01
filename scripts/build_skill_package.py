#!/usr/bin/env python3
"""Build the public .skill archive from tracked skill files only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "subtitle-focus.skill"
REQUIRED_PUBLIC_GLOSSARIES = {
    "skill/assets/glossaries/base.json",
    "skill/assets/glossaries/ai.json",
}


def is_private_glossary(path: str) -> bool:
    name = Path(path).name
    return name in {"personal-glossary.json", "project-glossary.json"} or name.endswith(
        ".private-glossary.json"
    )


def tracked_skill_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "skill"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    files = sorted(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)
    missing = REQUIRED_PUBLIC_GLOSSARIES - set(files)
    if missing:
        raise RuntimeError(f"Missing required public glossaries: {sorted(missing)}")
    private = [path for path in files if is_private_glossary(path)]
    if private:
        raise RuntimeError(f"Refusing to package private glossary files: {private}")
    return files


def main() -> None:
    files = tracked_skill_files()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".skill.tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            source = ROOT / relative
            if not source.is_file():
                raise RuntimeError(f"Tracked skill file is missing: {relative}")
            archive.write(source, relative)
    os.replace(temporary, OUTPUT)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    print(
        json.dumps(
            {"output": str(OUTPUT), "files": len(files), "sha256": digest},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
