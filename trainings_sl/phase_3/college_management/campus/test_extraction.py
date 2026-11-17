import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont

from . import extraction


class ExtractionTests(SimpleTestCase):
    @staticmethod
    def archive(files):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return output.getvalue()

    def read(self, raw, suffix):
        return extraction.extract_upload(raw, suffix, settings.WHISPER_MODEL_PATH)

    def test_text_code_data_and_unicode_encodings(self):
        for suffix in (".txt", ".md", ".csv", ".json", ".xml", ".log", ".py", ".js", ".yaml", ".srt"):
            with self.subTest(suffix=suffix):
                result = self.read(b"Library opening time: 09:00", suffix)
                self.assertIn("09:00", result[0][1])
        self.assertIn("Library", self.read("Library hours".encode("utf-16"), ".txt")[0][1])

    def test_html_extracts_content_not_scripts_or_styles(self):
        result = self.read(b"<style>hidden</style><p>Library &amp; study</p><script>danger()</script>", ".html")
        self.assertIn("Library & study", result[0][1])
        self.assertNotIn("hidden", result[0][1])
        self.assertNotIn("danger", result[0][1])

    def test_docx_extracts_paragraphs_and_table_cells(self):
        raw = self.archive({"word/document.xml": (
            '<w:document xmlns:w="urn:word"><w:body>'
            '<w:p><w:r><w:t>Library hours</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Monday 9am</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '</w:body></w:document>'
        )})
        text = self.read(raw, ".docx")[0][1]
        self.assertIn("Library hours", text)
        self.assertIn("Monday 9am", text)

    def test_xlsx_reads_all_sheets_and_does_not_evaluate_formulas(self):
        workbook = Workbook()
        workbook.active.title = "Library"
        workbook.active.append(["Day", "Opens"])
        workbook.active.append(["Monday", "9am"])
        workbook.create_sheet("Transport").append(["Bus", "7am"])
        workbook.active.append(["Formula", '=HYPERLINK("https://example.invalid","link")'])
        output = io.BytesIO()
        workbook.save(output)
        text = self.read(output.getvalue(), ".xlsx")[0][1]
        self.assertIn("Sheet: Library", text)
        self.assertIn("Monday\t9am", text)
        self.assertIn("Sheet: Transport", text)
        self.assertNotIn("example.invalid", text)

    def test_empty_workbook_has_no_indexable_content(self):
        workbook = Workbook()
        output = io.BytesIO()
        workbook.save(output)
        with self.assertRaisesMessage(extraction.ExtractionError, "No readable"):
            self.read(output.getvalue(), ".xlsx")

    def test_pptx_slides_follow_numeric_order(self):
        raw = self.archive({
            f"ppt/slides/slide{i}.xml": f'<p:slide xmlns:p="urn:p"><p:t>Topic {i}</p:t></p:slide>'
            for i in (10, 2, 1)
        })
        text = self.read(raw, ".pptx")[0][1]
        self.assertLess(text.index("Topic 1"), text.index("Topic 2"))
        self.assertLess(text.index("Topic 2"), text.index("Topic 10"))

    def test_open_document_formats_extract_body_and_table_text(self):
        raw = self.archive({"content.xml": (
            '<office:document xmlns:office="urn:o" xmlns:text="urn:t" xmlns:table="urn:table">'
            '<text:p>Library rules</text:p><table:table-cell><text:p>Quiet study</text:p>'
            '</table:table-cell></office:document>'
        )})
        for suffix in (".odt", ".ods", ".odp"):
            with self.subTest(suffix=suffix):
                text = self.read(raw, suffix)[0][1]
                self.assertIn("Library rules", text)
                self.assertIn("Quiet study", text)

    def test_unknown_binary_renamed_corrupt_and_entity_documents_are_rejected(self):
        for suffix, raw in (
            (".exe", b"executable"), (".zip", b"archive"), (".txt", b"\x00\x01binary"),
            (".png", b"not an image"), (".docx", b"not an archive"),
            (".xls", b"not a workbook"), (".doc", b"fake Word"), (".ppt", b"fake slides"),
            (".docx", self.archive({"word/document.xml": '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/hostname">]><x>&x;</x>'})),
        ):
            with self.subTest(suffix=suffix), self.assertRaises(extraction.ExtractionError):
                self.read(raw, suffix)

    def test_archive_inflation_and_text_output_limits(self):
        raw = self.archive({"word/document.xml": "a" * (25 * 1024 * 1024 + 1)})
        with self.assertRaisesMessage(extraction.ExtractionError, "archive limit"):
            self.read(raw, ".docx")
        with self.assertRaisesMessage(extraction.ExtractionError, "50,000"):
            self.read(b"x" * 50_001, ".txt")

    @staticmethod
    def image():
        image = Image.new("RGB", (1400, 300), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
        draw.text((40, 80), "Library closes at 7pm.", font=font, fill="black")
        return image

    @skipUnless(shutil.which("tesseract"), "Local Tesseract OCR is not installed")
    def test_real_image_ocr(self):
        for suffix, format_name in ((".png", "PNG"), (".jpg", "JPEG"), (".tiff", "TIFF"), (".webp", "WEBP")):
            output = io.BytesIO()
            self.image().save(output, format_name)
            text = self.read(output.getvalue(), suffix)[0][1]
            self.assertIn("Library", text)
            self.assertIn("7pm", text)

    @skipUnless(shutil.which("tesseract") and shutil.which("pdftoppm"), "Local PDF OCR tools are not installed")
    def test_real_scanned_pdf_ocr_preserves_page_number(self):
        output = io.BytesIO()
        self.image().save(output, "PDF")
        pages = self.read(output.getvalue(), ".pdf")
        self.assertEqual(pages[0][0], 1)
        self.assertIn("Library", pages[0][1])
        self.assertIn("7pm", pages[0][1])

    @patch("campus.extraction.shutil.which", return_value=None)
    def test_missing_tool_is_an_explicit_dependency_error(self, which):
        with self.assertRaisesMessage(extraction.ExtractionUnavailable, "missing"):
            extraction.command(["tesseract", "image.png", "stdout"])

    @patch("campus.extraction.command")
    def test_media_duration_audio_track_and_model_requirements(self, command):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "media.mp4"
            source.write_bytes(b"synthetic")
            for duration, streams, message in (
                ("601", [{"codec_type": "audio"}], "10 minutes"),
                ("nan", [{"codec_type": "audio"}], "10 minutes"),
                ("60", [{"codec_type": "video"}], "no audio track"),
                ("60", [{"codec_type": "audio"}], "Whisper model"),
            ):
                command.return_value = json.dumps({"format": {"duration": duration}, "streams": streams}).encode()
                error = extraction.ExtractionUnavailable if "Whisper" in message else extraction.ExtractionError
                with self.subTest(duration=duration, streams=streams), self.assertRaisesMessage(error, message):
                    extraction.extract_media(source, extraction.Sections(), directory)
                args = command.call_args.args[0]
                self.assertIn("file,pipe", args)

    @skipUnless(
        shutil.which("ffmpeg") and shutil.which("espeak-ng")
        and (Path(settings.WHISPER_MODEL_PATH) / "model.bin").is_file(),
        "Local speech tools/model are not installed",
    )
    def test_real_audio_and_video_speech_transcription(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "speech.wav"
            subprocess.run([
                "espeak-ng", "-s", "135", "-w", str(audio),
                "The library has many books. Students can borrow books from the library.",
            ], check=True, capture_output=True)
            for suffix in (".wav", ".mp3", ".mp4"):
                media = audio
                if suffix != ".wav":
                    media = Path(directory) / ("speech" + suffix)
                    subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-y", str(media)],
                                   check=True, capture_output=True)
                text = self.read(media.read_bytes(), suffix)[0][1].lower()
                self.assertIn("library", text)
                self.assertIn("books", text)
                self.assertIn("s]", text)
