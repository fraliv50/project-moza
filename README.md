# MOZA Cambial Stamp — Automation

Official rubber stamp from `test file.pdf` placed as **transparent overlay** (no white blocking) on Tax Invoice & Documento Único. Positions copied exactly from `example_1_fnb.pdf` blue Draft `Stamp` annots. Date is always **today** when the program runs; `POR` is the only value copied from the Termo.

## Daily use (one command)

1. **Drop PDFs** into a folder named `termos` in the project root (subfolders allowed).
2. **Run:**
   ```powershell
   python macro_processes/termos_auto.py
   ```
   It processes every folder named `termos*` (`termos`, `termos1`, `termos2` … all count) and creates a sibling output folder `termos (!!)` mirroring the structure:
   ```
   termos/24LOC001.pdf        ->  termos (!!)/24LOC001 (!!).pdf
   termos/batchA/20LOC002.pdf ->  termos (!!)/batchA/20LOC002 (!!).pdf
   ```
3. **You get everything:**
   - **Stamped copies** `name (!!).pdf` — date (today) + `POR` + `SALDO 0,00 EUR` filled from that Termo (fallback modes when pages are missing, see below).
   - **`termos (!!)/merged (!!).pdf`** — all stamped PDFs concatenated in order, for one-shot printing.
   - **`processadas_<YYYY-MM-DD>.xlsx`** — the run record (7 columns, one row per bundle).

Watch mode (auto-process new drops; Ctrl+C to stop):
```powershell
python macro_processes/termos_auto.py --watch
```

Notes:
- **Already-stamped files are skipped** (`name (!!).pdf` exists). Delete `termos (!!)` to force a re-stamp.
- **Date is always today** at runtime, regardless of the reference in the Termo.

## Files (kept for GitHub)

```
project moza/
├─ test file.pdf              # blank stamp scan (source, keep)
├─ example_1_fnb.pdf          # blue Draft — placement reference (keep)
├─ assets/stamp_template.png  # extracted stamp template (auto-regenerated)
├─ termos/                    # drop PDFs here (gitignored)
├─ extracted/                 # previews (gitignored)
├─ macro_processes/
│  ├─ core.py                 # shared logic, placement, stamp build — EDIT HERE
│  ├─ macro_full.py           # stamps one file (date + POR + SALDO)
│  └─ termos_auto.py          # the one-command entrypoint
├─ requirements.txt
├─ README.md
└─ LICENSE
```

Gitignored (not pushed): `termos/` `termos (!!)/` `20LOC*.pdf` `* (!!).pdf` `*_stamped*.pdf` `extracted/` `processadas_*.xlsx`

### Stamp fields

| Blank on stamp | Filled with | Source |
|---|---|---|
| `UTILIZADO P/FINS CAMBIAIS EM ___/___/___` | `DD` `MM` `YYYY` in 3 blanks, centered | `today_pt()` at runtime |
| `POR ___________________` | e.g. `9545,64 EUR` | `Valor do Termo de Compromisso` from Termo page |
| `SALDO ________________` | `0,00 EUR` always | fixed |

All text `32pt` uniform (`max(22, h*0.038+6)`), POR shifted **~3 chars left** `x=0.656` vs `0.68` to center in its long line. Text positions (`TEXT_POS` fractions of the stamp image `w/h`):

```
d1 0.538,0.103  d2 0.633,0.103  d3 0.724,0.103
por 0.656,0.210  saldo 0.28,0.285
```

### Placement (from `example_1_fnb.pdf`)

```
Invoice (p2): Rect(413.476, 651.229, 533.476, 681.279)
DU      (p3): Rect(394.182, 781.424, 514.182, 811.474)
```

`example_draft_rect(page, stamp_w, stamp_h, kind)` scales to page size `595×842` and clamps to `MARGIN 14`. The stamp ink is measured from the template and the placement rect is sized so the **visible** stamp is exactly `STAMP_INK_WIDTH_PT = 231.95 pt`. The DU stamp is lowered by `DU_DROP_SHARE = 1.10` of its visible height.

### Page-agnostic & validated

- Termo can be on any page (`find_all_pages_by_marker`); DU continuation sheets are never stamped.
- `select_du_by_ucr` links Termo ↔ DU via `Número Único por Consignação (UCR)` even if pages are shuffled.
- **All Tax Invoices stamped**, only the **first** UCR-matched DU.
- `ValidationReport` per file: UCR Termo↔DU, invoice-number triangle (`INVOICE:` on Termo ⇄ Tax Invoice ⇄ DU `13A Nº e data da factura`), Invoice Total ↔ Termo, DU FOB=Invoice FCA, DU Frete=Invoice Air Freight, DU CIF = FOB+FRETE+SEGURO, MT↔EUR conversion @ taxa de câmbio.

