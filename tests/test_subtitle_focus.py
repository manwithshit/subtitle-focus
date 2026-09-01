from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skill" / "scripts" / "subtitle_focus.py"
SPEC = importlib.util.spec_from_file_location("subtitle_focus", SCRIPT)
assert SPEC and SPEC.loader
focus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(focus)


def namespace(**kwargs):
    return argparse.Namespace(**kwargs)


class SubtitleFocusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="subtitle-focus-test-")
        self.work = Path(self.temp.name)
        self.source_srt = self.work / "source.srt"
        self.source_srt.write_text(
            """1
00:00:00,100 --> 00:00:00,700
然后点击生成花纹

2
00:00:00,800 --> 00:00:01,500
我用Kimi K3做了一个小工具

3
00:00:01,600 --> 00:00:02,300
然后你还可以3D 地旋转它
""",
            encoding="utf-8",
        )
        self.corrections = self.work / "corrections.json"
        self.corrections.write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": [
                        {
                            "cue_id": 1,
                            "find": "生成花纹",
                            "replace": "生成华纹",
                            "reason": "项目术语",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def build_locked_plan(self):
        corrected = self.work / "corrected.srt"
        review = self.work / "correction-review.md"
        focus.command_correct(
            namespace(
                srt=str(self.source_srt),
                corrections=str(self.corrections),
                output=str(corrected),
                review=str(review),
            )
        )
        lock = self.work / "srt-lock.json"
        focus.command_lock(
            namespace(srt=str(corrected), output=str(lock), confirmed=True)
        )
        plan = self.work / "caption-plan.json"
        focus.command_plan(
            namespace(srt=str(corrected), lock=str(lock), output=str(plan), max_chars=16.0)
        )
        return corrected, review, lock, plan

    def test_correction_preserves_timing_and_lock_detects_stale_source(self):
        corrected, review, _, plan_path = self.build_locked_plan()
        cues = focus.parse_srt(corrected)
        self.assertEqual(cues[0]["text"], "然后点击生成华纹")
        self.assertEqual((cues[0]["start_ms"], cues[0]["end_ms"]), (100, 700))
        self.assertIn("生成花纹", review.read_text(encoding="utf-8"))
        self.assertIn("生成华纹", review.read_text(encoding="utf-8"))
        plan = focus.load_json(plan_path)
        snapshot = focus.verify_plan_source(plan)
        self.assertEqual(snapshot["cue_count"], 3)
        corrected.write_text(corrected.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(focus.FocusError, "Source SRT changed"):
            focus.verify_plan_source(plan)

    def test_proofread_uses_glossary_without_rewriting(self):
        glossary = self.work / "glossary.json"
        glossary.write_text(
            json.dumps(
                {
                    "version": 1,
                    "forbidden_terms": [
                        {"text": "生成花纹", "suggest": "生成华纹", "reason": "项目术语"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        output = self.work / "proofread.md"
        before = self.source_srt.read_bytes()
        focus.command_proofread(
            namespace(srt=str(self.source_srt), glossary=str(glossary), output=str(output))
        )
        self.assertEqual(before, self.source_srt.read_bytes())
        text = output.read_text(encoding="utf-8")
        self.assertIn("`生成花纹` → `生成华纹`", text)
        self.assertIn("脚本不会擅自改字", text)

    def test_lock_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(focus.FocusError, "without --confirmed"):
            focus.command_lock(
                namespace(
                    srt=str(self.source_srt),
                    output=str(self.work / "should-not-exist.json"),
                    confirmed=False,
                )
            )
        self.assertFalse((self.work / "should-not-exist.json").exists())

    def test_correction_requires_exact_source_text(self):
        bad = self.work / "bad-corrections.json"
        bad.write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": [
                        {"cue_id": 1, "find": "不存在的词", "replace": "生成华纹"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(focus.FocusError, "cannot find"):
            focus.command_correct(
                namespace(
                    srt=str(self.source_srt),
                    corrections=str(bad),
                    output=str(self.work / "bad-output.srt"),
                    review=str(self.work / "bad-review.md"),
                )
            )

    def test_style_keeps_default_82_and_records_reference_override(self):
        base = ROOT / "skill" / "assets" / "default-style.json"
        default = json.loads(base.read_text(encoding="utf-8"))
        self.assertEqual(default["center_y_ratio"], 0.82)
        reference = self.work / "reference.png"
        Image.new("RGB", (1170, 1755), "white").save(reference)
        output = self.work / "style-v1.json"
        focus.command_style(
            namespace(
                base=str(base),
                output=str(output),
                reference_image=str(reference),
                center_x_ratio=None,
                center_y_ratio=0.73,
                safe_width_ratio=0.76,
                font_size_ratio=None,
                font_size_min=None,
                font_size_max=88,
            )
        )
        style = focus.load_json(output)
        self.assertEqual(style["center_y_ratio"], 0.73)
        self.assertEqual(style["_meta"]["reference_demo"]["width"], 1170)
        self.assertEqual(style["_meta"]["overrides"]["font_size_max"], 88)
        no_reference_output = self.work / "style-default-derived.json"
        focus.command_style(
            namespace(
                base=str(base),
                output=str(no_reference_output),
                reference_image=None,
                center_x_ratio=None,
                center_y_ratio=None,
                safe_width_ratio=None,
                font_size_ratio=None,
                font_size_min=None,
                font_size_max=None,
            )
        )
        no_reference = focus.load_json(no_reference_output)
        self.assertEqual(no_reference["center_y_ratio"], 0.82)
        self.assertIsNone(no_reference["_meta"]["reference_demo"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg required")
    def test_end_to_end_render_frames_and_delivery(self):
        corrected, _, _, plan_path = self.build_locked_plan()
        highlights = self.work / "highlights.json"
        highlights.write_text(
            json.dumps(
                {
                    "version": 1,
                    "global_terms": [],
                    "items": [
                        {"cue_id": 1, "text": "生成华纹"},
                        {"cue_id": 2, "text": "Kimi K3"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        highlighted = self.work / "caption-plan-highlighted.json"
        focus.command_apply(
            namespace(plan=str(plan_path), highlights=str(highlights), output=str(highlighted))
        )

        reference = self.work / "reference.png"
        Image.new("RGB", (540, 960), "white").save(reference)
        style_path = self.work / "style-v1.json"
        focus.command_style(
            namespace(
                base=str(ROOT / "skill" / "assets" / "default-style.json"),
                output=str(style_path),
                reference_image=str(reference),
                center_x_ratio=None,
                center_y_ratio=0.73,
                safe_width_ratio=0.94,
                font_size_ratio=None,
                font_size_min=24,
                font_size_max=32,
            )
        )
        video = self.work / "input.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=#e9e2d3:s=540x960:r=30:d=2.4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100:duration=2.4",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(video),
            ],
            check=True,
        )
        focus.command_validate(
            namespace(
                plan=str(highlighted),
                srt=str(corrected),
                video=str(video),
                tolerance_ms=100,
            )
        )
        preview_card = self.work / "preview.png"
        focus.command_preview(
            namespace(
                plan=str(highlighted),
                style=str(style_path),
                output=str(preview_card),
                cue=1,
                video=str(video),
                width=None,
                height=None,
            )
        )
        with Image.open(preview_card) as preview_image:
            self.assertEqual(preview_image.size, (540, 960))

        rendered = self.work / "rendered.mp4"
        focus.command_render(
            namespace(
                video=str(video),
                plan=str(highlighted),
                style=str(style_path),
                output=str(rendered),
                start=None,
                duration=None,
                crf=23,
                preset="ultrafast",
                keep_workdir=None,
                tolerance_ms=100,
            )
        )
        review_dir = self.work / "review-frames"
        focus.command_frames(
            namespace(
                video=str(rendered),
                plan=str(highlighted),
                style=str(style_path),
                corrections=str(self.corrections),
                output_dir=str(review_dir),
                already_burned=True,
                tolerance_ms=100,
            )
        )
        index = focus.load_json(review_dir / "index.json")
        self.assertIn(1, index["corrected_cue_ids"])
        self.assertTrue(any(frame["cue_id"] == 1 for frame in index["frames"]))
        cue_one = next(frame for frame in index["frames"] if frame["cue_id"] == 1)
        self.assertIn("corrected", cue_one["reasons"])
        self.assertIn("highlighted", cue_one["reasons"])
        self.assertTrue(index["already_burned"])
        self.assertTrue((review_dir / "contact-sheet.jpg").is_file())

        publish_copy = self.work / "publish-copy.md"
        publish_copy.write_text("# Demo title\n\nDemo body\n", encoding="utf-8")
        delivery = self.work / "delivery.json"
        handoff = self.work / "handoff"
        focus.command_deliver(
            namespace(
                video=str(rendered),
                srt=str(corrected),
                plan=str(highlighted),
                style=str(style_path),
                corrections=str(self.corrections),
                review_dir=str(review_dir),
                output=str(delivery),
                handoff_dir=str(handoff),
                name="Final",
                copy_video=True,
                publish_copy=str(publish_copy),
                tolerance_ms=100,
            )
        )
        manifest = focus.load_json(delivery)
        self.assertEqual(manifest["kind"], "subtitle-focus-delivery")
        self.assertEqual(manifest["corrections"]["changed_cue_ids"], [1])
        self.assertEqual(manifest["style"]["center_y_ratio"], 0.73)
        self.assertTrue((handoff / "Final.mp4").is_file())
        self.assertTrue((handoff / "Final.srt").is_file())
        self.assertTrue((handoff / "Final-transcript.md").is_file())
        self.assertTrue((handoff / "Final-publish-copy.md").is_file())
        self.assertTrue((handoff / "Final-delivery.json").is_file())
        with self.assertRaisesRegex(focus.FocusError, "not extracted from this final"):
            focus.command_deliver(
                namespace(
                    video=str(video),
                    srt=str(corrected),
                    plan=str(highlighted),
                    style=str(style_path),
                    corrections=str(self.corrections),
                    review_dir=str(review_dir),
                    output=str(self.work / "mismatched-delivery.json"),
                    handoff_dir=None,
                    name=None,
                    copy_video=False,
                    publish_copy=None,
                    tolerance_ms=100,
                )
            )


if __name__ == "__main__":
    unittest.main()
