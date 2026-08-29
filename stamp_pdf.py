"""
Apply MOZA cambial stamp to FNB import document bundles.

Uses the official scanned stamp from test file.pdf (image overlay + filled text).
Stamps Tax Invoice and Documento Único pages.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Default paths relative to this script
ROOT = Path(__file__).resolve().parent
DEFAULT_STAMP_SOURCE = ROOT / "test file.pdf"
STAMP_TEMPLATE = ROOT / "assets" / "stamp_template.png"

# Measured ink size of the original stamp on test file.pdf: 231.95 x 75.99 pt.
# stamp_template.png also contains paper margins, so stamp_rect_size() measures the
# ink fraction once and widens the placed rect so the VISIBLE stamp = 231.95 pt exactly.
STAMP_INK_WIDTH_PT = 231.95
MARGIN = 14.0
DU_DROP_SHARE = 1.10  # DU stamp lowered by 110% of its visible height (30%+30%+50%)
POR_SUFFIX = " EUR"
SALDO_TEXT = "0,00 EUR"

TEXT_POS = {
    "d1": (0.538, 0.103),
    "d2": (0.633, 0.103),
    "d3": (0.724, 0.103),
    "por": (0.656, 0.210),
    "saldo": (0.28, 0.285),
}


@dataclass
class TermoData:
    valor_termo: float | None = None
    valor_factura: float | None = None
    ucr: str | None = None
    invoice_ref: str | None = None
    ref_termo: str | None = None
    raw_valor_por: str | None = None


@dataclass
class ValidationReport:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append((name, ok, detail))

    def print_report(self) -> None:
        print("\n--- Validation ---")
        for name, ok, detail in self.checks:
            mark = "OK" if ok else "WARN"
            print(f"  [{mark}] {name}: {detail}")


def _parse_amount(text: str) -> float | None:
    if not text:
        return None
    cleaned = text.strip().replace("\xa0", " ")
    cleaned = re.sub(r"\s*EUR\s*$", "", cleaned, flags=re.I).strip()
    cleaned = cleaned.replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def format_pt_amount(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def today_pt() -> str:
    d = date.today()
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def ensure_stamp_template(source_pdf: Path = DEFAULT_STAMP_SOURCE) -> Path:
    """Extract blank stamp image from test file.pdf if not already cached."""
    STAMP_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    if STAMP_TEMPLATE.exists():
        return STAMP_TEMPLATE

    if not source_pdf.exists():
        raise FileNotFoundError(
            f"Stamp source not found: {source_pdf}. Place test file.pdf in project root."
        )

    doc = fitz.open(source_pdf)
    page = doc[0]
    imgs = page.get_images(full=True)
    if not imgs:
        doc.close()
        raise ValueError(f"No stamp image in {source_pdf}")

    bi = doc.extract_image(imgs[0][0])
    doc.close()

    full = Image.open(io.BytesIO(bi["image"])).convert("RGBA")
    arr = np.array(full.convert("L"))
    h, w = arr.shape
    mask = arr[int(h * 0.4) :, :] < 240
    ys, xs = np.where(mask)
    y0 = int(h * 0.4) + int(ys.min()) - 5
    y1 = int(h * 0.4) + int(ys.max()) + 5
    x0 = max(0, int(xs.min()) - 5)
    x1 = min(w, int(xs.max()) + 5)
    stamp = full.crop((x0, y0, x1, y1))
    # Trim below stamp box (MOZA logo sits inside; drop extra scan margin)
    stamp = stamp.crop((0, 0, stamp.width, int(stamp.height * 0.62)))
    stamp.save(STAMP_TEMPLATE)
    return STAMP_TEMPLATE


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_filled_stamp(
    stamp_date: str,
    por_display: str,
    saldo: str = SALDO_TEXT,
) -> tuple[bytes, float, float]:
    """Return PNG bytes, aspect width/height for placement."""
    template_path = ensure_stamp_template()
    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    parts = stamp_date.split("/")
    d1, d2, d3 = (parts[0] if len(parts) > 0 else "", parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "")
    por_text = f"{por_display}{POR_SUFFIX}"
    base_size = max(22, int(h * 0.038) + 6)
    fonts = {
        "d1": _load_font(base_size),
        "d2": _load_font(base_size),
        "d3": _load_font(base_size),
        "por": _load_font(base_size),
        "saldo": _load_font(base_size),
    }

    for key, text in (("d1", d1), ("d2", d2), ("d3", d3), ("por", por_text), ("saldo", saldo)):
        fx, fy = TEXT_POS[key]
        draw.text((int(w * fx), int(h * fy)), text, fill=(0, 0, 0, 255), font=fonts[key], anchor="mm")

    # White background -> transparent so stamp overlays without blocking content
    data = img.getdata()
    transparent = []
    for r, g, b, a in data:
        if r >= 235 and g >= 235 and b >= 235:
            transparent.append((255, 255, 255, 0))
        else:
            transparent.append((r, g, b, a))
    img.putdata(transparent)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), w / h


def extract_termo_data(text: str) -> TermoData:
    data = TermoData()

    m = re.search(
        r"N[ºo°]\s*de\s*Ref\.?\s*do\s*Termo\s*de\s*Compromisso\s+(\S+)",
        text,
        re.I,
    )
    if m:
        data.ref_termo = m.group(1).strip()

    m = re.search(
        r"Valor\s+do\s+Termo\s+de\s+Compromisso\s+([\d.,]+)\s*EUR",
        text,
        re.I,
    )
    if m:
        data.raw_valor_por = m.group(1).strip()
        data.valor_termo = _parse_amount(m.group(1))

    m = re.search(r"Valor\s+da\s+Factura\s+([\d.,]+)\s*EUR", text, re.I)
    if m:
        data.valor_factura = _parse_amount(m.group(1))

    m = re.search(
        r"N[úu]mero\s+[ÚU]nico\s+por\s+Consigna[çc][ãa]o\s+\(UCR\)\s+(\S+)",
        text,
        re.I,
    )
    if m:
        data.ucr = m.group(1).strip()

    m = re.search(r"INVOICE:\s*(\S+)", text, re.I)
    if m:
        data.invoice_ref = m.group(1).strip()

    return data


def extract_ucr_from_du(text: str) -> str | None:
    patterns = [
        r"consignanco\s*\(UCR\)\s*:?\s*(\S+)",
        r"consignação\s*\(UCR\)\s*:?\s*(\S+)",
        r"Numero unico de consigna\S*\s*\(UCR\)\s*:?\s*(\S+)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1).strip()
    m = re.search(r"0MZ\d+", text)
    return m.group(0) if m else None


def extract_invoice_total(text: str) -> float | None:
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if re.search(r"Total\s+EUR", line, re.I):
            for j in range(i - 1, max(0, i - 20), -1):
                if re.fullmatch(r"[\d.,]+", lines[j]):
                    v = _parse_amount(lines[j])
                    if v is not None and v > 0:
                        return v
    for i, line in enumerate(lines):
        if "Final IncoTerm" in line or "INCOTERMS" in line:
            for j in range(i - 1, max(0, i - 8), -1):
                if re.fullmatch(r"[\d.,]+", lines[j]):
                    v = _parse_amount(lines[j])
                    if v is not None and v > 0:
                        return v
    return None


def extract_invoice_number(text: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if line == "Invoice Number":
            for j in range(i + 1, min(len(lines), i + 20)):
                if re.fullmatch(r"\d{4,10}", lines[j]):
                    return lines[j]
    m = re.search(r"INVOICE:\s*(\S+)", text, re.I)
    return m.group(1).strip() if m else None


def find_page_by_marker(doc: fitz.Document, markers: list[str]) -> int | None:
    for i, page in enumerate(doc):
        text = page.get_text()
        if any(m.lower() in text.lower() for m in markers):
            return i
    return None


def find_all_pages_by_marker(doc: fitz.Document, markers: list[str]) -> list[int]:
    out = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if any(m.lower() in text.lower() for m in markers):
            out.append(i)
    return out


def find_du_pages(doc: fitz.Document) -> list[int]:
    all_du = find_all_pages_by_marker(doc, ["DOCUMENTO ÚNICO", "DOCUMENTO UNICO"])
    filtered = []
    for idx in all_du:
        text = doc[idx].get_text()
        if "Continuação" in text or "Continuacao" in text:
            continue
        filtered.append(idx)
    return filtered


# --- Fallback: date-only stamping when full automation lacks detail ---
# The Termo is identified by details that ONLY it has, mainly the full statement
# "Termo de Compromisso de Intermediação Bancária para a Importação de Bens".
import unicodedata


def _fold_text(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("\ufffd", " ").lower()


TERMO_LIBERAL_SIGNALS = (
    "termo de compromisso de intermediacao bancaria para a importacao de bens",
    "intermediacao bancaria",
    "importacao de bens",
    "termo de compromisso",
    "compromisso",
)


def find_termo_pages(doc: fitz.Document) -> list[int]:
    """Termo lookup: strict marker first, then liberal scan for termo-only details."""
    strict = find_all_pages_by_marker(doc, ["Termo de Compromisso"])
    if strict:
        return strict
    out = []
    for i, page in enumerate(doc):
        low = _fold_text(page.get_text())
        if any(s in low for s in TERMO_LIBERAL_SIGNALS):
            out.append(i)
    return sorted(out)


def build_date_stamp(stamp_date: str) -> tuple[bytes, float]:
    """Stamp with today's date filled only (POR/SALDO left for manual fill)."""
    template_path = ensure_stamp_template()
    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    parts = stamp_date.split("/")
    d1 = parts[0] if len(parts) > 0 else ""
    d2 = parts[1] if len(parts) > 1 else ""
    d3 = parts[2] if len(parts) > 2 else ""
    base_size = max(22, int(h * 0.038) + 6)
    font = _load_font(base_size)
    for key, text in (("d1", d1), ("d2", d2), ("d3", d3)):
        fx, fy = TEXT_POS[key]
        draw.text((int(w * fx), int(h * fy)), text, fill=(0, 0, 0, 255), font=font, anchor="mm")
    data = img.getdata()
    trans = []
    for r, g, b, a in data:
        if r >= 235 and g >= 235 and b >= 235:
            trans.append((255, 255, 255, 0))
        else:
            trans.append((r, g, b, a))
    img.putdata(trans)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), w / h


