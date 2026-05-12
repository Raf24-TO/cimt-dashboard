# GESC Trade Data Extraction Scripts

Two Python scripts for pulling Statistics Canada data for the grid equipment
supply chain analysis. They are independent. Use one or both.

---

## 1. `extract_cimt_trade.py` (primary)

Pulls customs-based merchandise trade data (HS-coded imports and exports)
from StatCan's CIMT bulk download endpoint.

**What it does**
- Downloads annual CIMT zip files for the years and trade flows you specify.
- Filters to your priority HS codes (prefix match).
- Aggregates to HS-6 (or HS-8/HS-10) and writes long-format and pivoted CSVs.
- Caches raw zips in `./cimt_cache/` so re-runs are fast.

**Outputs**
- `cimt_trade_long.csv` - one row per HS code x year x country x flow
- `cimt_trade_annual_pivot.csv` - HS code x year totals (world-aggregated)
- `cimt_trade_summary_by_hs6.csv` - lifetime totals per HS-6 per flow
- `extraction_log.txt`

**To configure**
Edit the CONFIG block at the top of the script:
- `YEARS` - default is 2010-2026
- `FLOWS` - imports, total_exports, domestic_exports
- `PRIORITY_HS6` - the 67 codes from your Concordance are pre-loaded
- `OUTPUT_DIR`, `DOWNLOAD_CACHE`, `KEEP_RAW_ZIPS`

**Run**
```
pip install requests pandas
python extract_cimt_trade.py
```

**Disk space**
Each annual zip is roughly 30-100 MB. A 17-year run for two flows is roughly
3-5 GB cached on disk. Set `KEEP_RAW_ZIPS = False` to delete each zip after
parsing if space is tight.

---

## 2. `extract_statcan_tables.py` (companion)

Pulls table-based data via StatCan's WDS (Web Data Service) API. Use this
for NAICS shipments, IPPI, supply-use tables, or any other table identified
by Product ID (PID).

**Two modes**
- **Full table** - entire CSV download. Use for first-time exploration or
  when you want all dimensions. Tables can be large (100+ MB).
- **Vectors** - specific series only. Faster and lighter when you know
  exactly which series you want.

**To configure**
Edit the CONFIG block:
- `FULL_TABLES` - list of (PID, label) tuples. Pre-loaded:
  - `16100047` Manufacturers' shipments by NAICS
  - `18100266` IPPI monthly
  - SUPC table commented out (very large)
- `VECTORS` - list of (vector_id, label) tuples. You need to find vector
  IDs for the series you want. Easiest method: open the StatCan table page
  in your browser, click "Add/Remove data," select your series, and the
  vector IDs are shown in the URL or in the customize panel.
- `VECTOR_PERIODS` - how many recent periods (default 240, for 20 years
  of monthly data)

**Run**
```
pip install requests pandas
python extract_statcan_tables.py
```

---

## Recommended workflow for the GESC project

1. **First run (now)**
   - Run `extract_cimt_trade.py` with default config to refresh your trade
     data and add 2010-2019 history (your current pull only covers 2020+).
   - Validate the new pull against your existing `Trade Data` tab in
     `GESC_Data.xlsx`. Spot-check 3-5 HS codes for consistency.

2. **Once trade is validated**
   - Edit the script to pull HS-10 detail for HS 850421/422/423 (LPT split)
     and HS 853529 (HV switchgear) by including these in `PRIORITY_HS6` as
     longer prefixes. The script already handles this; longer codes filter
     to longer prefixes.

3. **NAICS and IPPI refresh**
   - Run `extract_statcan_tables.py` to refresh shipments and IPPI. This
     replaces the manual download step in your extraction checklist.

---

## Critical caveats to flag in the deliverable

1. **HS-6 hides the equipment classes that matter.** HS 850421/422/423 split
   transformers by kVA, not voltage class. HS-10 separates further. Without
   HS-10, you cannot distinguish LPTs (>= 100 MVA) from medium-power within
   the >10,000 kVA bucket. The script supports HS-10 - use it for the
   transformer line items.

2. **Re-exports inflate "Total Exports."** A re-exported transformer was
   imported, then shipped out without significant transformation. If you
   want Canadian-origin only, set `FLOWS = ["domestic_exports"]`.

3. **Customs data is by border crossing, not by destination of use.** A
   transformer cleared in Ontario may end up serving an Alberta utility.
   `province_clearance` is the customs port; `province_origin` (for exports)
   is where production occurred. Neither is the same as final use location.

4. **Trade data revision schedule.** StatCan revises figures up to 2 years
   after initial release. Re-run quarterly during the project and document
   which vintage of data each chart was built on.

5. **2026 data is partial.** Filter or annotate before sharing externally.
   The script does NOT detect partial-year coverage; this is on you.

6. **CIMT URL structure has been stable since ~2021.** If StatCan moves the
   files, update `CIMT_URL_TEMPLATE` at the top of the script. The Open
   Government Portal dataset pages confirm the URL each year.

---

## Adding a vector for a specific NAICS series

1. Go to the table page (e.g., 16-10-0047-01 for shipments).
2. Click "Add/Remove data."
3. Select Geography = Canada, NAICS = 335311, Variable = Total shipments.
4. Apply.
5. The customize panel shows vector IDs (typically v-numbers like v123456789).
6. Add the integer to `VECTORS` in the script with a clear label.

If you want, I can pre-populate the `VECTORS` list with the specific
series you need; just say which NAICS codes and variables.