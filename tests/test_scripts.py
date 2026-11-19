"""Cross-platform unit tests and static hygiene checks for video-transcription scripts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import attend_webinar  # noqa: E402
import build_changelog  # noqa: E402
import extract_enhanced_clips  # noqa: E402
import fix_gdocs_toc_links  # noqa: E402
import prepare_compact_video  # noqa: E402
import transcribe_media  # noqa: E402


class TestFixGDocsTocLinks(unittest.TestCase):
    def test_slug_and_collapse(self) -> None:
        raw = "04. Q&A on Storage, Caching & I/O Limits"
        slug = fix_gdocs_toc_links.github_slug(raw)
        self.assertEqual(slug, "04-qa-on-storage-caching--io-limits")
        self.assertEqual(fix_gdocs_toc_links.collapse_hyphens(slug), "04-qa-on-storage-caching-io-limits")

    def test_extract_and_resolve_heading(self) -> None:
        doc_json = {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {
                                "startIndex": 10,
                                "endIndex": 34,
                                "textRun": {
                                    "content": "1. Intro & Setup",
                                    "textStyle": {"link": {"url": "#1-intro-setup"}},
                                },
                            }
                        ]
                    }
                },
                {
                    "paragraph": {
                        "paragraphStyle": {"headingId": "h.abc123"},
                        "elements": [{"textRun": {"content": "1. Intro & Setup"}}],
                    }
                },
            ]
        }
        exact_h, collapsed_h, numbered_h, spans = fix_gdocs_toc_links.extract_toc_mappings(doc_json)
        self.assertIn("1-intro-setup", spans)
        hid = fix_gdocs_toc_links.resolve_target_heading("1-intro-setup", exact_h, collapsed_h, numbered_h)
        self.assertEqual(hid, "h.abc123")

    def test_write_url_and_webloc_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            written = fix_gdocs_toc_links.write_shortcuts(tmpdir, "Panel: Test/Run", "DOC1234567890", "both")
            self.assertEqual(len(written), 2)
            url_path, webloc_path = Path(written[0]), Path(written[1])
            self.assertTrue(url_path.name.endswith("(Google Doc).url"))
            self.assertTrue(webloc_path.name.endswith("(Google Doc).webloc"))
            self.assertIn("https://docs.google.com/document/d/DOC1234567890/edit", url_path.read_text(encoding="utf-8"))
            self.assertIn(
                "<string>https://docs.google.com/document/d/DOC1234567890/edit</string>",
                webloc_path.read_text(encoding="utf-8"),
            )

    def test_rest_payload_builders_and_tab_selection(self) -> None:
        multipart = fix_gdocs_toc_links.build_drive_multipart_payload("My Doc", b"# Hello", "bnd_test")
        decoded = multipart.decode("utf-8")
        self.assertIn("--bnd_test\r\n", decoded)
        self.assertIn("application/vnd.google-apps.document", decoded)
        self.assertIn("# Hello", decoded)

        batch = fix_gdocs_toc_links.build_batch_update_requests([(10, 20, "h.xyz")], tab_id="t.0")
        req = batch["requests"][0]["updateTextStyle"]
        self.assertEqual(req["range"], {"startIndex": 10, "endIndex": 20, "tabId": "t.0"})
        self.assertEqual(req["textStyle"], {"link": {"headingId": "h.xyz"}})
        self.assertEqual(req["fields"], "link")

        tabbed_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.1"},
                    "documentTab": {"body": {"content": [{"marker": "target"}]}},
                }
            ]
        }
        selected = fix_gdocs_toc_links.select_doc_body(tabbed_doc, "t.1")
        self.assertEqual(selected, {"content": [{"marker": "target"}]})


class TestTranscribeMediaHelpers(unittest.TestCase):
    def test_default_model_and_gemini4_payload(self) -> None:
        self.assertEqual(transcribe_media.DEFAULT_MODEL, "gemini-4-neon")
        captured: dict[str, object] = {}

        def fake_http_request(url, method="GET", headers=None, data=None, timeout=120):
            captured["url"] = url
            captured["payload"] = data.decode("utf-8")
            captured["timeout"] = timeout
            response = (
                '{"candidates":[{"content":{"parts":['
                '{"text":"internal reasoning","thought":true},'
                '{"text":"**[00:05] Host:** Hello world."}'
                ']}}]}'
            ).encode("utf-8")
            return {}, response

        orig_req = transcribe_media._http_request
        try:
            transcribe_media._http_request = fake_http_request
            out = transcribe_media.generate_multimodal(
                "test-key",
                transcribe_media.DEFAULT_MODEL,
                [{"mime_type": "video/mp4", "uri": "https://example.com/file"}],
                "sys",
                "user",
            )
        finally:
            transcribe_media._http_request = orig_req

        self.assertEqual(out, "**[00:05] Host:** Hello world.")
        self.assertIn("/models/gemini-4-neon:generateContent", str(captured["url"]))
        self.assertNotIn("temperature", str(captured["payload"]))
        self.assertIn('"maxOutputTokens": 32768', str(captured["payload"]))
        self.assertEqual(captured["timeout"], 1200)

    def test_mime_detection_and_offset(self) -> None:
        self.assertEqual(transcribe_media.detect_mime_type(Path("clip.mkv")), "video/x-matroska")
        self.assertEqual(transcribe_media.detect_mime_type(Path("clip.wav")), "audio/wav")
        self.assertEqual(transcribe_media.detect_mime_type(Path("audio.m4a")), "audio/mp4")
        self.assertEqual(transcribe_media.parse_offset_label("20:00"), "20:00")
        with self.assertRaises(ValueError):
            transcribe_media.parse_offset_label("bad-offset")

    def test_prompts_and_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx_file = Path(tmpdir) / "ctx.txt"
            ctx_file.write_text("Speaker names: Alice, Bob", encoding="utf-8")
            loaded = transcribe_media.load_context_text(f"@{ctx_file}")
            self.assertEqual(loaded, "Speaker names: Alice, Bob")

        sys_p, usr_p = transcribe_media.build_prompts("transcribe", "15:38", loaded, ["part01.mp4"])
        self.assertIn("multimodal transcriptionist", sys_p)
        self.assertIn("+15:38", usr_p)
        self.assertIn("Alice, Bob", usr_p)

        sys_w, usr_w = transcribe_media.build_prompts("audit-wav", "00:00", "Unclear word", ["w01.wav"])
        self.assertIn("forensic audio", sys_w)
        self.assertIn("w01.wav", usr_w)

        self.assertTrue(transcribe_media.is_audio_only_batch(["ep_part00.mp3", "ep_part01.m4a"]))
        self.assertFalse(transcribe_media.is_audio_only_batch(["part00.mp4"]))
        sys_a, usr_a = transcribe_media.build_prompts("transcribe", "20:00", "Host: Alex", ["ep_part01.mp3"])
        self.assertIn("audio transcriptionist", sys_a)
        self.assertIn("spoken introductions", usr_a)
        self.assertNotIn("lower-thirds", sys_a)

        with tempfile.TemporaryDirectory() as tmpdir:
            info_file = Path(tmpdir) / "loom.info.json"
            info_file.write_text(
                '{"title": "Demo", "uploader": "Alice", "chapters": [{"start_time": 0, "title": "Intro"}], '
                '"formats": [{"url": "https://cdn.example.com/seg.m3u8"}], "cookies": "secret=1"}',
                encoding="utf-8",
            )
            filtered = transcribe_media.load_context_text(f"@{info_file}")
            self.assertIn('"title": "Demo"', filtered)
            self.assertIn('"uploader": "Alice"', filtered)
            self.assertIn('"chapters"', filtered)
            self.assertNotIn('"formats"', filtered)
            self.assertNotIn("secret=1", filtered)


class TestPrepareCompactVideoPodcastHelpers(unittest.TestCase):
    def test_video_format_includes_720p_fallback_before_unrestricted(self) -> None:
        fmt = prepare_compact_video.build_video_format_selector(480)
        self.assertIn("height<=480", fmt)
        self.assertIn("height<=720", fmt)
        self.assertLess(fmt.index("height<=720"), fmt.index("/bv*+ba"))

        fmt_screen = prepare_compact_video.build_video_format_selector(960)
        self.assertIn("height<=720", fmt_screen)
        self.assertIn("height<=1080", fmt_screen)
        self.assertLess(fmt_screen.index("height<=720"), fmt_screen.index("height<=1080"))

    def test_url_detectors_and_rss_parser(self) -> None:
        self.assertTrue(prepare_compact_video.is_spotify_episode_url("https://open.spotify.com/episode/685c45tl6MQyfDac6Qzmor"))
        self.assertFalse(prepare_compact_video.is_spotify_episode_url("https://open.spotify.com/show/1tgqafxZAB0Bjd8nkwVtE4"))
        self.assertTrue(prepare_compact_video.is_apple_podcasts_url("https://podcasts.apple.com/us/podcast/foo/id123?i=456"))
        self.assertTrue(prepare_compact_video._titles_match("How To Go From Researcher to Founder", "How to go from researcher to founder!"))
        self.assertEqual(prepare_compact_video._format_upload_date("Wed, 04 Nov 2026 10:00:00 GMT"), "20261104")
        self.assertEqual(prepare_compact_video._parse_duration_seconds("09:51"), 591)

        sample_rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
          <channel>
            <title>Engineering Conversations</title>
            <item>
              <title>Episode 12: Scaling Inference</title>
              <description>&lt;p&gt;With guests.&lt;/p&gt;</description>
              <pubDate>Mon, 02 Nov 2026 08:00:00 GMT</pubDate>
              <itunes:duration>15:30</itunes:duration>
              <enclosure url="https://cdn.example.com/ep12.mp3" type="audio/mpeg" length="12345" />
            </item>
          </channel>
        </rss>"""
        orig_fetch = prepare_compact_video._http_get_bytes
        try:
            prepare_compact_video._http_get_bytes = lambda url, timeout=30: (url, {}, sample_rss)
            parsed = prepare_compact_video._parse_rss_for_episode("https://cdn.example.com/feed.xml", "Episode 12 Scaling Inference")
        finally:
            prepare_compact_video._http_get_bytes = orig_fetch

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["enclosure_url"], "https://cdn.example.com/ep12.mp3")
        self.assertEqual(parsed["duration"], 930)
        self.assertEqual(parsed["upload_date"], "20261102")


