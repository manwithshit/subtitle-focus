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
我用Video Kit做了一个小工具

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

    def apply_highlights(self, plan_path, items, name="caption-plan-highlighted.json"):
        highlights = self.work / f"{name}.highlights.json"
        highlights.write_text(
            json.dumps(
                {"version": 1, "global_terms": [], "items": items},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        output = self.work / name
        focus.command_apply(
            namespace(plan=str(plan_path), highlights=str(highlights), output=str(output))
        )
        return output

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
            namespace(
                srt=str(self.source_srt),
                glossary=str(glossary),
                personal_glossary=None,
                use_default_personal=False,
                no_personal_glossary=True,
                project_glossary=None,
                no_project_glossary=True,
                output=str(output),
            )
        )
        self.assertEqual(before, self.source_srt.read_bytes())
        text = output.read_text(encoding="utf-8")
        self.assertIn("`生成花纹` → `生成华纹`", text)
        self.assertIn("脚本不会擅自改字", text)

    def test_proofread_layers_personal_and_project_glossaries(self):
        source = self.work / "layered.srt"
        source.write_text(
            """1
00:00:00,100 --> 00:00:00,700
我用clawd code写了一个工具
""",
            encoding="utf-8",
        )
        personal = self.work / "personal.json"
        personal.write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "我的常用词",
                    "forbidden_terms": [
                        {
                            "text": "clawd code",
                            "suggest": "Claude Code",
                            "reason": "个人常用产品名",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        project = self.work / "project.json"
        project.write_text(
            json.dumps(
                {
                    "version": 1,
                    "name": "当前项目词库",
                    "forbidden_terms": [
                        {
                            "text": "clawd code",
                            "suggest": "Claude Code 项目版",
                            "reason": "项目明确写法",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        output = self.work / "layered-review.md"
        before = source.read_bytes()
        focus.command_proofread(
            namespace(
                srt=str(source),
                glossary=None,
                personal_glossary=str(personal),
                use_default_personal=False,
                no_personal_glossary=False,
                project_glossary=str(project),
                no_project_glossary=False,
                output=str(output),
            )
        )
        self.assertEqual(before, source.read_bytes())
        text = output.read_text(encoding="utf-8")
        self.assertIn("`clawd code` → `Claude Code 项目版`", text)
        self.assertNotIn("`clawd code` → `Claude Code`（个人常用产品名）", text)
        self.assertIn("项目词库", text)
        self.assertNotIn(str(personal), text)
        self.assertNotIn(str(project), text)
        self.assertNotIn(str(source), text)
        self.assertNotIn("我的常用词", text)
        self.assertNotIn("当前项目词库", text)

    def test_proofread_requires_explicit_personal_and_project_choices(self):
        with self.assertRaisesRegex(focus.FocusError, "explicit personal glossary choice"):
            focus.command_proofread(
                namespace(
                    srt=str(self.source_srt),
                    glossary=None,
                    personal_glossary=None,
                    use_default_personal=False,
                    no_personal_glossary=False,
                    project_glossary=None,
                    no_project_glossary=False,
                    output=str(self.work / "missing-personal-choice.md"),
                )
            )
        with self.assertRaisesRegex(focus.FocusError, "explicit project glossary choice"):
            focus.command_proofread(
                namespace(
                    srt=str(self.source_srt),
                    glossary=None,
                    personal_glossary=None,
                    use_default_personal=False,
                    no_personal_glossary=True,
                    project_glossary=None,
                    no_project_glossary=False,
                    output=str(self.work / "missing-project-choice.md"),
                )
            )

    def test_proofread_rejects_plain_markdown_without_timestamps(self):
        transcript = self.work / "transcript.md"
        transcript.write_text("第一句台词\n第二句台词\n", encoding="utf-8")
        with self.assertRaisesRegex(focus.FocusError, "timestamped SRT is required"):
            focus.command_proofread(
                namespace(
                    srt=str(transcript),
                    glossary=None,
                    personal_glossary=None,
                    use_default_personal=False,
                    no_personal_glossary=True,
                    project_glossary=None,
                    no_project_glossary=True,
                    output=str(self.work / "should-not-exist.md"),
                )
            )

    def test_glossary_init_creates_editable_empty_file_without_overwrite(self):
        output = self.work / "project-glossary.json"
        focus.command_glossary_init(namespace(scope="project", output=str(output)))
        glossary = focus.load_json(output)
        self.assertEqual(glossary["version"], 1)
        self.assertEqual(glossary["forbidden_terms"], [])
        self.assertEqual(glossary["name"], "项目词库")
        with self.assertRaisesRegex(focus.FocusError, "Refusing to overwrite"):
            focus.command_glossary_init(namespace(scope="project", output=str(output)))
        original_default = focus.DEFAULT_PERSONAL_GLOSSARY
        try:
            personal = self.work / "config" / "glossary.json"
            focus.DEFAULT_PERSONAL_GLOSSARY = personal
            focus.command_glossary_init(namespace(scope="personal", output=None))
            self.assertEqual(focus.load_json(personal)["name"], "个人词库")
            personal.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "name": "个人词库",
                        "forbidden_terms": [
                            {"text": "常错词", "suggest": "标准词", "reason": "个人写法"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            auto_source = self.work / "auto-personal.srt"
            auto_source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n这里是常错词\n",
                encoding="utf-8",
            )
            auto_review = self.work / "auto-personal-review.md"
            focus.command_proofread(
                namespace(
                    srt=str(auto_source),
                    glossary=None,
                    personal_glossary=None,
                    project_glossary=None,
                    use_default_personal=True,
                    no_personal_glossary=False,
                    no_project_glossary=True,
                    output=str(auto_review),
                )
            )
            self.assertIn("`常错词` → `标准词`", auto_review.read_text(encoding="utf-8"))
        finally:
            focus.DEFAULT_PERSONAL_GLOSSARY = original_default

    def test_correction_preserves_multiline_text_and_repeated_spaces(self):
        source = self.work / "multiline.srt"
        source.write_text(
            """1
00:00:00,100 --> 00:00:01,500
第一行  保留
第二行Video Kit
""",
            encoding="utf-8",
        )
        corrections = self.work / "multiline-corrections.json"
        corrections.write_text(
            json.dumps(
                {
                    "version": 1,
                    "items": [
                        {
                            "cue_id": 1,
                            "find": "保留",
                            "replace": "保留字",
                            "reason": "测试精确替换",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        corrected = self.work / "multiline-corrected.srt"
        review = self.work / "multiline-review.md"
        focus.command_correct(
            namespace(
                srt=str(source),
                corrections=str(corrections),
                output=str(corrected),
                review=str(review),
            )
        )
        output_text = corrected.read_text(encoding="utf-8")
        self.assertIn("第一行  保留字\n第二行Video Kit", output_text)
        review_text = review.read_text(encoding="utf-8")
        self.assertIn("第一行  保留<br>第二行Video Kit", review_text)
        self.assertNotIn(str(source), review_text)
        self.assertNotIn(str(corrected), review_text)
        lock = self.work / "multiline-lock.json"
        focus.command_lock(namespace(srt=str(corrected), output=str(lock), confirmed=True))
        plan = self.work / "multiline-plan.json"
        focus.command_plan(
            namespace(srt=str(corrected), lock=str(lock), output=str(plan), max_chars=50.0)
        )
        segments = focus.load_json(plan)["segments"]
        self.assertEqual(segments[0]["text"], "第一行 保留字 第二行Video Kit")

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

    def test_highlight_policy_allows_one_plain_sentence_between_highlights(self):
        corrected, _, _, plan_path = self.build_locked_plan()
        highlighted = self.apply_highlights(
            plan_path,
            [
                {"cue_id": 1, "text": "华纹"},
                {"cue_id": 3, "text": "3D"},
            ],
        )
        focus.command_validate(
            namespace(plan=str(highlighted), srt=str(corrected), video=None, tolerance_ms=100)
        )
        plan = focus.load_json(highlighted)
        self.assertEqual(plan["statistics"]["longest_plain_run"], 1)
        self.assertGreater(plan["statistics"]["max_segment_highlight_coverage"], 0)
        review = self.work / "highlight-policy-review.md"
        focus.command_review(namespace(plan=str(highlighted), output=str(review)))
        review_text = review.read_text(encoding="utf-8")
        self.assertIn("# 完整字幕稿", review_text)
        self.assertIn("然后点击生成**华纹**", review_text)
        self.assertIn("我用Video Kit做了一个小工具", review_text)
        self.assertIn("然后你还可以**3D** 地旋转它", review_text)
        self.assertNotIn("| # |", review_text)
        self.assertNotIn("未高亮：", review_text)

    def test_highlight_policy_allows_every_sentence(self):
        corrected, _, _, plan_path = self.build_locked_plan()
        highlighted = self.apply_highlights(
            plan_path,
            [
                {"cue_id": 1, "text": "华纹"},
                {"cue_id": 2, "text": "Kit"},
                {"cue_id": 3, "text": "3D"},
            ],
            "every-sentence-highlighted.json",
        )
        focus.command_validate(
            namespace(plan=str(highlighted), srt=str(corrected), video=None, tolerance_ms=100)
        )
        plan = focus.load_json(highlighted)
        self.assertEqual(plan["statistics"]["longest_plain_run"], 0)
        self.assertEqual(plan["statistics"]["highlight_segment_count"], 3)

    def test_highlight_policy_rejects_two_consecutive_plain_sentences(self):
        corrected, _, _, plan_path = self.build_locked_plan()
        highlighted = self.apply_highlights(
            plan_path,
            [{"cue_id": 1, "text": "华纹"}],
            "cadence-invalid.json",
        )
        with self.assertRaisesRegex(focus.FocusError, "highlight cadence"):
            focus.command_validate(
                namespace(plan=str(highlighted), srt=str(corrected), video=None, tolerance_ms=100)
            )
        review = self.work / "cadence-invalid-review.md"
        focus.command_review(namespace(plan=str(highlighted), output=str(review)))
        review_text = review.read_text(encoding="utf-8")
        self.assertIn("# 完整字幕稿（需要调整）", review_text)
        self.assertIn("字幕段 2-1 → 3-1：连续 2 句没有重点", review_text)

    def test_highlight_policy_allows_full_short_sentence_and_reports_coverage(self):
        corrected, _, _, plan_path = self.build_locked_plan()
        highlighted = self.apply_highlights(
            plan_path,
            [
                {"cue_id": 1, "text": "生成华纹"},
                {"cue_id": 3, "text": "3D"},
            ],
            "coverage-informational.json",
        )
        focus.command_validate(
            namespace(plan=str(highlighted), srt=str(corrected), video=None, style=None, tolerance_ms=100)
        )
        review = self.work / "coverage-informational-review.md"
        focus.command_review(namespace(plan=str(highlighted), output=str(review)))
        review_text = review.read_text(encoding="utf-8")
        self.assertIn("然后点击**生成华纹**", review_text)
        self.assertNotIn("需要调整", review_text)
        short_plan = {
            "segments": [
                {
                    "id": "short-1",
                    "cue_id": 1,
                    "text": "好的",
                    "highlights": [{"start": 0, "end": 2, "text": "好的"}],
                }
            ]
        }
        short_errors, report = focus.validate_highlight_policy(short_plan)
        self.assertEqual(short_errors, [])
        self.assertEqual(report["segment_reports"][0]["coverage"], 1.0)
        self.assertEqual(report["density_warnings"], [])

    def test_long_dense_highlight_warns_without_blocking(self):
        corrected, _, _, plan_path = self.build_locked_plan()
        highlighted = self.apply_highlights(
            plan_path,
            [{"cue_id": 2, "text": "我用Video Kit做了一个小工具"}],
            "dense-highlight-warning.json",
        )
        focus.command_validate(
            namespace(plan=str(highlighted), srt=str(corrected), video=None, tolerance_ms=100)
        )
        plan = focus.load_json(highlighted)
        self.assertEqual(plan["statistics"]["dense_highlight_warning_count"], 1)
        review = self.work / "dense-highlight-review.md"
        focus.command_review(namespace(plan=str(highlighted), output=str(review)))
        review_text = review.read_text(encoding="utf-8")
        self.assertIn("完整字幕稿（建议复核）", review_text)
        self.assertIn("建议只保留主要语义词组（提示不阻断）", review_text)

    def test_vertical_layout_auto_shrinks_by_real_pixel_width(self):
        style = focus.load_json(ROOT / "skill/assets/default-style.json")
        segment = {
            "id": "long-1",
            "cue_id": 1,
            "text": "我用手机做了一个非常好用的旅行攻略小工具",
            "highlights": [{"start": 10, "end": 14, "text": "非常好用"}],
        }
        image = focus.render_segment_canvas(segment, style, 1080, 1924)
        self.assertEqual(image.size, (1080, 1924))

    def test_public_base_glossary_is_general_and_bounded(self):
        base = focus.load_json(ROOT / "skill/assets/glossaries/base.json")
        items = base["forbidden_terms"]
        self.assertEqual(len(items), 350)
        self.assertEqual(len({item["text"] for item in items}), 350)
        self.assertEqual(len(base["sources"]), 2)
        base_blob = json.dumps(items, ensure_ascii=False).lower()
        for term in ("chatgpt", "deepseek", "midjourney", "mcp", "claude", "gemini"):
            self.assertNotIn(term, base_blob)
        self.assertEqual(
            sorted(path.name for path in (ROOT / "skill/assets/glossaries").glob("*.json")),
            ["base.json"],
        )

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
                        {"cue_id": 1, "text": "华纹"},
                        {"cue_id": 2, "text": "Kit"},
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
                style=str(style_path),
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
