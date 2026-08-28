from __future__ import annotations
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAMP_SOURCE = ROOT / "test file.pdf"
STAMP_TEMPLATE = ROOT / "assets" / "stamp_template.png"

STAMP_WIDTH_PT = 220.0
MARGIN = 14.0
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
    page_idx: int = -1

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
    STAMP_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    if STAMP_TEMPLATE.exists():
        return STAMP_TEMPLATE
    if not source_pdf.exists():
        raise FileNotFoundError(f"Stamp source not found: {source_pdf}")
    doc = fitz.open(source_pdf)
    page = doc[0]
    imgs = page.get_images(full=True)
    if not imgs:
        doc.close()
        raise ValueError(f"No stamp image in {source_pdf}")
    bi = doc.extract_image(imgs[0][0])
    doc.close()
    full = Image.open(io.BytesIO(bi["image"])).convert("RGBA")
    import numpy as np
    arr = np.array(full.convert("L"))
    h, w = arr.shape
    mask = arr[int(h * 0.4) :, :] < 240
    ys, xs = np.where(mask)
    y0 = int(h * 0.4) + int(ys.min()) - 5
    y1 = int(h * 0.4) + int(ys.max()) + 5
    x0 = max(0, int(xs.min()) - 5)
    x1 = min(w, int(xs.max()) + 5)
    stamp = full.crop((x0, y0, x1, y1))
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

def extract_termo_data(text: str) -> TermoData:
    data = TermoData()
    m = re.search(r"N[ºo°]\s*de\s*Ref\.?\s*do\s*Termo\s*de\s*Compromisso\s+(\S+)", text, re.I)
    if m:
        data.ref_termo = m.group(1).strip()
    m = re.search(r"Valor\s+do\s+Termo\s+de\s+Compromisso\s+([\d.,]+)\s*EUR", text, re.I)
    if m:
        data.raw_valor_por = m.group(1).strip()
        data.valor_termo = _parse_amount(m.group(1))
    m = re.search(r"Valor\s+da\s+Factura\s+([\d.,]+)\s*EUR", text, re.I)
    if m:
        data.valor_factura = _parse_amount(m.group(1))
    m = re.search(r"N[úu]mero\s+[ÚU]nico\s+por\s+Consigna[çc][ãa]o\s+\(UCR\)\s+(\S+)", text, re.I)
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

def stamp_rect_size(aspect: float) -> tuple[float, float]:
    w = STAMP_WIDTH_PT
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
    return fitz.Rect(x0, y0, x0 + stamp_w, y0 + stamp_h)

def place_stamp(page: fitz.Page, rect: fitz.Rect, png_bytes: bytes) -> None:
    page.insert_image(rect, stream=png_bytes, overlay=True)

def validate_bundle(termo: TermoData, du_text: str, invoice_text: str, report: ValidationReport) -> str:
    por = termo.raw_valor_por
    if termo.valor_termo is not None:
        por = format_pt_amount(termo.valor_termo)
    elif por:
        v = _parse_amount(por)
        if v is not None:
            por = format_pt_amount(v)
    else:
        por = "0,00"
    report.add("Valor Termo", termo.valor_termo is not None, por if termo.valor_termo is not None else "Could not extract Valor do Termo de Compromisso")
    du_ucr = extract_ucr_from_du(du_text)
    if termo.ucr and du_ucr:
        report.add("UCR Termo vs DU", termo.ucr.upper() == du_ucr.upper(), f"Termo={termo.ucr} | DU={du_ucr}")
    else:
        report.add("UCR Termo vs DU", False, f"Termo UCR={termo.ucr or '?'} | DU UCR={du_ucr or '?'}")
    inv_total = extract_invoice_total(invoice_text)
    if termo.valor_termo is not None and inv_total is not None:
        diff = abs(termo.valor_termo - inv_total)
        ok = diff < 0.02 or diff / termo.valor_termo < 0.001
        report.add("Invoice Total vs Termo Valor", ok, f"Invoice={format_pt_amount(inv_total)} | Termo={por} (diff={diff:.2f})")
    else:
        report.add("Invoice Total vs Termo Valor", False, f"Invoice total={inv_total} | Termo={termo.valor_termo}")
    if termo.valor_factura is not None and termo.valor_termo is not None:
        ok = abs(termo.valor_factura - termo.valor_termo) < 0.02
        report.add("Valor Factura vs Valor Termo (same page)", ok, f"Factura={format_pt_amount(termo.valor_factura)} | Termo={por}")
    inv_no = extract_invoice_number(invoice_text)
    if termo.invoice_ref and inv_no:
        report.add("Invoice Ref Termo vs Tax Invoice No", termo.invoice_ref.strip() == inv_no.strip(), f"Termo INVOICE={termo.invoice_ref} | Invoice={inv_no}")
    elif termo.invoice_ref or inv_no:
        report.add("Invoice Ref Termo vs Tax Invoice No", False, f"Termo INVOICE={termo.invoice_ref or '?'} | Invoice={inv_no or '?'}")
    return por