def find_du_continuation_pages(doc: fitz.Document) -> list[int]:
    """DU continuation sheets ('Documento Único (Continuação)') — never stamped."""
    out = []
    for idx in find_all_pages_by_marker(doc, ["DOCUMENTO ÚNICO", "DOCUMENTO UNICO"]):
        if "continuacao" in _fold_text(doc[idx].get_text()):
            out.append(idx)
    return out


def classify_pages(
    doc: fitz.Document,
    termo_indices: list[int],
    invoice_indices: list[int],
    du_indices: list[int],
) -> list[tuple[int, str]]:
    """Each page -> skip | invoice | du | unknown (Termo + DU continuations are never stamped)."""
    termo = set(termo_indices)
    inv = set(invoice_indices)
    du = set(du_indices)
    cont = set(find_du_continuation_pages(doc))
    plan = []
    for idx in range(len(doc)):
        if idx in termo or idx in cont:
            plan.append((idx, "skip"))
        elif idx in inv:
            plan.append((idx, "invoice"))
        elif idx in du:
            plan.append((idx, "du"))
        else:
            plan.append((idx, "unknown"))
    return plan


def apply_date_fallback(
    doc: fitz.Document,
    output_path: Path,
    termo_indices: list[int],
    invoice_indices: list[int],
    du_indices: list[int],
    stamp_date: str,
    dry_run: bool,
) -> tuple[ValidationReport, list[tuple[int, str, tuple]]]:
    """Date-only stamp on every page EXCEPT the Termo and DU continuations.

    Unknown pages get the invoice placement so nothing real is missed. Raises
    ValueError if the Termo can't be identified even with the liberal search.
    """
    report = ValidationReport()
    termo_pages = termo_indices or find_termo_pages(doc)
    if not termo_pages:
        raise ValueError(
            "Full automation unavailable AND Termo page not found even with liberal "
            "search. Skipped without stamping (refusing to stamp an unidentified Termo)."
        )
    png_bytes, aspect = build_date_stamp(stamp_date)
    stamp_w, stamp_h = stamp_rect_size(aspect)
    stamped = []
    for idx, kind in classify_pages(doc, termo_pages, invoice_indices, du_indices):
        if kind == "skip":
            continue
        place_kind = "invoice" if kind == "unknown" else kind
        rect = example_draft_rect(doc[idx], stamp_w, stamp_h, place_kind)
        if not dry_run:
            place_stamp(doc[idx], rect, png_bytes)
        stamped.append((idx + 1, place_kind, tuple(round(v, 1) for v in rect)))
    if not dry_run:
        doc.save(output_path, garbage=4, deflate=True)
    report.add(
        "FALLBACK (full automation unavailable)",
        True,
        f"date-only stamp on {len(stamped)} page(s); Termo page(s) "
        f"{[p + 1 for p in termo_pages]} and DU continuations NOT stamped; POR/SALDO left for manual fill",
    )
    return report, stamped


