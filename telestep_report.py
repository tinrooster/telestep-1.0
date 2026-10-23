"""
telestep_report.py - turn a Session into Markdown / DOCX / HTML / PDF / plain text.

Annotated images are re-rendered from the unannotated raw screenshots every time, so the
numbers on the pictures always match the step numbers after you delete, reorder or exclude steps.
"""
import base64
import datetime as dt
import html
import re
import traceback
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from PIL import Image

from telestep_core import annotate, clean_text
from telestep_model import environment_text

CALLOUT = {  # level -> (label, fill colour, accent colour)
    "note": ("Note", "E3F2FD", "1E88E5"),
    "warning": ("Warning", "FFF3E0", "F59E0B"),
    "tip": ("Tip", "E8F5E9", "2E9E4F"),
}
FORMATS = {"md": "Markdown", "docx": "Word (DOCX)", "html": "HTML (single file)", "pdf": "PDF", "txt": "Plain text"}
_GENERATED = re.compile(r"^step_\d{3}_[0-9a-f]{8}(_after)?\.jpg$")


@dataclass
class Template:
    wording: str = "friendly"  # friendly | technical
    header: str = ""  # shown at the top of every page / the page header
    footer: str = ""
    logo: str = ""  # path to a PNG/JPG
    author: str = ""
    accent: str = "#1e88e5"
    show_time: bool = True
    show_window: bool = True
    show_app: bool = True
    environment: bool = True  # appendix with machine/OS/display details
    image_width_in: float = 6.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_settings(cls, settings):
        d = dict((settings or {}).get("template", {}))
        if "wording" in (settings or {}):
            d.setdefault("wording", settings["wording"])
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


# ---------------------------------------------------------------------------
# images + model
# ---------------------------------------------------------------------------
def render_step_image(session, step, number):
    """Annotated PIL image for a step (None if it has no picture).  Used by export and the review editor."""
    if step.raw and (session.dir / step.raw).exists():
        img = Image.open(session.dir / step.raw).convert("RGB")
        return annotate(img, step.marker, number if step.numbered else None)
    if step.image and (session.dir / step.image).exists():  # imported v1 session: already annotated
        return Image.open(session.dir / step.image).convert("RGB")
    return None


def render_images(session):
    """(Re)write images/step_NNN_<id>.jpg for every exported step and drop stale generated files."""
    session.make_dirs()
    nums = session.numbering()
    keep = set()
    for s in session.steps:
        if s.skip or s.kind in ("note", "section"):
            continue
        n = nums.get(s.id, 0)
        img = render_step_image(session, s, n)
        if img is not None and s.raw:
            rel = f"images/step_{n:03d}_{s.id}.jpg"
            img.save(session.dir / rel, "JPEG", quality=88)
            s.image = rel
            keep.add(Path(rel).name)
        if s.raw_after and (session.dir / s.raw_after).exists():
            rel = f"images/step_{n:03d}_{s.id}_after.jpg"
            Image.open(session.dir / s.raw_after).convert("RGB").save(session.dir / rel, "JPEG", quality=88)
            s.image_after = rel
            keep.add(Path(rel).name)
    for f in session.img_dir.iterdir():
        if _GENERATED.match(f.name) and f.name not in keep:
            try:
                f.unlink()
            except OSError:
                pass


def build_blocks(session, tpl):
    nums = session.numbering()
    out = []
    for s in session.steps:
        if s.skip:
            continue
        cap = clean_text(s.caption(tpl.wording))
        if s.kind == "section":
            out.append({"type": "section", "text": cap})
        elif s.kind == "note":
            out.append({"type": "callout", "level": s.level if s.level in CALLOUT else "note", "text": cap})
        else:
            meta = []
            if tpl.show_window and s.window:
                meta.append(f"Window: {clean_text(s.window)}")
            if tpl.show_app and s.app:
                meta.append("App: " + clean_text(s.app + (f" {s.app_version}" if s.app_version else "")))
            if tpl.show_time and s.when:
                meta.append(f"Time: {s.when}")
            imgs = []
            if s.image:
                imgs.append(("Before" if s.image_after else "", s.image))
            if s.image_after:
                imgs.append(("After", s.image_after))
            out.append({"type": "step", "n": nums.get(s.id, 0), "text": cap, "meta": " | ".join(meta),
                        "images": imgs, "dialog": clean_text(s.dialog_text)})
    return out


