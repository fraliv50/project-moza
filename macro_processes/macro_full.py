"""
Macro Full — stamp + date (today) + POR (Valor do Termo) + SALDO 0,00
Page-agnostic UCR matching, stamps ALL invoices, only FIRST DU
Positions copied exactly from example_1_fnb.pdf blue Draft
"""
from __future__ import annotations
import argparse
import io
import sys
from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont
from core import ensure_stamp_template, _load_font, TEXT_POS, STAMP_TEMPLATE, POR_SUFFIX, SALDO_TEXT, stamp_rect_size, example_draft_rect, place_stamp, find_all_pages_by_marker, find_du_pages, extract_termo_data, extract_ucr_from_du, validate_bundle, ValidationReport, format_pt_amount, today_pt, apply_date_fallback

ROOT = Path(__file__).resolve().parent.parent

def build_full_stamp(stamp_date: str, por_display: str, saldo: str = SALDO_TEXT) -> tuple[bytes, float]:
    template_path = ensure_stamp_template()
    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    parts = stamp_date.split("/")
    d1, d2, d3 = (parts[0] if len(parts)>0 else "", parts[1] if len(parts)>1 else "", parts[2] if len(parts)>2 else "")
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
        draw.text((int(w*fx), int(h*fy)), text, fill=(0,0,0,255), font=fonts[key], anchor="mm")
    data = img.getdata()
    trans = []
    for r,g,b,a in data:
        if r>=235 and g>=235 and b>=235:
            trans.append((255,255,255,0))
        else:
            trans.append((r,g,b,a))
    img.putdata(trans)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), w/h

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

def apply(input_path: Path, output_path: Path | None = None, *, stamp_date: str | None = None, stamp_source: Path | None = None, dry_run: bool = False) -> ValidationReport:
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_name(input_path.stem + "_stamped_full.pdf")
    if stamp_source:
        ensure_stamp_template(stamp_source)
    else:
        ensure_stamp_template()
    stamp_date = stamp_date or today_pt()
    report = ValidationReport()
    doc = fitz.open(input_path)
    termo_indices = find_all_pages_by_marker(doc, ["Termo de Compromisso"])
    invoice_indices = find_all_pages_by_marker(doc, ["Tax Invoice", "Commercial Invoice"])
    du_indices_all = find_du_pages(doc)
    if not (termo_indices and invoice_indices and du_indices_all):
        missing = []
        if not termo_indices:
            missing.append("Termo de Compromisso")
        if not invoice_indices:
            missing.append("Tax Invoice / Commercial Invoice")
        if not du_indices_all:
            missing.append("Documento Único")
        print(f"FALLBACK — missing {', '.join(missing)}; date-only stamp on non-Termo pages (POR/SALDO leave blank)")
        report, stamped = apply_date_fallback(doc, output_path, termo_indices, invoice_indices, du_indices_all, stamp_date, dry_run)
        print(f"Input: {input_path}")
        print(f"Output: {output_path}")
        print(f"Date: {stamp_date}")
        for pno, kind, r in stamped:
            print(f"  p{pno} [{kind}] date-only: {r}")
        if not dry_run:
            print(f"\nSaved: {output_path}")
        doc.close()
        report.print_report()
        return report
    termo = extract_termo_data(doc[termo_indices[0]].get_text())
    termo.page_idx = termo_indices[0]
    du_idx = select_du_by_ucr(doc, du_indices_all, termo.ucr)
    du_text = doc[du_idx].get_text()
    inv_text = doc[invoice_indices[0]].get_text()
    por_display = validate_bundle(termo, du_text, inv_text, report)
    for extra_idx in invoice_indices[1:]:
        extra_ucr = extract_ucr_from_du(doc[extra_idx].get_text()) if False else None
        pass
    png_bytes, aspect = build_full_stamp(stamp_date, por_display)
    stamp_w, stamp_h = stamp_rect_size(aspect)
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Date (today): {stamp_date}")
    print(f"POR (from Termo p{termo_indices[0]+1}): {por_display}{POR_SUFFIX}")
    print(f"SALDO: {SALDO_TEXT}")
    print(f"Termo pages: {[i+1 for i in termo_indices]} (UCR={termo.ucr}) page-agnostic matched")
    print(f"Invoices: {[i+1 for i in invoice_indices]} -> ALL stamped")
    print(f"DU pages: {[i+1 for i in du_indices_all]} -> ONLY FIRST matched {du_idx+1} stamped (UCR matched)")
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

def main(argv=None):
    parser = argparse.ArgumentParser(description="Macro Full — stamp + date + POR + SALDO, page-agnostic UCR, all invoices / first DU")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--date", default=None, help="DD/MM/YYYY default today")
    parser.add_argument("--stamp-source", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.input.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    try:
        apply(args.input, args.output, stamp_date=args.date, stamp_source=args.stamp_source, dry_run=args.dry_run)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