class TestBuildChangelog(unittest.TestCase):
    def test_to_seconds_and_parse_turns(self) -> None:
        self.assertEqual(build_changelog.to_seconds("02:15"), 135)
        self.assertEqual(build_changelog.to_seconds("1:01:05"), 3665)
        lines = [
            "**[00:10] Alice:** Hello [unclear] world.",
            "**[00:15] Carol**: Follow-up remark.",
            "[00:25] Bob",
            "Multiline reply here.",
        ]
        turns = build_changelog.parse_turns(lines)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0]["speaker"], "Alice")
        self.assertEqual(turns[1]["speaker"], "Carol")
        self.assertEqual(turns[2]["speaker"], "Bob")
        self.assertEqual(turns[2]["text"], "Multiline reply here.")


class TestExtractEnhancedClipsHelpers(unittest.TestCase):
    def test_parse_windows(self) -> None:
        parsed = extract_enhanced_clips.parse_windows(["01:40-02:20,28:30-29:05", "01:00:00-01:00:10"])
        self.assertEqual(
            parsed,
            [
                ("00:01:40", "00:02:20"),
                ("00:28:30", "00:29:05"),
                ("01:00:00", "01:00:10"),
            ],
        )

    def test_next_clip_start_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.assertEqual(extract_enhanced_clips.next_clip_start_index(tmp), 1)
            (tmp / "w01_000000_000025.wav").write_bytes(b"RIFF")
            (tmp / "w04_000305_000325_L.wav").write_bytes(b"RIFF")
            self.assertEqual(extract_enhanced_clips.next_clip_start_index(tmp), 5)