def _subtitle(session, tpl):
    bits = [f"Recorded {session.created.replace('T', ' ')[:16]} on {clean_text(session.host)}"]
    if tpl.author:
        bits.append(f"by {clean_text(tpl.author)}")
    return " ".join(bits)


def _md_escape_lines(text):
    return text.strip().splitlines() or [""]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def write_markdown(session, tpl):
    blocks = build_blocks(session, tpl)
    has_sections = any(b["type"] == "section" for b in blocks)
    lines = []
    if tpl.header:
        lines += [f"_{clean_text(tpl.header)}_", ""]
    lines += [f"# {clean_text(session.title)}", "", f"_{_subtitle(session, tpl)}_", ""]
    for b in blocks:
        if b["type"] == "section":
            lines += [f"## {b['text']}", ""]
        elif b["type"] == "callout":
            label = CALLOUT[b["level"]][0]
            body = _md_escape_lines(b["text"])
            lines.append(f"> **{label}:** {body[0]}")
            lines += [f"> {ln}" for ln in body[1:]]
            lines.append("")
        else:
            lines.append(f"{'###' if has_sections else '##'} Step {b['n']}")
            lines.append(f"**{b['text'].replace('`', '')}**  ")
            if b["meta"]:
                lines.append(f"_{b['meta']}_")
            lines.append("")
            if b["dialog"]:
                lines += ["> **Dialog text:**"] + [f"> {ln}" for ln in _md_escape_lines(b["dialog"])] + [""]
            for label, rel in b["images"]:
                if label:
                    lines += [f"_{label}_", ""]
                lines += [f"![Step {b['n']}]({rel})", ""]
    if tpl.environment and session.environment:
        lines += ["## Environment", "", "| | |", "|---|---|"]
        lines += [f"| {k} | {str(v).replace('|', '/')} |" for k, v in session.environment.items()]
        lines.append("")
    if tpl.footer:
        lines += ["---", f"_{clean_text(tpl.footer)}_", ""]
    path = session.dir / "steps.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# plain text (also used for "copy steps to clipboard")
# ---------------------------------------------------------------------------
def steps_text(session, tpl):
    lines = [clean_text(session.title), "=" * min(60, max(8, len(session.title))), ""]
    for b in build_blocks(session, tpl):
        if b["type"] == "section":
            lines += ["", b["text"].upper(), "-" * len(b["text"])]
        elif b["type"] == "callout":
            body = _md_escape_lines(b["text"])
            lines.append(f"   {CALLOUT[b['level']][0]}: {body[0]}")
            lines += [f"   {ln}" for ln in body[1:]]
        else:
            lines.append(f"{b['n']}. {b['text']}")
            if b["dialog"]:
                lines += [f"   Dialog text: {ln}" for ln in _md_escape_lines(b["dialog"])]
    return "\n".join(lines) + "\n"


