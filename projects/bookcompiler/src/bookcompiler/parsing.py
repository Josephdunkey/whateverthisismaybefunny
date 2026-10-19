from __future__ import annotations

import html
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Chapter, Chunk, ParsedBook
from .utils import normalize_text, stable_id

MD_H2_RE = re.compile(r"^\s{0,3}#{2,4}\s+(.+?)\s*$", re.MULTILINE)
MD_H1_RE = re.compile(r"^\s{0,3}#\s+(.+?)\s*$", re.MULTILINE)
CHAPTER_LINE_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零\d]+[章节篇部].*|Chapter\s+\d+.*|Part\s+[IVXLC\d]+.*)\s*$",
    re.IGNORECASE,
)
# Chinese sentences usually have no whitespace after punctuation, so split after
# CJK terminal punctuation unconditionally and after Latin punctuation only when
# followed by whitespace (this avoids splitting decimals and abbreviations).
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])|(?<=[.!?;])\s+")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _chapters_from_markdown(text: str) -> list[Chapter]:
    matches = list(MD_H2_RE.finditer(text))
    if not matches:
        matches = list(MD_H1_RE.finditer(text))
    if not matches:
        return []
    chapters: list[Chapter] = []
    for i, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            chapters.append(Chapter(index=len(chapters) + 1, title=match.group(1).strip(), text=body))
    return chapters


OCR_PAGE_RE = re.compile(r"^\s*[≦<＜]\s*(\d+)\s*[≧>＞]\s*$")


def _chapters_from_ocr_pages(text: str) -> list[Chapter]:
    """Use scanner page markers such as `≦ 12 ≧` as provenance units.

    Many OCR books repeat or garble chapter headings in the table of contents.
    Page markers are much more reliable: every quote can then carry a real page
    number and a bounded source unit.
    """
    lines = text.splitlines(keepends=True)
    marks: list[tuple[int, int]] = []
    offset = 0
    for line in lines:
        match = OCR_PAGE_RE.match(line.strip())
        if match:
            marks.append((offset, int(match.group(1))))
        offset += len(line)
    if len(marks) < 3:
        return []
    chapters: list[Chapter] = []
    for index, (start, page_no) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        body = text[start:end].strip()
        first_line, _, rest = body.partition("\n")
        if OCR_PAGE_RE.match(first_line.strip()):
            body = rest.strip()
        if len(body) < 20:
            continue
        chapters.append(
            Chapter(
                index=len(chapters) + 1,
                title=f"Page {page_no}",
                text=body,
                page_start=page_no,
                page_end=page_no,
            )
        )
    return chapters