class TestAttendWebinarHelpers(unittest.TestCase):
    def test_detect_end_signal_phrase_and_url(self) -> None:
        self.assertEqual(
            attend_webinar.detect_end_signal("This webinar has been ended by host", "https://events.zoom.us/ejl/abc/join"),
            "this webinar has been ended by host",
        )
        self.assertEqual(
            attend_webinar.detect_end_signal("Rate this session", "https://events.zoom.us/ejl/abc/meeting/survey?sessionId=1"),
            "url:/meeting/survey",
        )
        self.assertIsNone(
            attend_webinar.detect_end_signal("Live Q&A in progress", "https://events.zoom.us/ejl/abc/join/xyz")
        )

    def test_parse_silencedetect_and_compute_trim_bounds(self) -> None:
        stderr = (
            "[silencedetect @ 0x1] silence_start: 0.002\n"
            "[silencedetect @ 0x1] silence_end: 311.526 | silence_duration: 311.524\n"
            "[silencedetect @ 0x1] silence_start: 2401.473\n"
            "[silencedetect @ 0x1] silence_end: 3613.807 | silence_duration: 1212.334\n"
        )
        silences = attend_webinar.parse_silencedetect_output(stderr)
        self.assertEqual(silences, [(0.002, 311.526), (2401.473, 3613.807)])
        bounds = attend_webinar.compute_trim_bounds(silences, 3613.807, lead_pad=3.0, tail_pad=4.0)
        self.assertEqual(bounds, (308.53, 2405.47))

    def test_compute_trim_bounds_skips_negligible_silence(self) -> None:
        self.assertIsNone(attend_webinar.compute_trim_bounds([(0.0, 2.5)], 600.0))

    def test_resolve_segment_settings(self) -> None:
        self.assertEqual(
            prepare_compact_video.resolve_segment_settings(False, None, None, None),
            (1200, 25.0, 45.0),
        )
        self.assertEqual(
            prepare_compact_video.resolve_segment_settings(True, None, None, None),
            (600, 15.0, 25.0),
        )
        self.assertEqual(
            prepare_compact_video.resolve_segment_settings(True, 900, 20.0, 30.0),
            (900, 20.0, 30.0),
        )