def write_text(session, tpl):
    path = session.dir / "steps.txt"
    path.write_text(steps_text(session, tpl), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def _shade(cell, fill):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _page_number(paragraph):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def write_docx(session, tpl):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    doc = Document()
    sec = doc.sections[0]
    # ---- header / footer ----
    hp = sec.header.paragraphs[0]
    if tpl.logo and Path(tpl.logo).exists():
        try:
            hp.add_run().add_picture(tpl.logo, height=Inches(0.4))
            hp.add_run("   ")
        except Exception:
            pass
    if tpl.header:
        r = hp.add_run(clean_text(tpl.header))
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
    fp = sec.footer.paragraphs[0]
    if tpl.footer:
        r = fp.add_run(clean_text(tpl.footer) + "    ")
        r.font.size = Pt(9)
    fp.add_run("Page ").font.size = Pt(9)
    _page_number(fp)

    doc.add_heading(clean_text(session.title), 0)
    sub = doc.add_paragraph().add_run(_subtitle(session, tpl))
    sub.italic = True

    for b in build_blocks(session, tpl):
        if b["type"] == "section":
            doc.add_heading(b["text"], level=1)
        elif b["type"] == "callout":
            label, fill, accent = CALLOUT[b["level"]]
            cell = doc.add_table(rows=1, cols=1).cell(0, 0)
            _shade(cell, fill)
            p = cell.paragraphs[0]
            lead = p.add_run(f"{label}: ")
            lead.bold = True
            lead.font.color.rgb = RGBColor.from_string(accent)
            p.add_run(b["text"].strip())  # "\n" becomes a line break in Word
            doc.add_paragraph()
        else:
            doc.add_heading(f"Step {b['n']}", level=2)
            run = doc.add_paragraph().add_run(b["text"].replace("`", ""))
            run.bold = True
            if b["meta"]:
                m = doc.add_paragraph().add_run(b["meta"])
                m.italic = True
                m.font.size = Pt(9)
            if b["dialog"]:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.25)
                p.add_run("Dialog text: ").bold = True
                p.add_run(b["dialog"])
            for label, rel in b["images"]:
                if label:
                    doc.add_paragraph().add_run(label).italic = True
                doc.add_picture(str(session.dir / rel), width=Inches(tpl.image_width_in))
    if tpl.environment and session.environment:
        doc.add_heading("Environment", level=1)
        t = doc.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for k, v in session.environment.items():
            row = t.add_row().cells
            row[0].text, row[1].text = clean_text(k), clean_text(str(v))
    path = session.dir / "steps.docx"
    doc.save(path)
    return path


# ---------------------------------------------------------------------------
# HTML (single self-contained file)
# ---------------------------------------------------------------------------
def _data_uri(path):
    p = Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def _h(text):
    return html.escape(text).replace("\n", "<br>")


