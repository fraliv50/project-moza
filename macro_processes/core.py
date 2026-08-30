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
    nuit_exportador: str | None = None
    nome_exportador: str | None = None
    pais_exportador: str | None = None
    nuit_importador: str | None = None
    nome_importador: str | None = None
    pais_importador: str | None = None
    banco_emitente: str | None = None
    data_emissao: str | None = None
    modalidade: str | None = None
    regime: str | None = None
    transporte: str | None = None
    mercadoria: str | None = None

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

# Recover glyphs the PDF font leaves as U+FFFD (no ToUnicode for accented chars).
_MOJIBAKE_FIXES = {
    "Importa��o": "Importação",
    "A�reo": "Aéreo",
    "Mo�ambique": "Moçambique",
    "Pa�s": "País",
}

def _clean_text(s: str) -> str:
    if not s:
        return s
    for bad, good in _MOJIBAKE_FIXES.items():
        s = s.replace(bad, good)
    return s

def extract_termo_data(text: str) -> TermoData:
    text = _clean_text(text)
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
    lines = [ln.strip() for ln in text.splitlines()]
    data.nuit_exportador = _field_after(lines, "NUIT do Exportador", "Nuit do Exportador")
    data.nome_exportador = _field_after(lines, "Nome do Exportador")
    data.pais_exportador = _field_after(lines, "País Exportador", "Pa�s Exportador", "Pais Exportador")
    data.nuit_importador = _field_after(lines, "NUIT do Importador", "Nuit do Importador")
    data.nome_importador = _field_after(lines, "Nome do Importador")
    data.pais_importador = _field_after(lines, "País Importador", "Pa�s Importador", "Pais Importador")
    data.banco_emitente = _field_after(lines, "Banco Emitente", "Banco Emissor")
    data.modalidade = _field_after(lines, "Modalidade de Remessa/Pagamento", "Modalidade de Remessa / Pagamento")
    data.regime = _field_after(lines, "Regime")
    data.transporte = _field_after(lines, "Modo de Transporte", "Modo de Transporte/Rota")
    data.mercadoria = _field_after(lines, "Mercadoria/bem", "Mercadoria / bem", "Mercadoria/ bem")
    em = _field_after(lines, "Data de Emissão")
    if em:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", em)
        if m:
            data.data_emissao = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return data

def _squash(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold_text(s or ""))

def _field_after(lines: list[str], *variants: str) -> str | None:
    """Value that follows a label line (next non-empty line, or same line after ':').

    Squashes whitespace/accents so it also matches corrupted encodings. Exact
    label matches are tried first; a string-similarity fallback (threshold >= 0.9
    plus shared 2-char prefix) only runs when NO exact variant matched anywhere,
    catching labels that lost accented glyphs (\ufffd).
    """
    import difflib
    sq = [_squash(ln) for ln in lines]
    svs = [_squash(v) for v in variants]

    def pick_from(i: int) -> str | None:
        line = lines[i]
        if ":" in line:
            rest = line.split(":", 1)[1].strip()
            if rest:
                return rest
        for j in range(i + 1, len(lines)):
            v = lines[j].strip()
            if v:
                return v
        return None

    for sv in svs:
        for i, q in enumerate(sq):
            if q == sv or q.startswith(sv + ":"):
                got = pick_from(i)
                if got:
                    return got
    for sv in svs:
        if len(sv) < 10:
            continue
        for i, q in enumerate(sq):
            if len(q) < 8 or q[:2] != sv[:2]:
                continue
            if difflib.SequenceMatcher(None, q, sv).ratio() >= 0.9:
                got = pick_from(i)
                if got:
                    return got
    return None

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
    decl_no: str | None = None
    liqui_iso: str | None = None

def extract_du_financials(text: str) -> DuFinancials:
    """Financial/factura block of the DU (fields 13A, 22, 23, 28, 24)."""
    text = _clean_text(text)
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
    m = re.search(r"N[ºo°]\s*DA\s*DECLARA[ÇC][ÃA]O[^\d]{0,24}(\d{6,15})", text, re.I)
    if m:
        fin.decl_no = m.group(1)
    m = re.search(r"Data\s+de\s+liquida[çc][ãa]o[^\d]{0,24}(\d{2})/(\d{2})/(\d{4})", text, re.I)
    if m:
        fin.liqui_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
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

