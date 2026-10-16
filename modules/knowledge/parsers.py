"""P0 file parsers for the knowledge import pipeline (contract §1.5).

P0 formats: ``.txt .md .pdf .docx .pptx`` plus ``.epub`` (text-only EPUB, standard
library only: ``zipfile`` + ``xml.etree.ElementTree``).  Each parser is *optional* —
if a third-party dependency is missing we report ``parser_unavailable`` honestly
instead of pretending the format works.  Parsing never executes document content
and never touches the network.
"""

from __future__ import annotations

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger("knowledge.parsers")

MAX_PAGES_HINT = 500          # soft guard, enforced by the caller/pipeline

EXTS = {
    ".txt": {"source_type": "text", "parser": "builtin-text"},
    ".md": {"source_type": "markdown", "parser": "builtin-text"},
    ".pdf": {"source_type": "pdf_text", "parser": "pdfminer.six"},
    ".docx": {"source_type": "docx_text", "parser": "python-docx"},
    ".pptx": {"source_type": "pptx_text", "parser": "python-pptx"},
    ".epub": {"source_type": "epub_text", "parser": "builtin-epub (zipfile+xml)"},
}


def ext_of(name) -> str:
    n = str(name or "").lower()
    i = n.rfind(".")
    return n[i:] if i >= 0 else ""


def is_p0(ext) -> bool:
    return ext_of(ext) in EXTS


def _mod(name):
    try:
        return __import__(name)
    except Exception:  # noqa: BLE001
        return None


def parser_available(ext):
    """``(available, reason)`` for one extension."""
    ext = ext_of(ext)
    if ext not in EXTS:
        return (False, "unsupported_content_type")
    if ext in (".txt", ".md"):
        return (True, None)
    if ext == ".pdf":
        if _mod("pdfminer") is None:
            return (False, "parser_unavailable (pdfminer.six not installed)")
        return (True, None)
    if ext == ".docx":
        if _mod("docx") is None:
            return (False, "parser_unavailable (python-docx not installed)")
        return (True, None)
    if ext == ".pptx":
        if _mod("pptx") is None:
            return (False, "parser_unavailable (python-pptx not installed)")
        return (True, None)
    if ext == ".epub":
        # stdlib only (zipfile + xml.etree.ElementTree) — always available.
        # Deliberately NOT ebooklib (AGPL, third-party) — see D2 licensing note.
        return (True, None)
    return (False, "unsupported_content_type")


def capabilities():
    """Machine-readable parser table for ``GET /admin/knowledge/parsers``."""
    out = []
    for ext, meta in sorted(EXTS.items()):
        ok, reason = parser_available(ext)
        out.append({"ext": ext, "source_type": meta["source_type"],
                    "parser": meta["parser"], "available": bool(ok),
                    "reason": reason, "p0": True})
    return out


def _norm(text) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return t.strip()


# ---- per-format extraction ------------------------------------------------

def _parse_text(path):
    data = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return _norm(data.decode(enc)), None
        except UnicodeDecodeError:
            continue
    return None, "extract_failed"


def _parse_pdf(path):
    try:
        from pdfminer.high_level import extract_text
    except Exception:  # noqa: BLE001
        return None, "parser_unavailable"
    try:
        text = _norm(extract_text(str(path)))
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__.lower()
        if "password" in name or "encrypt" in str(e).lower():
            return None, "encrypted"
        return None, "extract_failed"
    if not text:
        # a text-less PDF is almost always a scan: no OCR in P0
        return None, "scanned_pdf_no_text"
    return text, None


def _parse_docx(path):
    try:
        import docx
    except Exception:  # noqa: BLE001
        return None, "parser_unavailable"
    try:
        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs if p.text and p.text.strip()]
        for tbl in d.tables:                      # linearize table cells
            for row in tbl.rows:
                cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        text = _norm("\n".join(parts))
    except Exception:  # noqa: BLE001
        return None, "extract_failed"
    if not text:
        return None, "empty_extraction"
    return text, None


def _parse_pptx(path):
    try:
        from pptx import Presentation
    except Exception:  # noqa: BLE001
        return None, "parser_unavailable"
    try:
        prs = Presentation(str(path))
        slides = []
        for i, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.text_frame:
                    t = shape.text_frame.text
                    if t and t.strip():
                        texts.append(t.strip())
            if texts:
                slides.append("[slide %d]\n%s" % (i, "\n".join(texts)))
        text = _norm("\n\n".join(slides))
    except Exception:  # noqa: BLE001
        return None, "extract_failed"
    if not text:
        return None, "empty_extraction"
    return text, None