def write_html(session, tpl):
    acc = tpl.accent or "#1e88e5"
    css = f"""
    :root {{ --acc: {acc}; }}
    body {{ font: 15px/1.5 "Segoe UI", system-ui, sans-serif; color: #1c1f23; max-width: 920px; margin: 0 auto; padding: 24px 20px 60px; }}
    header.top {{ display: flex; align-items: center; gap: 12px; color: #667; font-size: 13px; border-bottom: 1px solid #dde; padding-bottom: 8px; margin-bottom: 18px; }}
    header.top img {{ height: 36px; }}
    h1 {{ margin: 0 0 4px; }} .sub {{ color: #667; font-style: italic; margin-bottom: 22px; }}
    h2.section {{ margin-top: 34px; padding-bottom: 4px; border-bottom: 2px solid var(--acc); }}
    .step {{ margin: 22px 0; page-break-inside: avoid; }}
    .step h3 {{ margin: 0; color: var(--acc); font-size: 14px; text-transform: uppercase; letter-spacing: .05em; }}
    .step .cap {{ font-weight: 600; font-size: 17px; margin: 2px 0; }}
    .meta {{ color: #778; font-size: 12px; }}
    figure {{ margin: 8px 0 0; }} figure img {{ max-width: 100%; border: 1px solid #ccd; border-radius: 4px; }}
    figcaption {{ font-size: 12px; color: #778; margin-bottom: 2px; }}
    .callout {{ border-left: 4px solid; padding: 8px 12px; margin: 16px 0; border-radius: 3px; }}
    .callout b {{ margin-right: 4px; }}
    .dialog {{ background: #f6f6f8; border-left: 3px solid #999; padding: 6px 10px; margin: 6px 0; font-family: Consolas, monospace; font-size: 13px; }}
    table.env {{ border-collapse: collapse; font-size: 13px; }} table.env td {{ border: 1px solid #ccd; padding: 3px 10px; }}
    table.env td:first-child {{ color: #556; }}
    footer {{ margin-top: 40px; color: #889; font-size: 12px; border-top: 1px solid #dde; padding-top: 8px; }}
    @media print {{ body {{ max-width: none; padding: 0; }} }}
    """
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(session.title)}</title>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{css}</style></head><body>"]
    if tpl.header or (tpl.logo and Path(tpl.logo).exists()):
        logo = f"<img alt='' src='{_data_uri(tpl.logo)}'>" if tpl.logo and Path(tpl.logo).exists() else ""
        out.append(f"<header class='top'>{logo}<span>{_h(clean_text(tpl.header))}</span></header>")
    out.append(f"<h1>{_h(clean_text(session.title))}</h1><div class='sub'>{_h(_subtitle(session, tpl))}</div>")
    for b in build_blocks(session, tpl):
        if b["type"] == "section":
            out.append(f"<h2 class='section'>{_h(b['text'])}</h2>")
        elif b["type"] == "callout":
            label, fill, accent = CALLOUT[b["level"]]
            out.append(f"<div class='callout' style='background:#{fill};border-color:#{accent}'>"
                       f"<b style='color:#{accent}'>{label}:</b>{_h(b['text'].strip())}</div>")
        else:
            out.append(f"<section class='step'><h3>Step {b['n']}</h3><div class='cap'>{_h(b['text'])}</div>")
            if b["meta"]:
                out.append(f"<div class='meta'>{_h(b['meta'])}</div>")
            if b["dialog"]:
                out.append(f"<div class='dialog'>{_h(b['dialog'])}</div>")
            for label, rel in b["images"]:
                cap = f"<figcaption>{label}</figcaption>" if label else ""
                out.append(f"<figure>{cap}<img alt='Step {b['n']}' src='{_data_uri(session.dir / rel)}'></figure>")
            out.append("</section>")
    if tpl.environment and session.environment:
        out.append("<h2 class='section'>Environment</h2><table class='env'>")
        out += [f"<tr><td>{_h(k)}</td><td>{_h(str(v))}</td></tr>" for k, v in session.environment.items()]
        out.append("</table>")
    if tpl.footer:
        out.append(f"<footer>{_h(clean_text(tpl.footer))}</footer>")
    out.append("</body></html>")
    path = session.dir / "steps.html"
    path.write_text("".join(out), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# PDF (reportlab, pure Python)
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


def _pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for reg, bold in _FONT_CANDIDATES:
        if Path(reg).exists() and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont("SR", reg))
                pdfmetrics.registerFont(TTFont("SR-B", bold))
                pdfmetrics.registerFontFamily("SR", normal="SR", bold="SR-B", italic="SR", boldItalic="SR-B")
                return "SR", "SR-B", True
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold", False


