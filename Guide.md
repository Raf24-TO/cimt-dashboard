# Guide — Canadian Grid-Equipment Trade Dashboard (CIMT)

> **Purpose of this file.** This is a self-contained reference describing all the
> data and analysis available in the "Strengthening Canada's Grid Equipment
> Supply Chain" project. Drop it into another project so an assistant knows
> exactly what trade data exists, how it's structured, what it covers, how to
> load it, and the caveats. Everything below reflects the data as built; figures
> are illustrative and should be recomputed from the files for precision.

---

## 1. What this project is

A Streamlit dashboard and dataset analysing **Canadian international trade in
electricity-grid equipment and its upstream materials**. It tracks who Canada
trades grid hardware with, in what value/quantity, over time, organised into
plain-English equipment categories — plus a registry of the companies that
import these goods.

It answers questions like:
- How much does Canada import/export of large power transformers, switchgear,
  HV cable, conductors, transformer-core steel, etc., and from/to which countries?
- How have those flows changed 2016 → 2025 (nominal and inflation-adjusted)?
- Which specific companies import a given grid-equipment HS code, and from where?

---

## 2. Data sources

| Source | What it provides | URL |
|--------|------------------|-----|
| **StatCan CIMT** (Canadian International Merchandise Trade) | Monthly/annual trade values & quantities by HS code, country, province, for imports / total exports / domestic exports | https://www150.statcan.gc.ca/n1/pub/71-607-x/71-607-x2021004-eng.htm |
| **StatCan IPPI** — NAPCS P73 (Electrical, electronic, audiovisual & telecom products) | Industrial Product Price Index used to deflate nominal CAD → constant CAD | StatCan table (annual averages, 2020 = 100) |
| **StatCan Canadian Importers Database (CID)** | Companies importing each HS-6 by country of origin and importer location | StatCan CID |

CIMT zip download pattern used by the extractor:
`https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_{Imp|Tot_Exp|Dom_Exp}_{YEAR}.zip`

---

## 3. Coverage at a glance

- **Years:** 2016 – 2025 (10 years).
- **Trade flows:** `imports` and `domestic_exports` (Canadian-origin exports;
  re-exports excluded). The pipeline can also handle `total_exports`.
- **Products:** **65 focus HS-6 codes** (grid equipment + upstream materials),
  expanding to ~300 HS-10 (imports) / HS-8 (domestic exports) detail codes.
  *(Note: `850431` ≤1 kVA and `850432` >1–16 kVA transformers are
  intentionally excluded — sub-grid-scale electronic/control transformers.)*
- **Partners:** 223 countries in the trade data; 71 origin countries + ~9,556
  importing companies in the importer registry (2023).
- **Currency:** values in CAD, available **nominal** or **constant 2025 CAD**
  (IPPI-deflated).

### HS classification primer
HS (Harmonized System) codes classify goods by *product type*. Granularity:
- **HS-4** = heading (e.g. `8504` transformers/converters).
- **HS-6** = internationally comparable subheading (e.g. `850423` large liquid
  transformers). This is the primary unit of analysis.
- **HS-8 / HS-10** = Canada-specific detail. **Imports report to 10 digits;
  domestic exports only to 8 digits.** So HS-10 detail (e.g. isolating a
  >100 MVA transformer) is available on the import side only.

---

## 4. The 67 focus HS-6 codes, by equipment category

Codes are assigned to grid-equipment categories (defined in
`equipment_categories.md`). Most map at HS-6; two categories are pinned to
specific HS-10/HS-8 detail codes (see §5). `⚠` marks a forced/weak fit (the
code is broad or partly non-grid — see the reasoning in `equipment_categories.md`).

| Category | HS-6 codes |
|----------|------------|
| **Large Power Transformer (≥100 MVA)** | `850423` → HS-10 `8504230030` only (imports, 2019+) |
| **Medium / Substation Transformer** | `850421`, `850422`, `850433`, `850434`; plus `850423`'s lower bands (`8504230010/20/00`, export `85042300`) |
| **High-Voltage Switchgear** | `853510`, `853529`, `853590`, `853540`⚠ |
| **Medium-Voltage Switchgear** | `853521`⚠, `853610`⚠, `853620`⚠, `853630`⚠, `853650`⚠, `853690`⚠ (8536 = ≤1 kV, technically LV, folded in) |
| **Underground / Submarine Cable** | `854460`; `854420`⚠ (coax), `854442`⚠, `854449`⚠ (LV) |
| **HVDC Converter Station** | `850440` → HS-10 high-power subset (see §5) |
| **Overhead Conductor** | `741300` (bare Cu), `761410` (ACSR), `761490` (Al), `730820`⚠ (towers) |
| **Substation reactive-power equipment** (shunt reactors, capacitor banks, SVC/STATCOM) | `853210`; `850450`⚠ (inductors), `853229`⚠, `853230`⚠, `853290`⚠ (capacitors) |
| **Protection & Control panels** | `853710`, `853720`, `853649`; `853641`⚠ (relays), `903031/032/033/039/084/089`⚠ (measuring instruments) |
| **Disconnect Switches (HV/MV)** | `853530` |
| **Raw Materials** (upstream feedstock & components) | Electrical steel `722511/519/611/619`; copper `740710/811/819/821/829`; aluminium `760410/421/429/511/519/521/529`; winding wire `854411/419`; insulators `854610/620/690`; insulating fittings `854710/720/790`; transformer/converter parts `850490`⚠ |