def apply_por_fallback(
    doc: fitz.Document,
    output_path: Path,
    termo_pages: list[int],
    invoice_indices: list[int],
    du_indices: list[int],
    por_display: str,
    termo_ucr: str | None,
    stamp_date: str,
    dry_run: bool,
) -> tuple[ValidationReport, list[tuple[int, str, tuple]]] | None:
    """POR known: fill the FULL stamp (POR + SALDO 0,00) on identified pages only.

    Stamps ALL invoices + the FIRST relevant DU (UCR-matched when possible).
    DU continuations and unknown pages are never stamped here. Returns None when
    no identified page exists so the caller can degrade to date-only.
    """
    png_bytes, aspect = build_filled_stamp(stamp_date, por_display)
    stamp_w, stamp_h = stamp_rect_size(aspect)
    main_du = select_du_by_ucr(doc, sorted(du_indices), termo_ucr) if du_indices else None
    stamped = []
    for idx, kind in classify_pages(doc, termo_pages, invoice_indices, du_indices):
        if kind == "invoice":
            rect = example_draft_rect(doc[idx], stamp_w, stamp_h, "invoice")
            if not dry_run:
                place_stamp(doc[idx], rect, png_bytes)
            stamped.append((idx + 1, "invoice", tuple(round(v, 1) for v in rect)))
        elif kind == "du" and idx == main_du:
            rect = example_draft_rect(doc[idx], stamp_w, stamp_h, "du")
            if not dry_run:
                place_stamp(doc[idx], rect, png_bytes)
            stamped.append((idx + 1, "du", tuple(round(v, 1) for v in rect)))
    if not stamped:
        return None
    if not dry_run:
        doc.save(output_path, garbage=4, deflate=True)
    report = ValidationReport()
    report.add(
        "FALLBACK-POR (partial automation)",
        True,
        f"full stamp (POR {por_display}{POR_SUFFIX}, SALDO {SALDO_TEXT}) on {len(stamped)} "
        f"identified page(s); Termo p{[p + 1 for p in termo_pages]} and DU "
        f"continuations/unknown pages NOT stamped",
    )
    return report, stamped


