"""
Batch stamp — recursively stamps all *LOC*.pdf files
Output is same folder with " (!!)" suffix: 20LOC001.pdf -> 20LOC001 (!!).pdf
Uses macro_full (date today + POR + SALDO), page-agnostic UCR, all invoices / first DU
Skips already stamped files containing "(!!)"
"""
from __future__ import annotations
import sys
from pathlib import Path

# allow running as `python macro_processes/batch_stamp.py` and as module
try:
    from core import today_pt, merge_pdfs, now_stamp, today_slug, outcome_to_row, error_row, skip_row, write_excel
    from macro_full import apply as apply_full
except ImportError:
    from macro_processes.core import today_pt, merge_pdfs, now_stamp, today_slug, outcome_to_row, error_row, skip_row, write_excel
    from macro_processes.macro_full import apply as apply_full

def batch_stamp(root: Path, pattern: str = "*LOC*.pdf", dry_run: bool = False) -> None:
    root = Path(root)
    if not root.exists():
        print(f"Error: folder not found: {root}", file=sys.stderr)
        sys.exit(1)
    files = [p for p in root.rglob(pattern) if p.is_file() and "(!!)" not in p.name and p.suffix.lower() == ".pdf"]
    files = sorted(files)
    if not files:
        print(f"No matching files for {pattern} under {root}")
        return
    print(f"Found {len(files)} files under {root} matching {pattern}")
    print(f"Date (today): {today_pt()} — POR from each Termo, SALDO 0,00")
    ok = 0
    skipped = 0
    failed = 0
    ts = now_stamp()
    rows = []
    for idx, pdf in enumerate(files, 1):
        out = pdf.with_name(pdf.stem + " (!!)" + pdf.suffix)
        if out.exists():
            print(f"[{idx}/{len(files)}] SKIP exists: {out.name}")
            skipped += 1
            rows.append(skip_row(pdf.name, out.name, ts))
            continue
        print(f"[{idx}/{len(files)}] {pdf.relative_to(root)} -> {out.name} ...", end=" ")
        try:
            oc = apply_full(pdf, out, dry_run=dry_run)
            ok += 1
            print("OK")
            rows.append(outcome_to_row(oc, pdf.name, ts))
        except Exception as e:
            print(f"FAIL: {e}")
            failed += 1
            rows.append(error_row(pdf.name, out.name, str(e), ts))
    print(f"\nDone: {ok} stamped, {skipped} skipped (already exists), {failed} failed, total {len(files)}")
    merged = root / "merged (!!).pdf"
    stamped_files = sorted(
        p for p in root.rglob("* (!!).pdf")
        if p.is_file() and p.name != merged.name
    )
    if stamped_files:
        n = merge_pdfs(stamped_files, merged)
        print(f"Merged {n} stamped PDFs -> {merged}")
    if rows and not dry_run:
        xl = root / f"processadas_{today_slug()}.xlsx"
        write_excel(rows, xl)
        print(f"Excel: {xl} ({len(rows)} rows)")

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Batch stamp all LOC PDFs with (!!) suffix")
    parser.add_argument("folder", type=Path, nargs="?", default=Path("."), help="Root folder containing LOC PDFs (default: current dir)")
    parser.add_argument("--pattern", default="*LOC*.pdf", help="Glob pattern (default *LOC*.pdf)")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, don't write")
    args = parser.parse_args(argv)
    batch_stamp(args.folder, pattern=args.pattern, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
