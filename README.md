# MOZA Cambial Stamp — Automation

Official rubber stamp from `test file.pdf` placed as **transparent overlay** (no white blocking) on Tax Invoice & Documento Único. Positions copied exactly from `example_1_fnb.pdf` blue Draft `Stamp` annots. Date is always **today** when program runs; `POR` value is the only field copied from Termo.

## Files (kept for GitHub)

```
project moza/
├─ test file.pdf              # blank stamp scan (source, keep)
├─ example_1_fnb.pdf          # blue Draft — position reference (keep, do not move)
├─ assets/stamp_template.png  # auto-extracted stamp (1240×693, auto-generated)
├─ stamp_pdf.py               # single-file entry (future-proof)
├─ termos/                    # drop PDFs here (gitignored, created empty)
├─ extracted/                 # previews (gitignored)
└─ macro_processes/
   ├─ core.py                 # shared: TEXT_POS, UCR, placement — EDIT HERE
   ├─ macro_blank.py          # 1) stamp only (no fields)
   ├─ macro_date.py           # 2) stamp + today DD/MM/YYYY split
   ├─ macro_full.py           # 3) stamp + today + POR + SALDO 0,00 (use this)
   ├─ batch_stamp.py          # recursive batch with (!!) suffix
   └─ termos_auto.py          # SIMPLEST: drop PDFs in ./termos/ -> auto creates ./termos (!!)/
```
Gitignored (not pushed): `20LOC*.pdf` `test 2.pdf` `* (!!).pdf` `extracted/` `termos (!!)/`

### Stamp fields

| Blank on stamp | Filled with | Source |
|---|---|---|
| `UTILIZADO P/FINS CAMBIAIS EM ___/___/___` | `DD` `MM` `YYYY` split into 3 blanks, centered `anchor="mm"` | `today_pt()` at runtime |
| `POR ___________________` | `9545,64 EUR` (example) | `Valor do Termo de Compromisso` from Termo page |
| `SALDO ________________` | `0,00 EUR` always | fixed |

All text `32pt` uniform (`max(22, h*0.038+6)`), lifted `0.007` above lines so it doesn't touch, `POR` shifted **~3 chars left** `x=0.656` vs `0.68` to be centered in its long line.

Text positions (`TEXT_POS` fractions of stamp image `w/h`):

```
d1 0.538,0.103  d2 0.633,0.103  d3 0.724,0.103
por 0.656,0.210  saldo 0.28,0.285
```

### Placement (from `example_1_fnb.pdf`)

Extracted via `page.annots()` type `Stamp`:

```
Invoice (p2): Rect(413.476, 651.229, 533.476, 681.279)
DU      (p3): Rect(394.182, 781.424, 514.182, 811.474)
```

`example_draft_rect(page, stamp_w, stamp_h, kind)` scales to page size `595×842` and clamps to `MARGIN 14` so `220pt` stamp stays visible. Tax Invoice & DU both follow draft. If you want Tax Invoice to prefer empty space first, `find_least_text_rect` falls back to draft when `overlap > 0.45*area`.

### Page-agnostic & future-proof

- `find_all_pages_by_marker(doc, markers)` — Termo can be on any page, not just p1
- `find_du_pages` filters `Continuação` pages
- `select_du_by_ucr` matches `Número Único por Consignação (UCR)` e.g. `0MZ400010234687766` Termo ↔ DU to link correct bundle even if pages shuffled
- **Invoices**: `find_all_pages_by_marker(["Tax Invoice","Commercial Invoice"])` → **ALL** stamped
- **DUs**: only **FIRST** matching DU stamped (others ignored, continuation ignored)

Validated via `ValidationReport`: UCR match, Invoice Total vs Termo, Valor Factura vs Termo, Invoice ref.

## Setup on another laptop (quick)

1. **Copy folder** `project moza` as-is (keep `test file.pdf`, `example_1_fnb.pdf`, `assets/`)

2. **Python 3.11+** — https://python.org/downloads/ — check `python --version`

3. **Install deps** (one-time, in project folder):
```powershell
python -m pip install --upgrade pip
python -m pip install pymupdf Pillow numpy
# if you have requirements.txt:
# pip install -r requirements.txt
```

4. **Test single file**:
```powershell
python macro_processes/macro_full.py ".\20LOC00566833_FNB.pdf"
# or
python stamp_pdf.py ".\20LOC00566833_FNB.pdf"
# output: 20LOC00566833_FNB_stamped_full.pdf  (or _stamped.pdf)
# with --date override:  python macro_processes/macro_full.py "file.pdf" --date 27/08/2026
```