### Fallback (when full automation can't run)

If Termo / Tax Invoice / Documento Único aren't **all** found, the file is **not skipped** — a safe ladder runs using whatever *can* be found:

1. **POR-fill fallback** — Termo found (strict or liberal scan of details only it has) **and** `Valor do Termo de Compromisso` extractable → **FULL** stamp on every **identified** page (all invoices + first relevant DU).
2. **Date-only fallback** — even POR not extractable → `DD/MM/YYYY` stamp on every page except the Termo and DU continuations; POR/SALDO blank for manual fill.
3. **Never stamped**: Termo page and `Documento Único (Continuação)` sheets. If the Termo can't be identified even liberally, the file is **skipped** (nothing stamped).
4. Output prints `FALLBACK-POR` or `FALLBACK` so you know which mode ran.

### Excel record (one workbook per run)

Written at the end of every run as `processadas_<YYYY-MM-DD>.xlsx` in the project root, with two sheets (pandas + openpyxl):

- **`Processadas`** — 7 priority columns per bundle: `resultado` (OK/FALLBACK-POR/FALLBACK-DATA/ERRO/SKIP), `ficheiro_origem`, `ucr`, `ref_termo`, `valor_termo_eur` (POR), `total_factura_eur`, `nr_factura`.
- **`Resumo`** — count per `resultado` plus `TOTAIS NAO-ERRO` sums of POR / total factura.

Rows are **deduplicated by bundle** (UCR, else ref_termo, else file name): the same bundle in several input files yields **one** row, keeping the best outcome. Amounts are numbers; missing fields are blank.

## Setup on another laptop

1. **Copy the folder** as-is (keep `test file.pdf`, `example_1_fnb.pdf`, `assets/`).
2. **Python 3.11+** — https://python.org/downloads/ — check `python --version`.
3. **Install deps** (one-time):
   ```powershell
   python -m pip install -r requirements.txt
   ```
4. **Create a `termos` folder**, drop PDFs in, and run:
   ```powershell
   python macro_processes/termos_auto.py
   ```

## Adjusting char size & stamp placement (easy)

Everything adjustable in **one file**: `macro_processes/core.py`. No rebuild needed — `assets/stamp_template.png` auto-caches.

**Char size** — `build_full_stamp`:
```python
base_size = max(22, int(h * 0.038) + 6)  # h=693 -> 32pt now
# larger: +8 (34pt), smaller: +4 (30pt), or fixed: base_size = 28
```

**Text position in stamp** — `TEXT_POS` fractions of `w=1240 h=693`:
```python
TEXT_POS = {"d1":(0.538,0.103), "d2":(0.633,0.103), "d3":(0.724,0.103), "por":(0.656,0.210), "saldo":(0.28,0.285)}
# nudge: y -0.005 = up ~3.5px, x +0.01 = right ~12px
```

**Stamp size & placement** — constants + `example_draft_rect`:
```python
STAMP_INK_WIDTH_PT = 231.95  # visible stamp ink width in pt (measured from test file.pdf)
MARGIN = 14.0
DU_DROP_SHARE = 1.10         # DU stamp lowered by 110% of visible height ("du" kind only)
# from example_1_fnb.pdf blue Draft annots:
# invoice x0_src,y0_src = 413.47,651.22   du = 394.18,781.42 (for 595x842 page)
# scaled: x0 = x0_src * (pw/595), y0 = y0_src * (ph/842), then clamped to MARGIN
```
Move stamp: change `x0_src`/`y0_src` (e.g. `y0_src+20` = down). Bigger/smaller: change `STAMP_INK_WIDTH_PT`. DU drop: adjust `DU_DROP_SHARE` (`0` = draft position).

## Troubleshooting

- `Stamp source not found: test file.pdf` → keep `test file.pdf` in project root
- `all automation AND Termo page not found` → the PDF has no Termo text at all; file is skipped intentionally
- `SKIP already stamped` → output exists in `termos (!!)`; delete it to re-stamp
- `PermissionError` writing the Excel → close `processadas_*.xlsx` if it's open in Excel
- Stamp text touches the line → adjust `TEXT_POS` y in `core.py`