class TestCliHelpAndRepoHygiene(unittest.TestCase):
    def test_cli_help_exit_zero(self) -> None:
        scripts = [
            "attend_webinar.py",
            "prepare_compact_video.py",
            "extract_enhanced_clips.py",
            "transcribe_media.py",
            "fix_gdocs_toc_links.py",
            "build_changelog.py",
        ]
        for script in scripts:
            res = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / script), "--help"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"{script} --help failed:\n{res.stderr}")

    def test_no_hardcoded_personal_paths(self) -> None:
        patterns = [
            re.compile(r"[A-Za-z]:\\Users\\[^\\/<>\s\"']+"),
            re.compile(r"/Users/[A-Za-z0-9._-]+/"),
            re.compile(r"/home/[A-Za-z0-9._-]+/"),
            re.compile(r"docs\.google\.com/document/d/[A-Za-z0-9_-]{25,}"),
        ]
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for fname in files:
                fpath = Path(root) / fname
                if fpath.resolve() == Path(__file__).resolve():
                    continue
                if fpath.suffix in {".md", ".py", ".ps1", ".txt", ".yml", ".yaml", ".gitignore"}:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for pat in patterns:
                        self.assertIsNone(
                            pat.search(text),
                            msg=f"Disallowed personal path/ID matching {pat.pattern} found in {fpath}",
                        )

    def test_no_em_or_en_dashes_in_docs(self) -> None:
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix in {".md", ".svg"}:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn("\u2014", text, msg=f"Em dash found in documentation file {fpath}")
                    self.assertNotIn("\u2013", text, msg=f"En dash found in documentation file {fpath}")


if __name__ == "__main__":
    unittest.main()