The full code list with curated descriptions is in `hs_priority_6.md`; the
categorization with per-code reasoning and flags is in `equipment_categories.md`.

---

## 5. HS-10 carve-outs (important methodology)

Two categories are **not** the whole HS-6 — they are pinned to specific detail
codes so the category captures only the grid-relevant slice. These apply to the
**import side only** (HS-10); domestic exports (HS-8) can't be split this way.

- **Large Power Transformer (≥100 MVA)** = HS-10 **`8504230030`** ("liquid
  dielectric transformers, >100,000 kVA") only. The rest of `850423`
  (10–59 MVA, 59–100 MVA, pre-2019 aggregate, and HS-8 exports) falls into
  *Medium / Substation Transformer*. **This series is imports-only and starts
  in 2019** (the >100 MVA band wasn't reported separately before then).

- **HVDC Converter Station** = the high-power converter HS-10 codes under
  `850440` — `8504409031/032/033/034/035/039` (rectifiers, inverters, DC/AC
  converters, ">100 A" devices) plus the catch-all `8504409099` and the HS-8
  export code `85044000`. This **excludes** PC/IT power supplies, battery/USB
  chargers, and motor speed-drive controllers (the bulk of raw `850440`).

Consequence: a category restricted to HS-10 shows **no data** for domestic
exports / pre-2019 imports where those detail codes don't exist — the dashboard
flags this explicitly.

---

## 6. Currency & price adjustment

- **Nominal CAD** — values as recorded.
- **2025 CAD (constant)** — nominal deflated by the StatCan **IPPI, NAPCS P73**
  (electrical/electronic equipment), rebased so 2025 = 1.0. Annual index
  (2020 = 100): 2016 ≈ 99.98, 2020 = 100.00, 2021 = 106.26, 2022 = 121.44,
  2023 = 128.52, 2024 = 134.35, 2025 = 142.03. Methodology in
  `Price Adjustments.md`.
- **Quantity** is shown only when a view narrows to a single HS-6 with one unit
  of measure (summing quantities across different products is meaningless).
  The main CIMT quantity unit here is `NMB` (number of units).

---

## 7. Data files & schemas

All generated outputs live in `cimt_output/`. Load with pandas.

### `cimt_output/cimt_trade_slim.parquet` — primary trade dataset (committed)
Aggregated to (year, flow, hs6, hs_full, country). ~93,000 rows.

| Column | Meaning |
|--------|---------|
| `year` | 2016–2025 |
| `flow` | `imports` / `domestic_exports` |
| `hs6` | 6-digit HS code (string) |
| `hs_full` | HS-10 (imports) or HS-8 (domestic exports) detail code |
| `hs_description` | curated HS-6 description (from `hs_priority_6.md`) |
| `hs_full_description` | official CIMT detail-code description |
| `country` | partner country code |
| `country_name` | partner country name |
| `value_cad` | trade value, nominal CAD |
| `quantity_1` | quantity in `unit_1` |
| `unit_1` | CIMT unit of measure (e.g. `NMB`) |

```python
import pandas as pd
df = pd.read_parquet("cimt_output/cimt_trade_slim.parquet")
# e.g. Canadian imports of large power transformers (>100 MVA), 2025, by country
lpt = df[(df.flow=="imports") & (df.hs_full=="8504230030") & (df.year==2025)]
lpt.groupby("country_name").value_cad.sum().sort_values(ascending=False)
```

### `cimt_output/major_importers.parquet` — importer registry (committed)
StatCan Canadian Importers Database, 2023, filtered to the focus HS-6 codes.
~25,900 rows. **No trade value** — it is a company directory.

| Column | Meaning |
|--------|---------|
| `hs6` | 6-digit HS code |
| `company` | importing company name |
| `country` | country of **origin** of the goods |
| `province`, `city`, `postal` | importer's location |
| `year` | 2023 |

### Other CSV outputs in `cimt_output/` (from the extractor)
- `cimt_trade_long.csv` — row-level long format.
- `cimt_trade_annual_pivot.csv` — HS × year value pivot.
- `cimt_trade_by_country_pivot.csv` — HS × country × year.
- `cimt_trade_summary_by_hs6.csv` — totals per HS-6.

### Source / config files (repo root)
- `hs_priority_6.md` — the 67 focus HS-6 codes + curated descriptions.
- `equipment_categories.md` — category → code mapping, reasoning, flags, carve-outs.
- `categorization.md` — older HS-4 tier grouping (superseded by the above).
- `country_coords.csv` — lat/long for the map.
- `Price Adjustments.md` — IPPI sourcing & deflation method.
- `extract_cimt_trade.py` — the extraction pipeline (downloads CIMT zips, filters
  to focus codes, writes the outputs above).
- `MajorImportersbyHS6byCountry2023.xlsx` — raw CID workbook (23 MB, gitignored;
  the slim parquet is committed instead).

---

## 8. The dashboard (`streamlit_dashboard.py`)

Run: `streamlit run streamlit_dashboard.py`. Three pages (sidebar nav):

### 📊 Trade Dashboard
Interactive trade view for the selected flow.
- **Filters:** Trade flow (imports / domestic exports); equipment **Category**
  (multi-select, drives HS selection incl. HS-10 carve-outs); HS-4 heading; HS-6
  code; HS-10/HS-8 detail (when one HS-6 is chosen, scoped to a category's
  carve-out codes); Year (single or custom range); Top-N origins; CAD basis
  (nominal / 2025).
- **Outputs:** headline metrics (total value, quantity when applicable, partner
  count, year); world **map** of partner countries (Canada = destination for
  imports, origin for exports) and a **treemap**; stacked **annual bar chart**
  (top-5 partners + Others per year); per-country origin/destination breakdown
  with drill-down; "Notable changes" 2016→2025 and a year-over-year table.
- **Selected-codes panel** showing exactly which HS-10/HS-8 codes are included
  (green) vs excluded (red) by the active category carve-out.
- **CSV export** (Excel-style button) of the exact filtered rows, respecting
  flow, category/HS, year and CAD basis.

### 🗂️ Equipment Categorization
Read-only reference. Each category rendered as a bordered **HS-4 → HS-6 → HS-10**
table (code, description, notes); forced/weak fits flagged in red. Summary
metrics (categories, HS-6 count, carve-outs, flagged count) + jump-to-category.

### 🏭 Major importers
Company-level importer registry (CID, 2023) filtered to the focus codes.
- **Filters:** Category type (maps to the category's HS-6 codes — HS-6
  granularity only, no HS-10 carve-out here); HS-6; country of origin; company
  name search.
- **Outputs:** metrics (companies, origin countries, HS-6 codes, records),
  sortable table (HS-6, description, company, imported-from, province, city),
  and a CSV export of the filtered list.

---

## 9. Key caveats & limitations

- **HS ≠ end-use.** HS codes describe product type, not application. Several
  focus codes are broad or partly non-grid; these are flagged `⚠` in
  `equipment_categories.md` with reasoning (e.g. `850440` static converters
  includes consumer power supplies; `730820` includes bridges/building steel;
  `9030xx` measuring instruments include lab/test gear).
- **HS-10 detail is imports-only.** Domestic exports stop at HS-8, so the
  >100 MVA transformer and high-power-converter carve-outs have no export series.
- **Large Power Transformer series starts 2019** (pre-2019 imports only report
  the aggregate >10 MVA band).
- **Imports vs domestic exports shouldn't be summed** — different bases; pick one.
- **Importer registry has no value/volume** — it lists *which companies* import a
  code from *which country*, not how much.
- **Category filtering on the importer page is HS-6-level only** (the CID has no
  HS-10), so carve-out categories collapse to their whole HS-6 (and `850423`
  isn't present in the CID at all).
- Quantities are only meaningful at a single-HS-6, single-unit view.

---

## 10. Quick reference — what you can ask of this data

- Canadian import/export **value or quantity** of any focus grid-equipment
  category or HS code, by **year** and **partner country**, nominal or real CAD.
- **Trends** 2016–2025, year-over-year changes, and partner concentration.
- **Supply-chain framing**: finished equipment vs upstream **Raw Materials**
  (electrical steel, copper/aluminium, insulators, winding wire).
- **Large power transformers specifically** (>100 MVA) on the import side, 2019+.
- **Which companies import** a given grid-equipment code into Canada and from
  where (2023), filterable by equipment category.

To compute precise numbers, load the parquet files in §7 and group/filter as
shown; the dashboard is a convenience layer over exactly that data.