# ---- EPUB (text-only) -----------------------------------------------------
#
# Standard library only.  No third-party dependency, in particular NOT ebooklib
# (AGPL is a licensing red line for this codebase).  The archive is hostile input,
# so every read is bounded and streamed; nothing is ever executed.
#
# Safety constants (fail-closed).  Values chosen for a *textbook* import where the
# gateway already caps the **compressed** upload at 20 MiB (api_import.MAX_UPLOAD):
#   * a well-formed text EPUB is a few MiB at most, so:
#       - 4096 members is far above any real book's spine/manifest;
#       - 16 MiB per member is far above any single (X)HTML chapter;
#       - 64 MiB total *uncompressed* budget caps the blast radius of a zip bomb
#         whose compressed form still fits under the 20 MiB upload cap (a ~10x
#         overhead is the realistic worst case for text before we refuse).
EPUB_MAX_ENTRIES = 4096                     # max zip members (central directory)
EPUB_MAX_ENTRY_BYTES = 16 * 1024 * 1024     # max uncompressed bytes per member
EPUB_MAX_TOTAL_BYTES = 64 * 1024 * 1024     # max uncompressed bytes, whole archive
EPUB_READ_CHUNK = 64 * 1024                 # streaming read chunk

# D2 ruling: refuse *dangerous* DTD constructs **before** any XML parsing
# (XXE / entity-expansion).  A bare ``<!DOCTYPE html>`` -- which real-world
# XHTML/EPUB frequently carries and which cannot itself define entities -- is
# **tolerated and stripped**; refusing it would reject most genuine EPUBs.
# (TC decision 2026-10-12: relax the initial "reject any DOCTYPE" rule.)
EPUB_REJECT_DTD = True              # master switch for the pre-parse sanitizer
EPUB_ALLOW_BARE_DOCTYPE = True      # strip a DOCTYPE with no entities / no external id

_EPUB_ENTITY_RE = re.compile(rb"<\s*!\s*ENTITY\b", re.IGNORECASE)
_EPUB_EXTERNAL_ID_RE = re.compile(
    rb"<\s*!\s*DOCTYPE\b[^>]*\b(?:SYSTEM|PUBLIC)\b", re.IGNORECASE | re.DOTALL)
_EPUB_SUBSET_RE = re.compile(rb"<\s*!\s*DOCTYPE\b[^>]*\[", re.IGNORECASE | re.DOTALL)
_EPUB_DOCTYPE_RE = re.compile(rb"<\s*!\s*DOCTYPE\b[^>]*>", re.IGNORECASE | re.DOTALL)

# A chapter whose XML cannot be parsed is NOT silently dropped: an explicit marker
# keeps the gap visible to the preview / proofreading step, so a broken book never
# looks like a shorter-but-complete book.  (If *no* chapter is readable the parser
# still reports ``empty_extraction`` rather than returning only markers.)
EPUB_CHAPTER_MISSING_MARKER = "[本章无法解析，内容缺失，需人工确认]"
_EPUB_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_EPUB_HEX_RE = re.compile(r"[0-9A-Fa-f]{2}$")

_EPUB_SKIP_TAGS = frozenset(
    ("script", "style", "head", "title", "meta", "link", "base"))
_EPUB_BLOCK_TAGS = frozenset(
    ("p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
     "section", "article", "header", "footer", "blockquote", "pre", "figure",
     "figcaption", "nav", "aside", "table", "ul", "ol", "dl", "dt", "dd", "hr"))


class _EpubUnsafe(Exception):
    """Archive exceeds a safety limit or contains an escaping member name."""


class _EpubEncrypted(Exception):
    """A member (or the archive) is encrypted."""


def _local(tag):
    """``{ns}name`` → ``name`` (namespace-agnostic matching for XHTML/OPF)."""
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def _epub_sanitize_xml(raw):
    """Return sanitized XML bytes, or ``None`` if the document is **unsafe**.

    Rejected (checked BEFORE any XML parsing, so nothing is ever expanded):
      * ``<!ENTITY ...>``            -- internal entity definitions (billion laughs / XXE);
      * ``<!DOCTYPE ... SYSTEM|PUBLIC ...>`` -- external DTD reference (external fetch / XXE);
      * ``<!DOCTYPE ... [ ... ]>``   -- internal subset (may declare entities).

    Tolerated: a **bare** ``<!DOCTYPE html>`` -- it cannot define entities on its
    own, so it is stripped and the document is parsed normally.
    """
    if not raw or not EPUB_REJECT_DTD:
        return raw
    if _EPUB_ENTITY_RE.search(raw):
        return None
    if _EPUB_EXTERNAL_ID_RE.search(raw):
        return None
    if _EPUB_SUBSET_RE.search(raw):
        return None
    if EPUB_ALLOW_BARE_DOCTYPE:
        return _EPUB_DOCTYPE_RE.sub(b"", raw)
    return None if _EPUB_DOCTYPE_RE.search(raw) else raw