def build_full_stamp(stamp_date: str, por_display: str, saldo: str = SALDO_TEXT) -> tuple[bytes, float]:
    """Stamp with date + POR + SALDO filled."""
    template_path = ensure_stamp_template()
    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    parts = stamp_date.split("/")
    d1 = parts[0] if len(parts) > 0 else ""
    d2 = parts[1] if len(parts) > 1 else ""
    d3 = parts[2] if len(parts) > 2 else ""
    por_text = f"{por_display}{POR_SUFFIX}"
    base_size = max(22, int(h * 0.038) + 6)
    fonts = {k: _load_font(base_size) for k in ("d1", "d2", "d3", "por", "saldo")}
    for key, text in (("d1", d1), ("d2", d2), ("d3", d3), ("por", por_text), ("saldo", saldo)):
        fx, fy = TEXT_POS[key]
        draw.text((int(w * fx), int(h * fy)), text, fill=(0, 0, 0, 255), font=fonts[key], anchor="mm")
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
    png_bytes, aspect = build_full_stamp(stamp_date, por_display)
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
) -> BundleOutcome:
    """Most automated safe fallback:

    1. Find the Termo (strict markers, else liberal scan). Missing even liberally -> skip the file.
    2. If the Termo's value (POR) is extractable -> FULL stamp on identified invoice/DU pages.
    3. Otherwise -> date-only stamp on every non-Termo, non-DU-continuation page.
    """
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
    termo.page_idx = termo_pages[0]
    du_fin = extract_du_financials(doc[sorted(du_indices)[0]].get_text()) if du_indices else None
    inv_text = doc[invoice_indices[0]].get_text() if invoice_indices else None
    inv_details = extract_invoice_details(inv_text) if inv_text else {}
    inv_no = (extract_invoice_number(inv_text) if inv_text else None) or (termo.invoice_ref or None) or ""
    inv_date = extract_invoice_date(inv_text) if inv_text else None

    def make_result(result: str, stamped: list[tuple[int, str, tuple]], report: ValidationReport) -> BundleOutcome:
        warns = " | ".join(f"{nm}: {dt}" for nm, ok, dt in report.checks if not ok)
        return BundleOutcome(
            result=result,
            output_name=str(output_path),
            stamped_pages=",".join(str(pn) for pn, _, _ in stamped),
            checks_ok=sum(1 for _, ok, _ in report.checks),
            checks_total=len(report.checks),
            warns=warns,
            termo=termo,
            du=du_fin,
            inv=inv_details,
            inv_no=inv_no or "",
            inv_date=_iso_date(inv_date) or "",
        )

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
            return make_result("FALLBACK-POR", stamped, fb_report)
    report, stamped = apply_date_fallback(
        doc, output_path, termo_pages, invoice_indices, du_indices, stamp_date, dry_run,
    )
    reason = "POR known but no identifiable invoice/DU page to stamp" if termo.valor_termo is not None else "POR not extractable"
    print(f"FALLBACK — missing {', '.join(missing) or 'none (strict markers only)'}; "
          f"{reason} => date-only stamp (POR/SALDO left blank for manual fill)")
    for pno, kind, r in stamped:
        print(f"  p{pno} [{kind}] date-only: {r}")
    if not dry_run:
        print(f"Saved: {output_path}")
    report.print_report()
    return make_result("FALLBACK-DATA", stamped, report)

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

def merge_pdfs(sources: list[Path], output: Path) -> int:
    """Concatenate PDFs in order into one file. Returns number of files merged."""
    output = Path(output)
    out = fitz.open()
    try:
        for p in sources:
            with fitz.open(p) as src:
                out.insert_pdf(src)
        if out.page_count:
            out.save(output, garbage=4, deflate=True)
    finally:
        out.close()
    return len(sources)

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

# --- Excel record of every processed bundle ---