def apply_auto_fallback(
    doc: fitz.Document,
    output_path: Path,
    termo_indices: list[int],
    invoice_indices: list[int],
    du_indices: list[int],
    stamp_date: str,
    dry_run: bool,
) -> ValidationReport:
    """Most automated safe fallback: POR-fill if possible, else date-only."""
    report = ValidationReport()
    termo_pages = termo_indices or find_termo_pages(doc)
    if not termo_pages:
        raise ValueError(
            "Full automation unavailable AND Termo page not found even with liberal "
            "search. Skipped without stamping (refusing to stamp an unidentified Termo)."
        )
    missing = []
    if not termo_indices:
        missing.append("Termo (strict marker)")
    if not invoice_indices:
        missing.append("Tax Invoice")
    if not du_indices:
        missing.append("Documento Único")
    termo = extract_termo_data(doc[termo_pages[0]].get_text())
    if termo.valor_termo is not None:
        por_display = format_pt_amount(termo.valor_termo)
        got = apply_por_fallback(
            doc, output_path, termo_pages, invoice_indices, du_indices,
            por_display, termo.ucr, stamp_date, dry_run,
        )
        if got is not None:
            fb_report, stamped = got
            print(f"FALLBACK-POR — missing {', '.join(missing) or 'none (strict markers only)'}; "
                  f"POR found in Termo => full stamp")
            print(f"POR (from Termo p{termo_pages[0] + 1}): {por_display}{POR_SUFFIX} | SALDO: {SALDO_TEXT}")
            for pno, kind, r in stamped:
                print(f"  p{pno} [{kind}] full: {r}")
            if not dry_run:
                print(f"Saved: {output_path}")
            fb_report.print_report()
            return fb_report
    report, stamped = apply_date_fallback(
        doc, output_path, termo_pages, invoice_indices, du_indices, stamp_date, dry_run,
    )
    print(f"FALLBACK — missing {', '.join(missing) or 'none (strict markers only)'}; "
          f"POR not extractable => date-only stamp (POR/SALDO left blank for manual fill)")
    for pno, kind, r in stamped:
        print(f"  p{pno} [{kind}] date-only: {r}")
    if not dry_run:
        print(f"Saved: {output_path}")
    report.print_report()
    return report


