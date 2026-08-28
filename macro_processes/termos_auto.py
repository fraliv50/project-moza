"""
Termos auto — as simple as possible
Watches ./termos folder (any folder named termos* in project root)
For each PDF inside, creates stamped copy in sibling folder "termos (!!)" 
preserving subfolder structure, files renamed "name (!!).pdf"
Uses macro_full (today + POR + SALDO), page-agnostic UCR, all invoices / first DU
Run: python macro_processes/termos_auto.py
Or run once: it will find existing termos folders and process all PDFs
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from macro_full import apply as apply_full
    from core import today_pt
except ImportError:
    from macro_processes.macro_full import apply as apply_full
    from macro_processes.core import today_pt

def find_termos_folders(root: Path) -> list[Path]:
    out = []
    for p in root.iterdir():
        if p.is_dir() and p.name.lower().startswith("termos"):
            # skip already stamped outputs
            if "(!!)" in p.name:
                continue
            out.append(p)
    return sorted(out)

def process_termos_folder(src_folder: Path) -> None:
    dst_folder = src_folder.parent / (src_folder.name + " (!!)")
    dst_folder.mkdir(parents=True, exist_ok=True)
    pdfs = [p for p in src_folder.rglob("*.pdf") if p.is_file() and "(!!)" not in p.name]
    if not pdfs:
        print(f"[{src_folder.name}] no PDFs")
        return
    print(f"[{src_folder.name}] {len(pdfs)} PDFs -> {dst_folder.name}  Date: {today_pt()}")
    ok = 0
    for pdf in sorted(pdfs):
        rel = pdf.relative_to(src_folder)
        out = dst_folder / rel.parent / (pdf.stem + " (!!)" + pdf.suffix)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            print(f"  SKIP {rel} already stamped")
            continue
        try:
            apply_full(pdf, out)
            print(f"  OK {rel} -> {out.relative_to(dst_folder)}")
            ok += 1
        except Exception as e:
            print(f"  FAIL {rel}: {e}")
    print(f"Done {src_folder.name}: {ok}/{len(pdfs)} stamped -> {dst_folder}\n")

def main(argv=None, watch: bool = False):
    import argparse
    parser = argparse.ArgumentParser(description="Termos auto — stamp folders named termos* -> termos (!!)")
    parser.add_argument("--watch", action="store_true", help="watch mode: keep running and process new folders")
    parser.add_argument("--interval", type=int, default=5, help="watch interval seconds")
    args = parser.parse_args(argv)
    # one-shot
    folders = find_termos_folders(ROOT)
    if not folders:
        print(f"No folder named termos* found in {ROOT}")
        print(f"Create e.g. {ROOT/'termos' / '20LOC...pdf'} and rerun")
        if not args.watch:
            return
    for f in folders:
        process_termos_folder(f)
    if args.watch or watch:
        print(f"Watching {ROOT} every {args.interval}s for new termos folders... Ctrl+C to stop")
        seen = set(str(p) for p in find_termos_folders(ROOT))
        try:
            while True:
                time.sleep(args.interval)
                current = find_termos_folders(ROOT)
                for p in current:
                    if str(p) not in seen:
                        print(f"\nNew folder detected: {p.name}")
                        process_termos_folder(p)
                        seen.add(str(p))
                    else:
                        # also check for new PDFs inside existing termos folders
                        pdfs = [x for x in p.rglob("*.pdf") if "(!!)" not in x.name]
                        # if any PDF has no stamped counterpart, re-process
                        need = False
                        for pdf in pdfs:
                            rel = pdf.relative_to(p)
                            out = p.parent / (p.name + " (!!)") / rel.parent / (pdf.stem + " (!!)" + pdf.suffix)
                            if not out.exists():
                                need = True
                                break
                        if need:
                            process_termos_folder(p)
        except KeyboardInterrupt:
            print("\nStopped")

if __name__ == "__main__":
    main()