5. **Batch all folders** (1000s of `*LOC*.pdf`):
```powershell
# from project root:
python macro_processes/batch_stamp.py "D:\path\to\LOC_root"
# optional pattern:
python macro_processes/batch_stamp.py "D:\LOC" --pattern "*LOC*.pdf"
# dry-run (validate only):
python macro_processes/batch_stamp.py "D:\LOC" --dry-run
```
Output is **same folder** with ` (!!)` suffix to mark stamped:
```
20LOC00566833_FNB.pdf  ->  20LOC00566833_FNB (!!).pdf
24LOC001234.pdf        ->  24LOC001234 (!!).pdf
```
Already stamped `* (!!).pdf` are skipped.

5b. **Simplest — termos folder (as you requested)**:
Just create a folder named `termos` in this codebase and drop PDFs inside (any subfolders). Run once:
```powershell
python macro_processes/termos_auto.py
```
It finds every folder named `termos*` in project root (so `termos`, `termos1`, `termos2` etc auto-numbered by you) and creates sibling `termos (!!)` / `termos1 (!!)` preserving structure:
```
termos/24LOC001.pdf  ->  termos (!!)/24LOC001 (!!).pdf
termos/batchA/20LOC002.pdf -> termos (!!)/batchA/20LOC002 (!!).pdf
```
Watch mode (auto-process new drops):
```powershell
python macro_processes/termos_auto.py --watch
```

## The 3 macro versions

| Macro | Use when | Output suffix | Command |
|---|---|---|---|
| `macro_blank.py` | stamp only, fill manually | `_stamped_blank.pdf` | `python macro_processes/macro_blank.py "file.pdf"` |
| `macro_date.py` | stamp + today date only | `_stamped_date.pdf` | `python macro_processes/macro_date.py "file.pdf"` |
| `macro_full.py` | **production** stamp+date+POR+SALDO | `_stamped_full.pdf` | `python macro_processes/macro_full.py "file.pdf"` |

All share `core.py` placement & UCR logic. For batch, `batch_stamp.py` calls `macro_full`.

## Naming convention

Files like `20LOC...`, `22LOC...`, `24LOC...` — leading `20`/`22`/`24` is year, not used for logic (date always today). Batch keeps **exact same name** plus ` (!!)` before `.pdf`.

## Adjusting char size & stamp placement (easy)

All adjustable in **2 files**: `macro_processes/core.py` and `stamp_pdf.py` (same constants). No rebuild needed — `assets/stamp_template.png` auto-cached.

**Char size** — `core.py` `build_full_stamp`:
```python
base_size = max(22, int(h * 0.038) + 6)  # h=693 → 32pt now; +6 = +2 bump vs previous
# larger: +8 (34pt), smaller: +4 (30pt), or fixed: base_size = 28
fonts = {"d1": _load_font(base_size), "por": _load_font(base_size), ...}  # all uniform
```
Increase `+6` → `+8` for +2pt, or set `base_size = 36` for big. All fields `d1/d2/d3/por/saldo` share it.

**Text position in stamp** — `TEXT_POS` fractions of stamp image `w=1240 h=693`:
```python
TEXT_POS = {"d1":(0.538,0.103), "d2":(0.633,0.103), "d3":(0.724,0.103), "por":(0.656,0.210), "saldo":(0.28,0.285)}
# x 0→1 left→right, y 0→1 top→bottom, anchor="mm" centered
# POR was 0.68 → 0.656 (~3 chars left) to center in long line
# nudge: y -0.005 = up ~3.5px, x +0.01 = right ~12px
```

**Stamp placement on page** — `core.py` `example_draft_rect` + `STAMP_WIDTH_PT`:
```python
STAMP_WIDTH_PT = 220.0  # width on page; height = 220/1.79≈123pt
MARGIN = 14.0
# from example_1_fnb.pdf blue Draft annots:
# invoice x0_src,y0_src = 413.47,651.22  du = 394.18,781.42 (for 595×842 page)
# scaled: x0 = x0_src * (pw/595), y0 = y0_src * (ph/842), then clamped to MARGIN
```
Move stamp: change `x0_src`/`y0_src` (e.g. `y0_src+20` = down). Bigger stamp: `STAMP_WIDTH_PT=250`.

After edit, test: `python macro_processes/macro_full.py ".\termos\test.pdf"` and check `extracted/trials/stamp_*.png`.

## Troubleshooting

- `Stamp source not found: test file.pdf` → keep `test file.pdf` in project root
- `Termo/Invoice/DU page not found` → PDF must contain those markers text (Termo de Compromisso, Tax Invoice, DOCUMENTO ÚNICO)
- `already exists SKIP` in batch → delete ` (!!).pdf` or run on copy
- Stamp text touches line → adjust `TEXT_POS` y `-0.005` in `core.py`/`stamp_pdf.py` and rebuild `assets/stamp_template.png` if needed
- Need different stamp size → change `STAMP_WIDTH_PT = 220.0` in `core.py`

## Closing changes placeholder

Positions are now locked to `example_1_fnb.pdf` draft. Before closing, confirm `TEXT_POS` POR `0.656` shift and `batch_stamp` ` (!!)` naming.