def select_du_by_ucr(doc: fitz.Document, du_indices: list[int], termo_ucr: str | None) -> int:
    if not du_indices:
        raise ValueError("No DU pages")
    if not termo_ucr:
        return du_indices[0]
    for idx in du_indices:
        ucr = extract_ucr_from_du(doc[idx].get_text())
        if ucr and ucr.upper() == termo_ucr.upper():
            return idx
    return du_indices[0]


def page_occupied_rects(page: fitz.Page, y_min_ratio: float = 0.0) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    y_min = page.rect.height * y_min_ratio
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 0:
            r = fitz.Rect(b["bbox"])
            if r.y1 >= y_min:
                rects.append(r)
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            if r.y1 >= y_min:
                rects.append(r)
    return rects


_stamp_ink_fraction: float | None = None
_stamp_ink_height_fraction: float | None = None


def _measure_template_ink() -> None:
    global _stamp_ink_fraction, _stamp_ink_height_fraction
    ensure_stamp_template()
    img = Image.open(STAMP_TEMPLATE).convert("L")
    arr = np.asarray(img)
    m = arr < 240
    cols = m.any(axis=0)
    rows = m.any(axis=1)
    xs = np.where(cols)[0]
    ys = np.where(rows)[0]
    ink_w = (xs.max() - xs.min() + 1) if len(xs) else img.width
    ink_h = (ys.max() - ys.min() + 1) if len(ys) else img.height
    _stamp_ink_fraction = ink_w / img.width
    _stamp_ink_height_fraction = ink_h / img.height


def stamp_ink_fraction() -> float:
    """Fraction of template pixel width that is actual stamp ink (measured once)."""
    if _stamp_ink_fraction is None:
        _measure_template_ink()
    return _stamp_ink_fraction


def stamp_ink_height_fraction() -> float:
    """Fraction of template pixel height that is actual stamp ink (measured once)."""
    if _stamp_ink_height_fraction is None:
        _measure_template_ink()
    return _stamp_ink_height_fraction


def stamp_rect_size(aspect: float) -> tuple[float, float]:
    """Full placement rect so that the visible ink matches STAMP_INK_WIDTH_PT."""
    w = STAMP_INK_WIDTH_PT / stamp_ink_fraction()
    h = w / aspect
    return w, h