@dataclass
class BundleOutcome:
    result: str = ""                                   # OK | FALLBACK-POR | FALLBACK-DATA | ERRO | SKIP
    input_name: str = ""
    output_name: str = ""
    error: str = ""
    stamped_pages: str = ""
    checks_ok: int = 0
    checks_total: int = 0
    warns: str = ""
    termo: TermoData | None = None
    du: DuFinancials | None = None
    inv: dict = field(default_factory=dict)
    inv_no: str = ""
    inv_date: str = ""

EXCEL_COLUMNS = [
    "resultado", "ficheiro_origem", "ucr", "ref_termo",
    "valor_termo_eur", "total_factura_eur", "nr_factura",
]

def _iso_date(s: str | None) -> str | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s.strip()

def today_slug() -> str:
    d = date.today()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"

def outcome_to_row(oc: BundleOutcome, input_name: str) -> dict:
    t = oc.termo
    inv_no = oc.inv_no or ""
    if not inv_no and oc.du and oc.du.invoice_ref:
        inv_no = oc.du.invoice_ref
    return {
        "resultado": oc.result,
        "ficheiro_origem": input_name,
        "ucr": t.ucr if t else None,
        "ref_termo": t.ref_termo if t else None,
        "valor_termo_eur": t.valor_termo if t else None,
        "total_factura_eur": (oc.inv or {}).get("total"),
        "nr_factura": inv_no or None,
    }

def error_row(input_name: str, output_name: str, error: str) -> dict:
    oc = BundleOutcome(result="ERRO", input_name=input_name, output_name=output_name, error=error)
    return outcome_to_row(oc, input_name)

def skip_row(input_name: str, output_name: str) -> dict:
    oc = BundleOutcome(result="SKIP", input_name=input_name, output_name=output_name)
    return outcome_to_row(oc, input_name)

def write_excel(rows: list[dict], output_path: Path, summary: bool = True) -> tuple[Path, int]:
    """Write one workbook per run: 'Processadas' (one row per bundle) + 'Resumo'.

    Rows are deduplicated by bundle identity (UCR, else ref_termo, else file name):
    a bundle appearing in several input files yields ONE row, preferring the best
    outcome (OK > FALLBACK-POR > FALLBACK-DATA > SKIP > ERRO). Returns (path, n).
    """
    import pandas as pd
    output_path = Path(output_path)
    df = pd.DataFrame([{c: r.get(c) for c in EXCEL_COLUMNS} for r in rows])
    order = {"OK": 0, "FALLBACK-POR": 1, "FALLBACK-DATA": 2, "SKIP": 3, "ERRO": 4}
    seen: dict[str, int] = {}
    keep: list[dict] = []
    for row in df.to_dict("records"):
        key = row.get("ucr") or row.get("ref_termo") or row.get("ficheiro_origem")
        if key is None:
            keep.append(row)
            continue
        key = str(key).strip()
        rank = order.get(str(row.get("resultado")), 5)
        idx = seen.get(key)
        if idx is None:
            seen[key] = len(keep)
            keep.append(row)
        elif rank < order.get(str(keep[idx].get("resultado")), 5):
            keep[idx] = row
    df = pd.DataFrame(keep, columns=EXCEL_COLUMNS)
    with pd.ExcelWriter(output_path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Processadas", index=False)
        if summary and len(df):
            sum_rows = []
            for res, g in df.groupby(df["resultado"].fillna("?")):
                sum_rows.append({"Resultado": res, "N": len(g)})
            ok_df = df[df["resultado"].fillna("") != "ERRO"]
            money = {
                "Somatorio POR (EUR)": "valor_termo_eur",
                "Somatorio Total Factura (EUR)": "total_factura_eur",
            }
            row = {"Resultado": "TOTAIS NAO-ERRO", "N": len(ok_df)}
            for label, col in money.items():
                vals = pd.to_numeric(ok_df[col], errors="coerce")
                row[label] = float(vals.sum()) if vals.notna().any() else 0.0
            sum_rows.append(row)
            pd.DataFrame(sum_rows).to_excel(xw, sheet_name="Resumo", index=False)
    return output_path, len(df)