def write_pdf(session, tpl):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    font, bold, unicode_ok = _pdf_fonts()

    def T(s):  # text safe for the chosen font
        s = escape(clean_text(s))
        if not unicode_ok:
            s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\n", "<br/>")

    accent = colors.HexColor(tpl.accent or "#1e88e5")
    base = ParagraphStyle("b", fontName=font, fontSize=10.5, leading=14)
    st_title = ParagraphStyle("t", parent=base, fontName=bold, fontSize=22, leading=26, spaceAfter=4)
    st_sub = ParagraphStyle("s", parent=base, textColor=colors.HexColor("#667788"), fontSize=9, spaceAfter=12)
    st_sec = ParagraphStyle("sec", parent=base, fontName=bold, fontSize=15, leading=19, spaceBefore=14, spaceAfter=6)
    st_step = ParagraphStyle("st", parent=base, fontName=bold, fontSize=8.5, textColor=accent, spaceBefore=12)
    st_cap = ParagraphStyle("c", parent=base, fontName=bold, fontSize=12, leading=15)
    st_meta = ParagraphStyle("m", parent=base, fontSize=8, textColor=colors.HexColor("#778899"))
    st_lbl = ParagraphStyle("l", parent=base, fontSize=8, textColor=colors.HexColor("#778899"), spaceBefore=4)

    page_w, page_h = A4
    margin = 18 * mm
    avail_w, avail_h = page_w - 2 * margin, page_h - 2 * margin - 30

    def picture(rel):
        p = session.dir / rel
        with Image.open(p) as im:
            w, h = im.size
        k = min(avail_w / w, avail_h * 0.75 / h)
        return RLImage(str(p), width=w * k, height=h * k)

    story = [Paragraph(T(session.title), st_title), Paragraph(T(_subtitle(session, tpl)), st_sub)]
    for b in build_blocks(session, tpl):
        if b["type"] == "section":
            story.append(Paragraph(T(b["text"]), st_sec))
        elif b["type"] == "callout":
            label, fill, acc = CALLOUT[b["level"]]
            para = Paragraph(f"<font name='{bold}' color='#{acc}'>{label}:</font> {T(b['text'].strip())}", base)
            tbl = Table([[para]], colWidths=[avail_w])
            tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + fill)),
                                     ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#" + acc)),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            story += [Spacer(1, 6), tbl, Spacer(1, 6)]
        else:
            part = [Paragraph(f"STEP {b['n']}", st_step), Paragraph(T(b["text"]), st_cap)]
            if b["meta"]:
                part.append(Paragraph(T(b["meta"]), st_meta))
            if b["dialog"]:
                part.append(Paragraph("<i>Dialog text:</i> " + T(b["dialog"]), base))
            first = True
            for label, rel in b["images"]:
                if label:
                    part.append(Paragraph(T(label), st_lbl))
                part += [Spacer(1, 3), picture(rel)]
                if first:
                    story.append(KeepTogether(part))
                    part, first = [], False
                else:
                    story.append(KeepTogether(part))
                    part = []
            if part:
                story.append(KeepTogether(part))
    if tpl.environment and session.environment:
        story.append(Paragraph("Environment", st_sec))
        rows = [[Paragraph(T(k), st_meta), Paragraph(T(str(v)), base)] for k, v in session.environment.items()]
        tbl = Table(rows, colWidths=[avail_w * 0.3, avail_w * 0.7])
        tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ccccdd")),
                                 ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(tbl)

    logo = tpl.logo if tpl.logo and Path(tpl.logo).exists() else None

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#778899"))
        x = margin
        if logo:
            try:
                canvas.drawImage(logo, x, page_h - margin + 2, height=9 * mm, preserveAspectRatio=True, mask="auto")
                x += 28 * mm
            except Exception:
                pass
        if tpl.header:
            canvas.drawString(x, page_h - margin + 8, T(tpl.header).replace("<br/>", " ")[:110]
                              .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
        foot = (T(tpl.footer).replace("<br/>", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                + "    ") if tpl.footer else ""
        canvas.drawString(margin, margin - 12, foot + f"Page {doc.page}")
        canvas.restoreState()

    path = session.dir / "steps.pdf"
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin + 4,
                      bottomMargin=margin, title=clean_text(session.title)).build(
        story, onFirstPage=decorate, onLaterPages=decorate)
    return path


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
WRITERS = {"md": write_markdown, "docx": write_docx, "html": write_html, "pdf": write_pdf, "txt": write_text}


def export(session, tpl, formats):
    """Write the requested formats.  Returns {format: path-string | 'FAILED: ...'}; one failing format
    never stops the others (details go to save_errors.log)."""
    session.settings["wording"] = tpl.wording
    session.settings["template"] = tpl.to_dict()
    results, trace = {}, []
    try:
        render_images(session)
    except Exception as e:
        results["images"] = f"FAILED: {type(e).__name__}: {e}"
        trace.append("images\n" + traceback.format_exc())
    session.save()
    if session.environment:
        try:
            (session.dir / "environment.txt").write_text(environment_text(session.environment, session.title),
                                                         encoding="utf-8")
        except OSError:
            pass
    for fmt in formats:
        w = WRITERS.get(fmt)
        if not w:
            results[fmt] = "FAILED: unknown format"
            continue
        try:
            results[fmt] = str(w(session, tpl))
        except Exception as e:
            results[fmt] = f"FAILED: {type(e).__name__}: {e}"
            trace.append(f"{fmt}\n{traceback.format_exc()}")
    log = session.dir / "save_errors.log"
    if trace:
        try:
            log.write_text(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\n\n" + "\n".join(trace), encoding="utf-8")
        except OSError:
            pass
    return results