def _unsafe_zip_name(name) -> bool:
    """Reject absolute paths, drive letters, backslash escapes and ``..``."""
    n = str(name or "")
    if not n or "\x00" in n:
        return True
    if n.startswith("/") or n.startswith("\\"):
        return True
    if "\\" in n:
        return True
    if _EPUB_DRIVE_RE.match(n):
        return True
    return any(part == ".." for part in n.split("/"))


def _pct_decode(s: str) -> str:
    """Minimal UTF-8 percent-decoder (avoids pulling in urllib)."""
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        if s[i] == "%" and i + 2 < n and _EPUB_HEX_RE.match(s[i + 1:i + 3]):
            out.append(int(s[i + 1:i + 3], 16))
            i += 3
        else:
            out.extend(s[i].encode("utf-8"))
            i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return s


def _join_opf_path(base: str, href: str) -> str:
    """Resolve a manifest ``href`` against the OPF directory (POSIX semantics)."""
    h = str(href or "").split("#", 1)[0].split("?", 1)[0]
    h = _pct_decode(h)
    if h.startswith("/"):
        full = h.lstrip("/")
    else:
        full = (base + "/" + h) if base else h
    out = []
    for seg in full.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/".join(out)


class _EpubArchive:
    """Streaming, bounded reader over a zip archive (never ``read()`` blind)."""

    def __init__(self, zf):
        self.zf = zf
        self.remaining = EPUB_MAX_TOTAL_BYTES
        self.by_name = {}
        self.by_lower = {}
        for info in zf.infolist():
            self.by_name[info.filename] = info
            self.by_lower.setdefault(info.filename.lower(), info)
        self.count = len(self.by_name)

    def find(self, name):
        info = self.by_name.get(name)
        if info is None:
            info = self.by_lower.get(str(name or "").lower())
        return info

    def read(self, name):
        """Return member bytes, or ``None`` if absent.  Raises on unsafe input."""
        info = self.find(name)
        if info is None:
            return None
        if info.flag_bits & 0x1:                      # encrypted member
            raise _EpubEncrypted()
        if info.file_size > EPUB_MAX_ENTRY_BYTES:
            raise _EpubUnsafe("declared entry size over cap")
        if info.file_size > self.remaining:
            raise _EpubUnsafe("declared size over remaining total budget")
        chunks, total = [], 0
        with self.zf.open(info, "r") as fp:           # stream + count, do not read()
            while True:
                chunk = fp.read(EPUB_READ_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > EPUB_MAX_ENTRY_BYTES:
                    raise _EpubUnsafe("entry over cap while reading")
                if total > self.remaining:
                    raise _EpubUnsafe("total budget over cap while reading")
                chunks.append(chunk)
        self.remaining -= total
        return b"".join(chunks)


def _container_rootfile(raw: bytes):
    """``META-INF/container.xml`` → OPF path (``rootfile/@full-path``)."""
    root = ET.fromstring(raw)
    for el in root.iter():
        if _local(el.tag) == "rootfile":
            fp = el.get("full-path") or el.get("fullpath")
            if fp:
                return fp
    return None


def _opf_manifest_spine(raw: bytes):
    """Parse the OPF → (``{item_id: href}``, ``[idref, ...]`` in spine order)."""
    root = ET.fromstring(raw)
    manifest, spine = {}, []
    for el in root.iter():
        ln = _local(el.tag)
        if ln == "item":
            iid, href = el.get("id"), el.get("href")
            if iid and href:
                manifest[iid] = href
        elif ln == "itemref":
            ref = el.get("idref")
            if ref:
                spine.append(ref)
    return manifest, spine


def _xhtml_text(raw: bytes) -> str:
    """Extract readable text from an XHTML document (namespaces, CDATA, comments).

    ``script``/``style``/``head`` subtrees are dropped; block tags become newlines
    so paragraphs stay separable.  Raises ``ET.ParseError`` on malformed XML.
    """
    root = ET.fromstring(raw)

    def emit(buf, s):
        if s and s.strip():
            buf.append(s)

    buf = []

    def walk(el):
        tag = _local(el.tag)
        if tag in _EPUB_SKIP_TAGS:
            emit(buf, el.tail)                        # keep tail, drop subtree
            return
        if tag == "br":
            buf.append("\n")
        emit(buf, el.text)
        for child in list(el):
            walk(child)
        emit(buf, el.tail)
        if tag in _EPUB_BLOCK_TAGS:
            buf.append("\n")

    body = None
    for el in root.iter():
        if _local(el.tag) == "body":
            body = el
            break
    walk(body if body is not None else root)

    text = "".join(buf)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _parse_epub(path):
    """Text-only EPUB extraction in **spine order**.  Never raises."""
    try:
        zf = zipfile.ZipFile(str(path), "r")
    except zipfile.BadZipFile:
        return None, "epub_malformed"                # not a zip / truncated / corrupt
    except Exception:  # noqa: BLE001
        return None, "extract_failed"
    try:
        try:
            ar = _EpubArchive(zf)
        except Exception:  # noqa: BLE001
            return None, "epub_malformed"
        if ar.count == 0:
            return None, "epub_malformed"            # empty archive
        if ar.count > EPUB_MAX_ENTRIES:
            return None, "epub_unsafe"               # too many members
        for name in ar.by_name:
            if _unsafe_zip_name(name):
                return None, "epub_unsafe"           # path traversal / absolute

        container = ar.read("META-INF/container.xml")
        if container is None:
            return None, "epub_malformed"            # not an EPUB (no container)
        container = _epub_sanitize_xml(container)
        if container is None:
            return None, "epub_unsafe"               # ENTITY / external DTD
        opf_path = _container_rootfile(container)
        if not opf_path or _unsafe_zip_name(opf_path):
            return None, "epub_malformed"

        opf = ar.read(opf_path)
        if opf is None:
            return None, "epub_malformed"            # rootfile missing
        opf = _epub_sanitize_xml(opf)
        if opf is None:
            return None, "epub_unsafe"               # ENTITY / external DTD
        manifest, spine = _opf_manifest_spine(opf)
        if not spine:
            return None, "epub_malformed"            # no spine order to trust

        base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
        entries = []                                 # (spine_pos, body|None), spine order
        for pos, idref in enumerate(spine, 1):       # STRICT spine order
            href = manifest.get(idref)
            if not href:
                continue
            raw = ar.read(_join_opf_path(base, href))
            if raw is None:
                continue                             # dangling itemref
            raw = _epub_sanitize_xml(raw)
            if raw is None:
                return None, "epub_unsafe"           # ENTITY / external DTD before parse
            try:
                body = _xhtml_text(raw)
            except ET.ParseError:
                entries.append((pos, None))          # unreadable -> VISIBLE marker
                continue
            if body:
                entries.append((pos, body))
        if not any(body is not None for _, body in entries):
            return None, "empty_extraction"          # nothing readable at all
        # A chapter we could not read is NOT silently dropped: the marker keeps
        # the gap visible to preview / proofreading, so a broken book never looks
        # like a shorter-but-complete book.
        chapters = [
            ("[chapter %d]\n%s" % (pos, body)) if body is not None
            else ("[chapter %d]\n%s" % (pos, EPUB_CHAPTER_MISSING_MARKER))
            for pos, body in entries]
        text = _norm("\n\n".join(chapters))
        if not text:
            return None, "empty_extraction"
        return text, None
    except _EpubEncrypted:
        return None, "encrypted"
    except _EpubUnsafe:
        return None, "epub_unsafe"
    except zipfile.BadZipFile:
        # a member failed zipfile's own integrity checks (CRC / size / deflate):
        # fail-closed.  This is also the second line of defence behind the
        # streaming budget — a forged declared size never becomes unbounded read.
        return None, "epub_malformed"
    except ET.ParseError:
        return None, "epub_malformed"
    except Exception:  # noqa: BLE001
        return None, "extract_failed"
    finally:
        try:
            zf.close()
        except Exception:  # noqa: BLE001
            pass


_DISPATCH = {".txt": _parse_text, ".md": _parse_text, ".pdf": _parse_pdf,
             ".docx": _parse_docx, ".pptx": _parse_pptx, ".epub": _parse_epub}


def parse_file(path, ext):
    """Return ``(text, error_code)``.  Exactly one of the two is non-None."""
    ext = ext_of(ext)
    fn = _DISPATCH.get(ext)
    if fn is None:
        return None, "unsupported_content_type"
    ok, reason = parser_available(ext)
    if not ok:
        return None, (reason or "parser_unavailable").split(" ")[0]
    return fn(path)
