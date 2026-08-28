"""
Macro Date — stamp + current date (DD/MM/YYYY split into 3 blanks)
Page-agnostic UCR, stamps ALL invoices, only FIRST DU
"""
from __future__ import annotations
import argparse
import io
import sys
from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont
from core import ensure_stamp_template, _load_font, TEXT_POS, stamp_rect_size, example_draft_rect, place_stamp, find_all_pages_by_marker, find_du_pages, extract_termo_data, validate_bundle, ValidationReport, today_pt, build_date_stamp, apply_date_fallback

ROOT = Path(__file__).resolve().parent.parent

def apply(input_path: Path, output_path: Path | None = None, *, stamp_date: str | None = None, stamp_source: Path | None = None, dry_run: bool = False) -> ValidationReport:
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_name(input_path.stem + "_stamped_date.pdf")
    if stamp_source:
        ensure_stamp_template(stamp_source)
    else:
        ensure_stamp_template()
    stamp_date = stamp_date or today_pt()
    report = ValidationReport()
    doc = fitz.open(input_path)
    termo_indices = find_all_pages_by_marker(doc, ["Termo de Compromisso"])
    invoice_indices = find_all_pages_by_marker(doc, ["Tax Invoice", "Commercial Invoice"])
    du_indices = find_du_pages(doc)
    if not (termo_indices and invoice_indices and du_indices):
        missing = []
        if not termo_indices:
            missing.append("Termo de Compromisso")
        if not invoice_indices:
            missing.append("Tax Invoice / Commercial Invoice")
        if not du_indices:
            missing.append("Documento Único")
        print(f"FALLBACK — missing {', '.join(missing)}; date-only stamp on non-Termo pages (POR/SALDO leave blank)")
        report, stamped = apply_date_fallback(doc, output_path, termo_indices, invoice_indices, du_indices, stamp_date, dry_run)
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
    du_text = doc[du_indices[0]].get_text()
    inv_text = doc[invoice_indices[0]].get_text()
    validate_bundle(termo, du_text, inv_text, report)
    png_bytes, aspect = build_date_stamp(stamp_date)
    stamp_w, stamp_h = stamp_rect_size(aspect)
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Date: {stamp_date}")
    print(f"Termo page: {termo_indices[0]+1} UCR={termo.ucr}")
    print(f"Invoices: {[i+1 for i in invoice_indices]} (all stamped)")
    print(f"DU first: {du_indices[0]+1} stamped (of {du_indices})")
    if not dry_run:
        for idx in invoice_indices:
            rect = example_draft_rect(doc[idx], stamp_w, stamp_h, "invoice")
            place_stamp(doc[idx], rect, png_bytes)
            print(f"  Invoice p{idx+1}: {tuple(round(v,1) for v in rect)}")
        rect = example_draft_rect(doc[du_indices[0]], stamp_w, stamp_h, "du")
        place_stamp(doc[du_indices[0]], rect, png_bytes)
        print(f"  DU p{du_indices[0]+1}: {tuple(round(v,1) for v in rect)}")
        doc.save(output_path, garbage=4, deflate=True)
        print(f"\nSaved: {output_path}")
    doc.close()
    report.print_report()
    return report

def main(argv=None):
    parser = argparse.ArgumentParser(description="Macro Date — stamp + current date")
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