def example_draft_rect(page: fitz.Page, stamp_w: float, stamp_h: float, kind: str) -> fitz.Rect:
    pw, ph = page.rect.width, page.rect.height
    if kind == "invoice":
        x0_src, y0_src = 413.47601318359375, 651.22900390625
    else:
        x0_src, y0_src = 394.1820068359375, 781.4244995117188
    scale_x = pw / 595.0
    scale_y = ph / 842.0
    x0 = x0_src * scale_x
    y0 = y0_src * scale_y
    x0 = min(max(MARGIN, x0), pw - MARGIN - stamp_w)
    y0 = min(max(MARGIN, y0), ph - MARGIN - stamp_h)
    if kind != "invoice":
        # DU stamp lowered by DU_DROP_SHARE of its own visible (ink) height.
        ink_h = stamp_h * stamp_ink_height_fraction()
        y0 += DU_DROP_SHARE * ink_h
        y0 = min(y0, ph - MARGIN - ink_h)
    return fitz.Rect(x0, y0, x0 + stamp_w, y0 + stamp_h)


def find_least_text_rect(page: fitz.Page, stamp_w: float, stamp_h: float) -> fitz.Rect:
    pw, ph = page.rect.width, page.rect.height
    occupied = page_occupied_rects(page, y_min_ratio=0.30)

    best: fitz.Rect | None = None
    best_overlap = float("inf")
    step = 8.0
    y = ph * 0.30
    while y + stamp_h <= ph - MARGIN:
        x = MARGIN
        while x + stamp_w <= pw - MARGIN:
            rect = fitz.Rect(x, y, x + stamp_w, y + stamp_h)
            overlap = 0.0
            for o in occupied:
                inter = rect & o
                if not inter.is_empty:
                    overlap += inter.get_area()
            if overlap < best_overlap:
                best_overlap = overlap
                best = rect
            x += step
        y += step

    stamp_area = stamp_w * stamp_h
    if best is None or best_overlap > stamp_area * 0.45:
        return example_draft_rect(page, stamp_w, stamp_h, "invoice")
    return best


def place_stamp(page: fitz.Page, rect: fitz.Rect, png_bytes: bytes) -> None:
    page.insert_image(rect, stream=png_bytes, overlay=True)


def validate_bundle(
    termo: TermoData,
    du_text: str,
    invoice_text: str,
    report: ValidationReport,
) -> str:
    por = termo.raw_valor_por
    if termo.valor_termo is not None:
        por = format_pt_amount(termo.valor_termo)
    elif por:
        v = _parse_amount(por)
        if v is not None:
            por = format_pt_amount(v)
    else:
        por = "0,00"

    report.add(
        "Valor Termo",
        termo.valor_termo is not None,
        por if termo.valor_termo is not None else "Could not extract Valor do Termo de Compromisso",
    )

    du_ucr = extract_ucr_from_du(du_text)
    if termo.ucr and du_ucr:
        report.add("UCR Termo vs DU", termo.ucr.upper() == du_ucr.upper(), f"Termo={termo.ucr} | DU={du_ucr}")
    else:
        report.add("UCR Termo vs DU", False, f"Termo UCR={termo.ucr or '?'} | DU UCR={du_ucr or '?'}")

    inv_total = extract_invoice_total(invoice_text)
    if termo.valor_termo is not None and inv_total is not None:
        diff = abs(termo.valor_termo - inv_total)
        ok = diff < 0.02 or diff / termo.valor_termo < 0.001
        report.add(
            "Invoice Total vs Termo Valor",
            ok,
            f"Invoice={format_pt_amount(inv_total)} | Termo={por} (diff={diff:.2f})",
        )
    else:
        report.add("Invoice Total vs Termo Valor", False, f"Invoice total={inv_total} | Termo={termo.valor_termo}")

    if termo.valor_factura is not None and termo.valor_termo is not None:
        ok = abs(termo.valor_factura - termo.valor_termo) < 0.02
        report.add(
            "Valor Factura vs Valor Termo (same page)",
            ok,
            f"Factura={format_pt_amount(termo.valor_factura)} | Termo={por}",
        )

    inv_no = extract_invoice_number(invoice_text)
    if termo.invoice_ref and inv_no:
        report.add(
            "Invoice Ref Termo vs Tax Invoice No",
            termo.invoice_ref.strip() == inv_no.strip(),
            f"Termo INVOICE={termo.invoice_ref} | Invoice={inv_no}",
        )
    elif termo.invoice_ref or inv_no:
        report.add(
            "Invoice Ref Termo vs Tax Invoice No",
            False,
            f"Termo INVOICE={termo.invoice_ref or '?'} | Invoice={inv_no or '?'}",
        )

    return por


