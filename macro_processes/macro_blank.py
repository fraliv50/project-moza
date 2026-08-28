"""
Macro Blank — stamp only, no fields
Uses official scanned stamp from test file.pdf, transparent overlay
Page-agnostic: finds Termo anywhere via UCR, stamps ALL invoices, only FIRST DU
"""
from __future__ import annotations
import argparse
import io
import sys
from pathlib import Path
import fitz
from PIL import Image
from core import ensure_stamp_template, stamp_rect_size, example_draft_rect, place_stamp, find_all_pages_by_marker, find_du_pages, extract_termo_data, validate_bundle, ValidationReport, STAMP_TEMPLATE

ROOT = Path(__file__).resolve().parent.parent

def build_blank_stamp() -> tuple[bytes, float]:
    template_path = ensure_stamp_template()
    img = Image.open(template_path).convert("RGBA")
    w, h = img.size
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

def apply(input_path: Path, output_path: Path | None = None, *, stamp_source: Path | None = None, dry_run: bool = False) -> ValidationReport:
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_name(input_path.stem + "_stamped_blank.pdf")
    if stamp_source:
        ensure_stamp_template(stamp_source)
    else:
        ensure_stamp_template()
    report = ValidationReport()
    doc = fitz.open(input_path)
    termo_indices = find_all_pages_by_marker(doc, ["Termo de Compromisso"])
    invoice_indices = find_all_pages_by_marker(doc, ["Tax Invoice", "Commercial Invoice"])
    du_indices = find_du_pages(doc)
    if not termo_indices:
        raise ValueError("Termo de Compromisso page not found (page-agnostic search)")
    if not invoice_indices:
        raise ValueError("Tax Invoice / Commercial Invoice page not found")
    if not du_indices:
        raise ValueError("Documento Único page not found")
    termo = extract_termo_data(doc[termo_indices[0]].get_text())
    termo.page_idx = termo_indices[0]
    du_text = doc[du_indices[0]].get_text()
    inv_text = doc[invoice_indices[0]].get_text()
    validate_bundle(termo, du_text, inv_text, report)
    png_bytes, aspect = build_blank_stamp()
    stamp_w, stamp_h = stamp_rect_size(aspect)
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Termo page: {termo_indices[0]+1} UCR={termo.ucr}")
    print(f"Invoices: {[i+1 for i in invoice_indices]} (all stamped)")
    print(f"DU pages: {[i+1 for i in du_indices]} -> only first {du_indices[0]+1} stamped")
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
    parser = argparse.ArgumentParser(description="Macro Blank — stamp only")
    parser.add_argument("input", type=Path, help="Input PDF")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--stamp-source", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.input.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        return 1
    try:
        apply(args.input, args.output, stamp_source=args.stamp_source, dry_run=args.dry_run)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
