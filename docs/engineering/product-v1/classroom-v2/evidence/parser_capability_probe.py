#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLASSROOM V2 · 教材解析逐格式能力探针（只读验证 · v2）

用途：逐格式验证 ``modules/knowledge/parsers.py`` 的**真实**能力与依赖状态，
      并实证 P0 批准令要求的边界行为（扫描件无文本层、多栏错序）。

约束：只读、离线、不联网、不调用任何模型或付费服务、不写仓库文件（仅临时目录）。

运行：
    PYTHONPATH= <venv>/bin/python parser_capability_probe.py > out.json
其中 <venv> 需具备 pdfminer.six / python-docx / python-pptx（如 xiaozhi-p2b2）。

覆盖用例
  P0 五格式 : TXT / MD / PDF / DOCX / PPTX
  真实样本  : 仓储内既有 PDF（非合成）
  边界行为  : 图片型 PDF（无文本层 → 期望 scanned_pdf_no_text）
              窄栏距双栏 PDF（期望复现「静默错序」缺陷）
  非 P0     : EPUB / PNG 书页图片（期望 unsupported_content_type）
  依赖矩阵  : 各解释器中 pdfminer / python-docx / python-pptx 的可用性
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = "<project-root>"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from modules.knowledge import parsers  # noqa: E402

REAL_PDF = os.path.join(
    REPO,
    "prototypes/v4-release-progress/evidence/kb-fix-round/materials/fix-03-travel-story.pdf")

# 依赖矩阵要探测的解释器（存在才探测）
INTERPRETERS = [
    ("probe(当前)", sys.executable),
    ("client/.venv", os.path.join(REPO, "client/.venv/bin/python")),
    ("xiaozhi-p2b2", os.path.expanduser(
        "~/.workbuddy/binaries/python/envs/xiaozhi-p2b2/bin/python")),
    ("system", "/usr/local/bin/python3"),
]
DEPS = [("pdfminer.six", "pdfminer"), ("python-docx", "docx"), ("python-pptx", "pptx")]


# ---- 合成样本 -------------------------------------------------------------

def _write_text(work, name, body):
    p = os.path.join(work, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    return p


def _make_docx(work):
    import docx
    d = docx.Document()
    d.add_heading("Unit 1 At the Restaurant", level=1)
    d.add_paragraph("Good evening. A table for two, please.")
    tbl = d.add_table(rows=1, cols=2)
    tbl.rows[0].cells[0].text = "reservation"
    tbl.rows[0].cells[1].text = "/ˌrezəˈveɪʃn/ 预订"
    p = os.path.join(work, "sample.docx")
    d.save(p)
    return p


def _make_pptx(work):
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Hotel English · Check-in"
    slide.placeholders[1].text = "reservation /ˌrezəˈveɪʃn/"
    p = os.path.join(work, "sample.pptx")
    prs.save(p)
    return p


def _make_epub(work):
    """最小但**结构完整**的 EPUB（container → OPF(manifest+spine) → XHTML）。

    注意：必须是可被真实解析的 EPUB。v2 早期版本只写了一个桩 container.xml，
    解析器正确地将其判为 ``epub_malformed`` —— 那验证的是"格式识别"，不是解析能力。
    spine 顺序故意与 zip 条目名顺序**不一致**，以验证解析器真的按 spine 定序。
    """
    p = os.path.join(work, "sample.epub")
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                   'unique-identifier="bookid">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<dc:title>Sample Textbook</dc:title></metadata>'
                   '<manifest>'
                   '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c2" href="z-last.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c1" href="a-first.xhtml" media-type="application/xhtml+xml"/>'
                   '</manifest>'
                   # spine order: a-first 先于 z-last（与 manifest/条目名顺序相反）
                   '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/nav.xhtml",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav>toc</nav></body></html>')
        z.writestr("OEBPS/a-first.xhtml",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                   '<h1>Unit 1</h1><p>reservation /ˌrezəˈveɪʃn/ 预订</p>'
                   '<script>alert(1)</script></body></html>')
        z.writestr("OEBPS/z-last.xhtml",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                   '<h1>Unit 2</h1><p>Good evening. A table for two, please.</p>'
                   '</body></html>')
    return p


def _make_png(work):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(img).text((20, 80), "reservation  booking", fill="black")
    p = os.path.join(work, "page.png")
    img.save(p)
    return p


# ---- PDF 样本（三种） -----------------------------------------------------

def _cupsfilter(src, dst):
    """用 macOS cupsfilter 生成真实 PDF。必须传**文件路径**（stdin 方式已知失败）。"""
    try:
        with open(dst, "wb") as fout:
            r = subprocess.run(["/usr/sbin/cupsfilter", "-m", "application/pdf", src],
                               stdout=fout, stderr=subprocess.DEVNULL, timeout=60)
        if r.returncode != 0 or os.path.getsize(dst) == 0:
            return "cupsfilter_failed rc=%s" % r.returncode
    except Exception as e:  # noqa: BLE001
        return "pdf_gen_failed: %r" % (e,)
    return None