def _chapters_from_plain_text(text: str) -> list[Chapter]:
    lines = text.splitlines(keepends=True)
    starts: list[tuple[int, str]] = []
    offset = 0
    for line in lines:
        stripped = line.strip()
        if CHAPTER_LINE_RE.match(stripped) and len(stripped) <= 120:
            starts.append((offset, stripped.lstrip("#").strip()))
        offset += len(line)
    if not starts:
        return []
    chapters: list[Chapter] = []
    for i, (start, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[start:end].strip()
        first_line, _, rest = body.partition("\n")
        if CHAPTER_LINE_RE.match(first_line.strip()):
            body = rest.strip()
        if body:
            chapters.append(Chapter(index=len(chapters) + 1, title=title, text=body))
    return chapters


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        if tag in {"p", "br", "div", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = html.unescape("".join(self.parts))
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _chapters_from_epub(path: Path) -> list[Chapter]:
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = container.find(".//c:rootfile", ns)
        if rootfile is None:
            raise ValueError("EPUB container has no rootfile")
        opf_path = rootfile.attrib["full-path"]
        opf = ET.fromstring(zf.read(opf_path))
        opf_ns = {"o": "http://www.idpf.org/2007/opf"}
        base = Path(opf_path).parent
        manifest = {}
        for item in opf.findall(".//o:manifest/o:item", opf_ns):
            manifest[item.attrib["id"]] = item.attrib["href"]
        chapters: list[Chapter] = []
        for itemref in opf.findall(".//o:spine/o:itemref", opf_ns):
            href = manifest.get(itemref.attrib.get("idref", ""))
            if not href:
                continue
            member = str(base / href) if str(base) != "." else href
            try:
                raw = zf.read(member).decode("utf-8", errors="replace")
            except KeyError:
                continue
            parser = _TextExtractor()
            parser.feed(raw)
            text = parser.text()
            if len(text) < 40:
                continue
            title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
            title = html.unescape(title_match.group(1)).strip() if title_match else f"Section {len(chapters) + 1}"
            chapters.append(Chapter(index=len(chapters) + 1, title=title or f"Section {len(chapters) + 1}", text=text))
        return chapters


def _chapters_from_pdf(path: Path) -> tuple[list[Chapter], int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append((page_no, normalize_text(text)))
    chapters: list[Chapter] = []
    current_title = "Document"
    current_pages: list[tuple[int, str]] = []
    for page_no, text in pages:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if CHAPTER_LINE_RE.match(first_line) and current_pages:
            body = "\n\n".join(t for _, t in current_pages).strip()
            if body:
                chapters.append(Chapter(len(chapters) + 1, current_title, body, current_pages[0][0], current_pages[-1][0]))
            current_title = first_line.lstrip("#").strip()
            current_pages = [(page_no, text)]
        else:
            current_pages.append((page_no, text))
    if current_pages:
        body = "\n\n".join(t for _, t in current_pages).strip()
        if body:
            chapters.append(Chapter(len(chapters) + 1, current_title, body, current_pages[0][0], current_pages[-1][0]))
    if not chapters and pages:
        chapters = [Chapter(1, "Document", "\n\n".join(t for _, t in pages).strip(), 1, pages[-1][0])]
    return chapters, len(pages)


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split a too-long paragraph at sentence boundaries, with a hard fallback."""
    pieces: list[str] = []
    for sentence in SENTENCE_SPLIT_RE.split(paragraph):
        sentence = (sentence or "").strip()
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if sentence:
            pieces.append(sentence)
    return pieces


def _chunk_text(text: str, max_chars: int = 1600, overlap: int = 160) -> list[str]:
    text = normalize_text(text, preserve_paragraphs=True)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            for sentence in _split_long_paragraph(para, max_chars):
                if not sentence:
                    continue
                if len(current) + len(sentence) + 1 <= max_chars:
                    current = f"{current} {sentence}".strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sentence
        elif len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for chunk in chunks[1:]:
            prefix = overlapped[-1][-overlap:] if len(overlapped[-1]) > overlap else overlapped[-1]
            overlapped.append(f"{prefix} {chunk}".strip())
        chunks = overlapped
    return chunks


def parse_book(
    path: str | Path,
    title: str | None = None,
    author: str = "Unknown",
    disciplines: list[str] | None = None,
) -> ParsedBook:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower().lstrip(".")
    pages: int | None = None
    text = ""
    if suffix in {"md", "markdown"}:
        text = _read_text(path)
        chapters = _chapters_from_markdown(text) or _chapters_from_plain_text(text)
    elif suffix in {"txt", "text"}:
        text = _read_text(path)
        chapters = _chapters_from_ocr_pages(text) or _chapters_from_plain_text(text) or _chapters_from_markdown(text)
    elif suffix == "pdf":
        chapters, pages = _chapters_from_pdf(path)
    elif suffix == "epub":
        chapters = _chapters_from_epub(path)
    else:
        raise ValueError(f"Unsupported format: {path.suffix}")
    if not chapters:
        chapters = [Chapter(1, "Document", normalize_text(text, preserve_paragraphs=True))]
    book_title = (title or path.stem).strip()
    book_id = stable_id(book_title, author, str(path.resolve()))
    normalized_chapters: list[Chapter] = []
    chunks: list[Chunk] = []
    for chapter in chapters:
        body = normalize_text(chapter.text, preserve_paragraphs=True)
        if not body:
            continue
        chapter.index = len(normalized_chapters) + 1
        normalized_chapters.append(chapter)
        for position, chunk_text in enumerate(_chunk_text(body)):
            chunk_id = stable_id(book_id, str(chapter.index), str(position), chunk_text[:80])
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    book_id=book_id,
                    chapter_index=chapter.index,
                    chapter_title=chapter.title,
                    position=position,
                    text=chunk_text,
                    page_start=chapter.page_start,
                    page_end=chapter.page_end,
                )
            )
    return ParsedBook(
        book_id=book_id,
        title=book_title,
        author=author,
        path=str(path.resolve()),
        format=suffix,
        disciplines=disciplines or [],
        chapters=normalized_chapters,
        chunks=chunks,
        pages=pages,
    )