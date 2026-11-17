"""Local file extraction, executed in a bounded subprocess for each upload."""

import io
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import warnings
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from xlrd import XLRDError, open_workbook


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT = 50_000
MAX_PAGES = 100
MAX_OCR_PAGES = 20
MAX_MEDIA_SECONDS = 600
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm",
    ".log", ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".sql", ".sh", ".css", ".scss", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".rst", ".tex", ".srt", ".vtt", ".ipynb",
}
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".doc", ".xls", ".ppt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
MEDIA_FORMATS = {
    ".mp3": "mp3", ".wav": "wav", ".m4a": "mov", ".mp4": "mov", ".mov": "mov",
    ".webm": "matroska", ".mkv": "matroska", ".ogg": "ogg", ".flac": "flac",
    ".avi": "avi", ".aac": "aac", ".mpeg": "mpeg", ".mpg": "mpeg",
}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | OFFICE_EXTENSIONS | IMAGE_EXTENSIONS | set(MEDIA_FORMATS) | {".pdf"}
Image.MAX_IMAGE_PIXELS = 20_000_000


class ExtractionError(ValueError):
    pass


class ExtractionUnavailable(Exception):
    pass


class Sections:
    def __init__(self):
        self.pages = []
        self.length = 0

    def add(self, page, text):
        if not isinstance(text, str):
            raise ExtractionError("The parser did not return readable text.")
        self.length += len(text)
        if self.length > MAX_TEXT:
            raise ExtractionError("Extracted text must be 50,000 characters or fewer.")
        if "\x00" in text:
            raise ExtractionError("Knowledge text cannot contain null characters.")
        if text.strip():
            self.pages.append((page, text))


def command(args, timeout=60):
    if not shutil.which(args[0]):
        raise ExtractionUnavailable(f"Local file tool '{args[0]}' is missing. See the README installation steps.")
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("Local file processing timed out. Use a smaller or simpler file.") from exc
    if result.returncode:
        raise ExtractionError(f"Local {args[0]} could not read this file. It may be damaged, encrypted, or unsupported.")
    return result.stdout


def decode_text(raw):
    try:
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ExtractionError("Text files must use UTF-8 or BOM-marked UTF-16 encoding.") from exc
    if any(ord(char) < 32 and char not in "\t\r\n\f" for char in text):
        raise ExtractionError("This file contains binary data, not readable text.")
    return text


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        if not self.ignored and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def checked_archive(path):
    archive = zipfile.ZipFile(path)
    entries = archive.infolist()
    if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 25 * 1024 * 1024:
        archive.close()
        raise ExtractionError("Office file expands beyond the 25 MB / 2,000-entry archive limit.")
    if any(entry.flag_bits & 1 for entry in entries):
        archive.close()
        raise ExtractionError("Encrypted Office archives are not supported.")
    return archive


def local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def xml_paragraphs(root, tag="p"):
    for element in root.iter():
        if local_name(element) == tag:
            yield "".join(element.itertext())