def _make_pdf_text(work):
    """(1) 单栏文本 PDF —— 真实渲染引擎产出，代表常规教材/讲义。"""
    src = _write_text(work, "pdf_src.txt",
                      "Hotel English\nreservation booking\nI have a reservation.\n")
    dst = os.path.join(work, "sample_text.pdf")
    err = _cupsfilter(src, dst)
    return (None, err) if err else (dst, None)


def _make_pdf_image(work):
    """(2) 图片型 PDF（无文本层）—— 代表扫描书页，期望 scanned_pdf_no_text。"""
    try:
        png = _make_png(work)
    except Exception as e:  # noqa: BLE001
        return None, "png_gen_failed: %r" % (e,)
    dst = os.path.join(work, "sample_scanned.pdf")
    err = _cupsfilter(png, dst)
    return (None, err) if err else (dst, None)


def _pdf_escape(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _build_pdf(placements):
    """手工构造最小合法 PDF：placements = [(x, y, text), ...]（绝对定位）。"""
    lines = ["BT /F1 11 Tf"]
    for x, y, t in placements:
        lines.append("1 0 0 1 %d %d Tm (%s) Tj" % (x, y, _pdf_escape(t)))
    lines.append("ET")
    stream = "\n".join(lines).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, body in enumerate(objs, 1):
        offs.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for o in offs:
        out += ("%010d 00000 n \n" % o).encode()
    out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return bytes(out)


# 期望的「视觉阅读顺序」：左栏 3 行 → 右栏 3 行
TWOCOL_EXPECTED = ["LEFTCOL 1", "LEFTCOL 2", "LEFTCOL 3",
                   "RIGHTCOL 1", "RIGHTCOL 2", "RIGHTCOL 3"]

_TWOCOL_LEFT_FMT = "LEFTCOL %d reservation booking confirm detail"
_TWOCOL_RIGHT_FMT = "RIGHTCOL %d deposit luggage passport"


def _make_pdf_twocol(work, x_right, name):
    """双栏 PDF —— 用于实证「多栏静默错序」缺陷。

    content stream 顺序被故意打乱（左右交错），视觉阅读顺序为左栏整列后右栏整列。
    x_right 越小（栏距越窄）越容易触发 pdfminer 跨栏合并 → 静默错序。
    """
    p = os.path.join(work, name)
    y0 = 720
    placements = []
    for i in range(3):
        placements.append((60, y0 - i * 15, _TWOCOL_LEFT_FMT % (i + 1)))
        placements.append((x_right, y0 - i * 15, _TWOCOL_RIGHT_FMT % (i + 1)))
    with open(p, "wb") as fh:
        fh.write(_build_pdf(placements))
    return p


# ---- 依赖矩阵 -------------------------------------------------------------

_PROBE_SRC = (
    "import json,sys\n"
    "r={}\n"
    "for name,mod in %r:\n"
    "    try:\n"
    "        __import__(mod); r[name]='OK'\n"
    "    except Exception:\n"
    "        r[name]='MISSING'\n"
    "print(json.dumps({'python':sys.version.split()[0],'deps':r}))\n"
) % (DEPS,)


def _dependency_matrix():
    rows = []
    for label, exe in INTERPRETERS:
        row = {"label": label, "exe": exe}
        if not (exe and os.path.exists(exe)):
            row.update({"status": "NOT_PRESENT"})
            rows.append(row)
            continue
        try:
            r = subprocess.run([exe, "-c", _PROBE_SRC], capture_output=True,
                               text=True, timeout=60)
            if r.returncode != 0:
                row.update({"status": "ERROR", "detail": (r.stderr or "")[-200:]})
            else:
                d = json.loads(r.stdout.strip().splitlines()[-1])
                row.update({"status": "OK", "python": d["python"], "deps": d["deps"]})
        except Exception as e:  # noqa: BLE001
            row.update({"status": "ERROR", "detail": repr(e)})
        rows.append(row)
    return rows


# ---- 主流程 ---------------------------------------------------------------

def main():
    work = tempfile.mkdtemp(prefix="xz-parser-probe-")
    rep = {
        "probe": "parser_capability_probe/v2",
        "repo": REPO,
        "python": sys.version.split()[0],
        "parsers_table": parsers.capabilities(),
        "dependency_matrix": _dependency_matrix(),
        "cases": [],
        "notes": [],
    }

    def rec(fmt, path, ext, expect_error=None, order_expected=None):
        row = {"format": fmt, "ext": ext}
        if not path or not os.path.exists(path):
            row.update({"status": "NOT_GENERATED", "text_len": 0, "error": None})
        else:
            text, err = parsers.parse_file(path, ext)
            row.update({
                "status": "PARSED" if text else "REFUSED",
                "bytes": os.path.getsize(path),
                "text_len": len(text) if text else 0,
                "error": err,
                "preview": (text[:120].replace("\n", "\\n") if text else ""),
            })
            if expect_error is not None:
                row["expect_error"] = expect_error
                row["expectation_met"] = (err == expect_error)
            if order_expected is not None:
                got = [ln.strip()[:9].strip() for ln in (text or "").splitlines() if ln.strip()]
                got = [g for g in got if g]
                # 归并成"标记"序列（LEFTCOL n / RIGHTCOL n）
                seq = []
                for ln in (text or "").splitlines():
                    for mark in order_expected:
                        if mark.replace(" ", "") in ln.replace(" ", ""):
                            seq.append(mark)
                row.update({
                    "order_expected": order_expected,
                    "order_observed": seq,
                    "order_matches_visual": seq == order_expected,
                    "raw_lines": (text or "").splitlines()[:6],
                })
        rep["cases"].append(row)

    # -- P0 五格式 --
    rec("TXT", _write_text(work, "sample.txt",
        "Hotel English\nreservation /ˌrezəˈveɪʃn/ 预订\nI have a reservation.\n"), ".txt")
    rec("MD", _write_text(work, "sample.md",
        "# Unit 1\n\n- **reservation** /ˌrezəˈveɪʃn/ 预订\n"), ".md")

    p, e = _make_pdf_text(work)
    if e:
        rep["notes"].append("pdf_text: " + e)
    rec("PDF(text)", p, ".pdf")

    for fmt, fn in (("DOCX", _make_docx), ("PPTX", _make_pptx)):
        try:
            rec(fmt, fn(work), "." + fmt.lower())
        except Exception as ex:  # noqa: BLE001
            rep["cases"].append({"format": fmt, "status": "GEN_ERROR", "error": repr(ex)})

    # -- D2: EPUB 文字型（现已支持，随 P0 一并验证）--
    try:
        rec("EPUB", _make_epub(work), ".epub")
    except Exception as ex:  # noqa: BLE001
        rep["cases"].append({"format": "EPUB", "ext": ".epub",
                             "status": "GEN_ERROR", "error": repr(ex)})

    # -- 真实样本 --
    rec("PDF(real-repo)", REAL_PDF, ".pdf")

    # -- 边界行为 --
    p, e = _make_pdf_image(work)
    if e:
        rep["notes"].append("pdf_image: " + e)
    rec("PDF(scanned)", p, ".pdf", expect_error="scanned_pdf_no_text")

    # 宽栏距（书页留白充足）—— 期望正确分列
    try:
        rec("PDF(two-column-wide)", _make_pdf_twocol(work, 330, "twocol_wide.pdf"), ".pdf",
            order_expected=TWOCOL_EXPECTED)
    except Exception as ex:  # noqa: BLE001
        rep["cases"].append({"format": "PDF(two-column-wide)", "status": "GEN_ERROR",
                             "error": repr(ex)})

    # 窄栏距（教科书双栏/双栏+旁注）—— 期望复现静默错序缺陷
    try:
        rec("PDF(two-column-narrow)", _make_pdf_twocol(work, 280, "twocol_narrow.pdf"), ".pdf",
            order_expected=TWOCOL_EXPECTED)
    except Exception as ex:  # noqa: BLE001
        rep["cases"].append({"format": "PDF(two-column-narrow)", "status": "GEN_ERROR",
                             "error": repr(ex)})

    # -- 非 P0 格式（D3：书页图片 OCR 推迟至 P1，P0 保持诚实降级）--
    for fmt, ext, fn in (("IMAGE", ".png", _make_png),):
        try:
            path = fn(work)
        except Exception as ex:  # noqa: BLE001
            rep["cases"].append({"format": fmt, "ext": ext, "status": "GEN_ERROR",
                                 "error": repr(ex)})
            continue
        ok, reason = parsers.parser_available(ext)
        text, err = parsers.parse_file(path, ext)
        rep["cases"].append({
            "format": fmt, "ext": ext,
            "status": "SUPPORTED" if ok else "UNSUPPORTED_BY_DESIGN",
            "is_p0": parsers.is_p0(ext), "available": bool(ok), "reason": reason,
            "text_len": len(text) if text else 0, "error": err,
            "bytes": os.path.getsize(path),
            "expect_error": "unsupported_content_type",
            "expectation_met": (err == "unsupported_content_type"),
        })

    # -- 汇总 --
    p0 = [c for c in rep["cases"] if c.get("ext") in parsers.EXTS]
    rep["summary"] = {
        "p0_formats_verified": sorted({c["ext"] for c in p0}),
        "p0_parsed_ok": sorted({c["ext"] for c in p0 if c.get("status") == "PARSED"}),
        "p0_refused": [(c["format"], c.get("error")) for c in p0
                       if c.get("status") == "REFUSED"],
        "boundary_expectations_met": all(
            c.get("expectation_met", True) for c in rep["cases"]),
        "layout_order_defect_reproduced": any(
            c.get("order_matches_visual") is False for c in rep["cases"]),
    }

    print(json.dumps(rep, ensure_ascii=False, indent=2))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