def apply_stamps(
    input_path: Path,
    output_path: Path | None = None,
    *,
    stamp_date: str | None = None,
    stamp_source: Path = DEFAULT_STAMP_SOURCE,
    dry_run: bool = False,
) -> ValidationReport:
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_name(input_path.stem + "_stamped.pdf")

    ensure_stamp_template(stamp_source)
    stamp_date = stamp_date or today_pt()
    report = ValidationReport()

    doc = fitz.open(input_path)
    termo_indices = find_all_pages_by_marker(doc, ["Termo de Compromisso"])
    invoice_indices = find_all_pages_by_marker(doc, ["Tax Invoice", "Commercial Invoice"])
    du_indices_all = find_du_pages(doc)

    if not (termo_indices and invoice_indices and du_indices_all):
        print(f"Input:  {input_path}")
        print(f"Output: {output_path}")
        print(f"Date:   {stamp_date}")
        report = apply_auto_fallback(doc, output_path, termo_indices, invoice_indices, du_indices_all, stamp_date, dry_run)
        doc.close()
        report.print_report()
        return report

    termo = extract_termo_data(doc[termo_indices[0]].get_text())
    termo.page_idx = termo_indices[0]
    du_idx = select_du_by_ucr(doc, du_indices_all, termo.ucr)
    por_display = validate_bundle(
        termo, doc[du_idx].get_text(), doc[invoice_indices[0]].get_text(), report
    )

    png_bytes, aspect = build_filled_stamp(stamp_date, por_display)
    stamp_w, stamp_h = stamp_rect_size(aspect)

    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"Stamp:  {STAMP_TEMPLATE}")
    print(f"Date:   {stamp_date} (today, page-agnostic)")
    print(f"POR (from Termo p{termo_indices[0]+1}): {por_display}{POR_SUFFIX}")
    print(f"SALDO:  {SALDO_TEXT}")
    print(f"Termo pages: {[i+1 for i in termo_indices]} UCR={termo.ucr}")
    print(f"Invoices: {[i+1 for i in invoice_indices]} -> ALL stamped")
    print(f"DU pages: {[i+1 for i in du_indices_all]} -> ONLY FIRST matched {du_idx+1} stamped")

    if not dry_run:
        for idx in invoice_indices:
            rect = example_draft_rect(doc[idx], stamp_w, stamp_h, "invoice")
            place_stamp(doc[idx], rect, png_bytes)
            print(f"  Invoice p{idx+1}: {tuple(round(v,1) for v in rect)}")
        rect = example_draft_rect(doc[du_idx], stamp_w, stamp_h, "du")
        place_stamp(doc[du_idx], rect, png_bytes)
        print(f"  DU p{du_idx+1}: {tuple(round(v,1) for v in rect)}")
        doc.save(output_path, garbage=4, deflate=True)
        print(f"\nSaved: {output_path}")

    doc.close()
    report.print_report()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply official MOZA stamp image to FNB import PDF bundles."
    )
    parser.add_argument("input", type=Path, help="Input PDF path")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output PDF path")
    parser.add_argument("--date", default=None, help="Stamp date DD/MM/YYYY (default: today)")
    parser.add_argument(
        "--stamp-source",
        type=Path,
        default=DEFAULT_STAMP_SOURCE,
        help="PDF containing blank stamp scan (default: test file.pdf)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write PDF")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        apply_stamps(
            args.input,
            args.output,
            stamp_date=args.date,
            stamp_source=args.stamp_source,
            dry_run=args.dry_run,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