def extract_office(path, output):
    suffix = path.suffix
    if suffix == ".doc":
        if not path.read_bytes().startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            raise ExtractionError("This is not a valid legacy Word document.")
        output.add(None, command(["antiword", "-m", "UTF-8.txt", str(path)]).decode("utf-8"))
    elif suffix == ".ppt":
        if not path.read_bytes().startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            raise ExtractionError("This is not a valid legacy PowerPoint document.")
        output.add(None, command(["catppt", "-d", "utf-8", str(path)]).decode("utf-8"))
    elif suffix == ".xls":
        workbook = open_workbook(path, on_demand=True)
        try:
            for sheet in workbook.sheets():
                if sheet.nrows * sheet.ncols > 100_000:
                    raise ExtractionError("Spreadsheets must contain at most 100,000 cells per sheet.")
                first = True
                for row in sheet.get_rows():
                    if any(cell.value not in {"", None} for cell in row):
                        prefix = f"Sheet: {sheet.name}\n" if first else ""
                        output.add(None, prefix + "\t".join(str(cell.value) for cell in row) + "\n")
                        first = False
        finally:
            workbook.release_resources()
    else:
        with checked_archive(path) as archive:
            if suffix == ".xlsx":
                workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
                try:
                    cells = 0
                    for sheet in workbook:
                        if (sheet.max_row or 0) * (sheet.max_column or 0) > 100_000:
                            raise ExtractionError("Spreadsheets must contain at most 100,000 cells per sheet.")
                        first = True
                        for row in sheet.iter_rows(values_only=True):
                            cells += len(row)
                            if cells > 100_000:
                                raise ExtractionError("Spreadsheets must contain at most 100,000 cells.")
                            if any(cell is not None for cell in row):
                                prefix = f"Sheet: {sheet.title}\n" if first else ""
                                output.add(None, prefix + "\t".join("" if cell is None else str(cell) for cell in row) + "\n")
                                first = False
                finally:
                    workbook.close()
            elif suffix == ".docx":
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                for paragraph in root.iter():
                    if local_name(paragraph) == "p":
                        text = "".join(node.text or "" for node in paragraph.iter() if local_name(node) == "t")
                        output.add(None, text + "\n")
            elif suffix == ".pptx":
                slides = sorted(
                    (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                    key=lambda name: int(re.search(r"slide(\d+)", name).group(1)),
                )
                if not slides or len(slides) > MAX_PAGES:
                    raise ExtractionError("Presentations must contain 1-100 slides.")
                for number, name in enumerate(slides, 1):
                    root = ElementTree.fromstring(archive.read(name))
                    text = "\n".join(
                        node.text or "" for node in root.iter() if local_name(node) == "t"
                    )
                    if text.strip():
                        output.add(None, f"Slide {number}:\n{text}")
            else:
                root = ElementTree.fromstring(archive.read("content.xml"))
                for text in xml_paragraphs(root):
                    output.add(None, text + "\n")


def ocr_image(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(path) as image:
                if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                    raise ExtractionError("Images must contain at most 20 million pixels.")
                image.verify()
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise ExtractionError("Image dimensions exceed the safe OCR limit.") from exc
    return command(["tesseract", str(path), "stdout", "-l", "eng", "--psm", "3"]).decode("utf-8")


def extract_pdf(path, output):
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ExtractionError("Encrypted PDFs are not supported.")
    if len(reader.pages) > MAX_PAGES:
        raise ExtractionError("PDFs must contain at most 100 pages.")
    ocr_pages = 0
    with tempfile.TemporaryDirectory() as directory:
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                ocr_pages += 1
                if ocr_pages > MAX_OCR_PAGES:
                    raise ExtractionError("A PDF may contain at most 20 pages requiring OCR.")
                prefix = str(Path(directory) / "page")
                command(["pdftoppm", "-f", str(number), "-l", str(number), "-singlefile",
                         "-scale-to", "2400", "-png", str(path), prefix])
                text = ocr_image(Path(prefix + ".png"))
                Path(prefix + ".png").unlink()
            output.add(number, text)


def extract_images(path, output):
    with Image.open(path) as image:
        if getattr(image, "n_frames", 1) > MAX_OCR_PAGES:
            raise ExtractionError("Image files may contain at most 20 frames.")
        with tempfile.TemporaryDirectory() as directory:
            for frame in range(getattr(image, "n_frames", 1)):
                image.seek(frame)
                if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                    raise ExtractionError("Images must contain at most 20 million pixels.")
                rendered = Path(directory) / "image.png"
                image.convert("RGB").save(rendered)
                output.add(None, ocr_image(rendered))


def extract_media(path, output, model_path):
    demuxer = MEDIA_FORMATS[path.suffix]
    info = json.loads(command([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-f", demuxer,
        "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path),
    ]))
    if not any(stream.get("codec_type") == "audio" for stream in info.get("streams", [])):
        raise ExtractionError("This file has no audio track to transcribe. Silent video is not supported.")
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ExtractionError("Could not determine recording duration.") from exc
    if not 0 < duration <= MAX_MEDIA_SECONDS:
        raise ExtractionError("Audio/video recordings must be 10 minutes or shorter.")
    if not all((Path(model_path) / filename).is_file()
               for filename in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")):
        raise ExtractionUnavailable("The local Whisper model is missing or incomplete. See the README speech-model setup steps.")
    with tempfile.TemporaryDirectory() as directory:
        audio = Path(directory) / "audio.wav"
        command([
            "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-f", demuxer,
            "-i", str(path), "-t", "600", "-vn", "-ac", "1", "-ar", "16000", "-y", str(audio),
        ])
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(str(model_path), device="cpu", compute_type="int8", cpu_threads=2,
                                 num_workers=1, local_files_only=True)
        except (RuntimeError, ValueError) as exc:
            raise ExtractionUnavailable("The local Whisper model could not be loaded. Reinstall it using the README steps.") from exc
        segments, _ = model.transcribe(str(audio), beam_size=1, vad_filter=True)
        for segment in segments:
            output.add(None, f"[{segment.start:.1f}s-{segment.end:.1f}s] {segment.text.strip()}\n")


def extract_file(path, model_path=""):
    path = Path(path)
    output = Sections()
    try:
        if path.suffix in TEXT_EXTENSIONS:
            text = decode_text(path.read_bytes())
            if path.suffix in {".html", ".htm"}:
                parser = HTMLText()
                parser.feed(text)
                text = "".join(parser.parts)
            output.add(None, text)
        elif path.suffix == ".pdf":
            extract_pdf(path, output)
        elif path.suffix in OFFICE_EXTENSIONS:
            extract_office(path, output)
        elif path.suffix in IMAGE_EXTENSIONS:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                extract_images(path, output)
        elif path.suffix in MEDIA_FORMATS:
            extract_media(path, output, model_path)
        else:
            raise ExtractionError("Unsupported file type. Use one of the formats listed beside the upload control.")
    except (ExtractionError, ExtractionUnavailable):
        raise
    except (PyPdfError, zipfile.BadZipFile, KeyError, ElementTree.ParseError, DefusedXmlException,
            XLRDError, UnidentifiedImageError, OSError, UnicodeError, ValueError, TypeError,
            Image.DecompressionBombError, Image.DecompressionBombWarning, RecursionError) as exc:
        raise ExtractionError("Could not read this file. It may be damaged, encrypted, or incorrectly named.") from exc
    if not output.pages:
        raise ExtractionError("No readable text or speech was found in this file.")
    # Keep tables and paragraphs together before the existing overlapping chunker runs.
    merged = []
    for page, text in output.pages:
        if merged and merged[-1][0] == page:
            merged[-1] = (page, merged[-1][1] + text)
        else:
            merged.append((page, text))
    return merged


def extract_upload(raw, suffix, model_path):
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ExtractionError("Unsupported file type. Executables, archives, and unknown formats are not accepted.")
    with tempfile.TemporaryDirectory(prefix="campusflow-extract-") as directory:
        source = Path(directory) / ("upload" + suffix)
        source.write_bytes(raw)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "campus.extraction", str(source), str(model_path)],
                stdout=stdout, stderr=stderr, start_new_session=True,
                env={**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
                     "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
            )
            try:
                process.wait(timeout=180)
            except subprocess.TimeoutExpired as exc:
                raise ExtractionError("File processing exceeded 3 minutes. Use a smaller file or shorter recording.") from exc
            finally:
                # Also stop any converter children left behind by a timed-out or failed worker.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            stdout.seek(0)
            raw_result = stdout.read(400_001)
        if process.returncode not in {0, 2, 3} or len(raw_result) > 400_000:
            raise ExtractionError("Local file processing failed or exceeded its resource limits.")
        try:
            result = json.loads(raw_result)
        except (ValueError, UnicodeError) as exc:
            raise ExtractionError("The local file reader returned an invalid result.") from exc
        if process.returncode == 3:
            raise ExtractionUnavailable(result["error"])
        if process.returncode == 2:
            raise ExtractionError(result["error"])
        return result["pages"]


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (150, 150))
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    try:
        pages = extract_file(sys.argv[1], sys.argv[2])
    except ExtractionError as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(2)
    except ExtractionUnavailable as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(3)
    print(json.dumps({"pages": pages}))
