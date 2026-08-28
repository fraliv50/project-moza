from __future__ import annotations
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
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

def extract_invoice_date(text: str) -> str | None:
    """Invoice date as YYYYMMDD, from the 'Invoice Date' field (falls back to first month-name date)."""
    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
        "nov": "11", "dec": "12",
    }
    pat = r"(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})"
    best = None
    for m in re.finditer(pat, text):
        key = m.group("mon").lower()[:3]
        if key not in months:
            continue
        iso = m.group("year") + months[key] + f"{int(m.group('day')):02d}"
        before = text[max(0, m.start() - 80):m.start()]
        if "invoice" in before.lower():
            return iso
        if best is None:
            best = iso
    return best

def extract_invoice_details(text: str) -> dict[str, float]:
    """Two-value awareness: goods sub-total (FCA), freight, and invoice total."""
    lines = [ln.strip() for ln in text.splitlines()]

    def around(i: int, steps: int = 6) -> float | None:
        for j in range(i + 1, min(len(lines), i + steps)):
            if re.fullmatch(r"[\d.,]+", lines[j]):
                v = _parse_amount(lines[j])
                if v is not None and v > 0:
                    return v
        for j in range(i - 1, max(0, i - steps), -1):
            if re.fullmatch(r"[\d.,]+", lines[j]):
                v = _parse_amount(lines[j])
                if v is not None and v > 0:
                    return v
        return None

    out: dict[str, float] = {"total": extract_invoice_total(text)}
    for i, line in enumerate(lines):
        if "goods" not in out and re.match(r"^FCA\b", line, re.I):
            out["goods"] = around(i)
        if "freight" not in out and re.match(r"^Air\s+Freight\b", line, re.I):
            out["freight"] = around(i)
    return out

@dataclass
class DuFinancials:
    ucr: str | None = None
    invoice_ref: str | None = None
    invoice_date: str | None = None
    fob: float | None = None
    freight: float | None = None
    insurance: float | None = None
    cif: float | None = None
    rate: float | None = None
    fob_mt: float | None = None
    freight_mt: float | None = None
    insurance_mt: float | None = None
    cif_mt: float | None = None

def extract_du_financials(text: str) -> DuFinancials:
    """Financial/factura block of the DU (fields 13A, 22, 23, 28, 24)."""
    fin = DuFinancials()
    fin.ucr = extract_ucr_from_du(text)
    m = re.search(r"N[ºo°]\s*E\s*DATA\s+DA\s+(?:FACTURA|FATURA)", text, re.I)
    if m:
        nums = re.findall(r"\d{4,14}", text[m.end():m.end() + 40])
        if nums:
            if len(nums) >= 2:
                fin.invoice_ref = nums[0]
                fin.invoice_date = nums[1] if len(nums[1]) == 8 else None
            else:
                n = nums[0]
                if len(n) >= 12:
                    fin.invoice_ref, fin.invoice_date = n[: len(n) - 8], n[-8:]
                else:
                    fin.invoice_ref = n
    lines = [ln.strip() for ln in text.splitlines()]

    def amt_pair(i: int, steps: int = 8) -> tuple[float | None, float | None]:
        got = []
        for j in range(i, min(len(lines), i + steps)):
            if re.fullmatch(r"[\d.,]+", lines[j]):
                v = _parse_amount(lines[j])
                if v is not None and v > 0:
                    got.append(v)
                    if len(got) == 2:
                        return got[0], got[1]
        return (got + [None, None])[:2]

    for i, line in enumerate(lines):
        key = line.upper()
        if key == "FOB" and fin.fob is None:
            fin.fob, fin.fob_mt = amt_pair(i + 1)
        elif key == "FRETE" and fin.freight is None:
            fin.freight, fin.freight_mt = amt_pair(i + 1)
        elif key == "SEGURO" and fin.insurance is None:
            fin.insurance, fin.insurance_mt = amt_pair(i + 1)
        elif key == "CIF" and fin.cif is None:
            fin.cif, fin.cif_mt = amt_pair(i + 1)
    m = re.search(r"TAXA\s+DE\s+C[ÂA]MBIO\s*\n?\s*([\d.,]+)", text, re.I)
    if m:
        fin.rate = _parse_amount(m.group(1))
    return fin

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

def apply_date_fallback(
    doc: fitz.Document,
    output_path: Path,
    termo_indices: list[int],
    invoice_indices: list[int],
    du_indices: list[int],
    stamp_date: str,
    dry_run: bool,
) -> tuple[ValidationReport, list[tuple[int, str, tuple]]]:
    """Best-effort fallback: stamp date-only on every page EXCEPT the Termo.

    The Termo is never stamped. If it can't be identified even with the liberal
    search, raises ValueError so the file is skipped instead of stamping unknowns.
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
    for idx in range(len(doc)):
        if idx in termo_pages:
            continue
        kind = "invoice" if idx in invoice_indices else ("du" if idx in du_indices else "invoice")
        rect = example_draft_rect(doc[idx], stamp_w, stamp_h, kind)
        if not dry_run:
            place_stamp(doc[idx], rect, png_bytes)
        stamped.append((idx + 1, kind, tuple(round(v, 1) for v in rect)))
    if not dry_run:
        doc.save(output_path, garbage=4, deflate=True)
    report.add(
        "FALLBACK (full automation unavailable)",
        True,
        f"date-only stamp on {len(stamped)} page(s); Termo page(s) "
        f"{[p + 1 for p in termo_pages]} NOT stamped; POR/SALDO left for manual fill",
    )
    return report, stamped

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

def place_stamp(page: fitz.Page, rect: fitz.Rect, png_bytes: bytes) -> None:
    page.insert_image(rect, stream=png_bytes, overlay=True)

def validate_triangle(termo: TermoData, du_text: str, invoice_text: str, report: ValidationReport) -> None:
    """3-way invoice-number triangle (Termo INVOICE <-> Tax Invoice <-> DU 13A)
    plus two-value amount cross-checks (DU FOB/Frete/CIF vs invoice lines)."""
    inv_no = extract_invoice_number(invoice_text)
    inv = extract_invoice_details(invoice_text)
    inv_date = extract_invoice_date(invoice_text)
    du = extract_du_financials(du_text)

    if du.invoice_ref and inv_no:
        report.add("DU FACTURA ref vs Tax Invoice No", du.invoice_ref == inv_no,
                   f"DU(13A)={du.invoice_ref} | Invoice={inv_no}")
    if du.invoice_ref and termo.invoice_ref:
        report.add("DU FACTURA ref vs Termo INVOICE", du.invoice_ref == termo.invoice_ref,
                   f"DU(13A)={du.invoice_ref} | Termo={termo.invoice_ref}")
    elif du.invoice_ref or termo.invoice_ref:
        report.add("DU FACTURA ref vs Termo INVOICE", False,
                   f"DU(13A)={du.invoice_ref or '?'} | Termo={termo.invoice_ref or '?'}")
    if du.invoice_date and inv_date:
        report.add("DU FACTURA date vs Invoice Date", du.invoice_date == inv_date,
                   f"DU(13A)={du.invoice_date} | Invoice={inv_date}")

    if du.fob is not None and inv.get("goods") not in (None, 0.0):
        ok = abs(du.fob - inv["goods"]) < 0.05
        report.add("DU FOB vs Invoice FCA", ok,
                   f"DU(FOB)={format_pt_amount(du.fob)} | Invoice(FCA)={format_pt_amount(inv['goods'])}")
    if du.freight is not None and inv.get("freight") not in (None, 0.0):
        ok = abs(du.freight - inv["freight"]) < 0.05
        report.add("DU Frete vs Invoice Air Freight", ok,
                   f"DU={format_pt_amount(du.freight)} | Invoice={format_pt_amount(inv['freight'])}")
    if None not in (du.fob, du.freight, du.insurance, du.cif):
        calc = du.fob + du.freight + du.insurance
        report.add("DU CIF = FOB+FRETE+SEGURO", abs(calc - du.cif) < 0.02,
                   f"CIF={format_pt_amount(du.cif)} | calc={format_pt_amount(calc)}")
    if inv.get("goods") and inv.get("freight") and inv.get("total"):
        calc = inv["goods"] + inv["freight"]
        report.add("Invoice FCA+Frete = Total", abs(calc - inv["total"]) < 0.05,
                   f"FCA+Frete={format_pt_amount(calc)} | Total={format_pt_amount(inv['total'])}")
    if du.rate and du.fob is not None and du.fob_mt is not None:
        conv = du.fob * du.rate
        report.add("DU FOB MT conversion @rate", abs(conv - du.fob_mt) < 1.0,
                   f"{format_pt_amount(du.fob)} EUR x {du.rate:.2f} = {conv:,.2f} MT vs {du.fob_mt:,.2f} MT")

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
    validate_triangle(termo, du_text, invoice_text, report)
    return por
