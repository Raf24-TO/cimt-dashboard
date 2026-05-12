#!/usr/bin/env python3
"""
GESC Trade Data Extractor

Pulls Canadian merchandise trade data (HS-coded imports and exports) from
Statistics Canada's CIMT (Canadian International Merchandise Trade) bulk
download endpoint, filters to your priority HS codes, and writes a tidy
long-format CSV plus an annual pivot.

Data source: StatCan CIMT bulk files
  https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Imp_{YEAR}.zip
  https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Tot_Exp_{YEAR}.zip
  https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Dom_Exp_{YEAR}.zip

Levels of detail:
  - Imports: HS-10 (full Canadian classification)
  - Exports: HS-8 (full Canadian classification)
  - Both can be aggregated to HS-6 by truncation

USAGE
-----
1. Edit the CONFIG block below (years, HS codes, output path, flow type).
2. Run:  python extract_cimt_trade.py
3. Outputs land in OUTPUT_DIR:
     - cimt_trade_long.csv           (one row per HS code x year x country x flow)
     - cimt_trade_annual_pivot.csv   (HS code x year, value totals, world-aggregated)
     - extraction_log.txt            (run metadata, errors, file sizes)

REQUIREMENTS
------------
  pip install requests pandas

NOTES
-----
- Each annual zip is roughly 30-100 MB compressed and 200-800 MB uncompressed.
  Plan disk space accordingly. The script streams CSVs in chunks to avoid
  loading the full file into memory.
- HS codes: import codes are 10-digit, export codes are 8-digit. Truncate to
  6 digits to match the international HS-6 used in your concordance.
- The script matches HS codes by PREFIX. If you list "850421" in PRIORITY_HS6,
  it will catch all HS-10 codes starting with 850421 (e.g., 8504210020,
  8504210030, etc.). This is what you want for HS-6-level analysis.
- For HS-10 / HS-8 detail, list the longer codes directly. Prefix matching
  still applies, so "85042100" catches all 10-digit codes starting with that.

CAVEATS
-------
- 2026 will be partial-year data. The script tags the row with the file year;
  it does NOT detect partial coverage. Filter or annotate downstream.
- StatCan revises trade data after initial release. Re-running the script
  later will get updated figures for prior years.
- "Total Exports" includes re-exports. Use "Domestic Exports" if you want
  Canadian-origin only. Set EXPORT_FLOW below.
"""

import io
import re
import sys
import zipfile
import logging
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd

# ============================================================================
# CONFIG  -- edit this block
# ============================================================================

# Years to pull. CIMT bulk files exist back to 1988; recent years revised.
YEARS = list(range(2016, 2026))

# Trade flows to pull. Options: "imports", "total_exports", "domestic_exports"
FLOWS = ["imports"]

# Priority HS codes are read from this file at run time. Prefix match — list
# HS-6 for category-level, HS-8/HS-10 for finer resolution. One code per line;
# blank lines, '#' comments, and a leading "HS " prefix are all tolerated.
HS_PRIORITY_FILE = Path("./hs_priority_6.md")

OUTPUT_DIR = Path("./cimt_output")
DOWNLOAD_CACHE = Path("./cimt_cache")  # raw zips kept here so re-runs are fast
KEEP_RAW_ZIPS = True  # set False if disk space is tight

# Aggregation level for the pivot output.
# Options: 6 (HS-6), 8 (HS-8), 10 (HS-10, imports only)
PIVOT_HS_LEVEL = 6

# Network
USER_AGENT = "GESC-research-extract/1.0 (Transition Accelerator)"
TIMEOUT_SECONDS = 300
MAX_RETRIES = 3

# ============================================================================
# END CONFIG
# ============================================================================

# CIMT bulk file URL pattern. This URL pattern has been stable since ~2021.
# If StatCan moves the files, update this single template.
CIMT_URL_TEMPLATE = (
    "https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/"
    "CIMT-CICM_{flow_token}_{year}.zip"
)

FLOW_TOKENS = {
    "imports": "Imp",
    "total_exports": "Tot_Exp",
    "domestic_exports": "Dom_Exp",
}

# Set up logging
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_CACHE.mkdir(parents=True, exist_ok=True)
log_path = OUTPUT_DIR / "extraction_log.txt"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(log_path, mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("cimt")


def download_zip(year: int, flow: str) -> Path | None:
    """Download a yearly CIMT zip to cache. Returns local path, or None on failure."""
    flow_token = FLOW_TOKENS[flow]
    url = CIMT_URL_TEMPLATE.format(flow_token=flow_token, year=year)
    local_path = DOWNLOAD_CACHE / f"CIMT-CICM_{flow_token}_{year}.zip"

    if local_path.exists() and local_path.stat().st_size > 1024:
        log.info(f"  cached: {local_path.name} ({local_path.stat().st_size:,} bytes)")
        return local_path

    log.info(f"  downloading: {url}")
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS, stream=True)
            if r.status_code == 404:
                log.warning(f"  not found (404): {flow} {year}. Probably year not yet published.")
                return None
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            log.info(f"  saved: {local_path.name} ({local_path.stat().st_size:,} bytes)")
            return local_path
        except requests.exceptions.RequestException as e:
            log.warning(f"  attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                log.error(f"  giving up on {flow} {year}")
                return None
    return None


def parse_csv_in_zip(zip_path: Path, hs_prefixes: list[str], flow: str, year: int) -> pd.DataFrame:
    """
    Extract priority HS rows from a CIMT zip. CIMT CSVs have varying column
    names across vintages, so we detect the schema from the header.

    Typical CIMT import CSV columns (post-2021 schema):
      Year, Month, HS6, HS10, HSDescription, Country, ProvinceOrigin,
      ProvinceClearance, State, Quantity1, Unit1, Quantity2, Unit2, Value
    Export CSVs have HS8 instead of HS10.
    """
    log.info(f"  parsing: {zip_path.name}")
    all_chunks = []

    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            log.error(f"  no CSV inside {zip_path.name}")
            return pd.DataFrame()

        # CIMT zips contain multiple CSVs at different aggregation levels
        # (HS10/HS8 detail, HS6, HS2). Reading more than one double-counts.
        detail_csv = _pick_detail_csv(zf, csv_names)
        if detail_csv is None:
            log.error(f"  no detail-level CSV found in {zip_path.name}")
            return pd.DataFrame()
        log.info(f"  detail file: {detail_csv}")

        with zf.open(detail_csv) as f:
            try:
                reader = pd.read_csv(
                    f, chunksize=200_000, dtype=str,
                    encoding="utf-8", on_bad_lines="warn", low_memory=False
                )
                chunks = list(_filter_chunks(reader, hs_prefixes, flow, year))
            except UnicodeDecodeError:
                with zf.open(detail_csv) as f2:
                    reader = pd.read_csv(
                        f2, chunksize=200_000, dtype=str,
                        encoding="latin-1", on_bad_lines="warn", low_memory=False
                    )
                    chunks = list(_filter_chunks(reader, hs_prefixes, flow, year))
            all_chunks.extend(chunks)

    if not all_chunks:
        return pd.DataFrame()
    df = pd.concat(all_chunks, ignore_index=True)
    log.info(f"  matched rows: {len(df):,}")
    return df


def _filter_chunks(reader, hs_prefixes, flow, year):
    """Generator: filter each chunk to priority HS prefixes and tag with flow/year."""
    prefix_tuple = tuple(hs_prefixes)
    for chunk in reader:
        # Locate the HS code column. CIMT uses different names across years.
        hs_col = _find_hs_column(chunk.columns)
        if hs_col is None:
            log.warning(f"  no HS column found in columns: {list(chunk.columns)[:10]}")
            continue
        # Strip whitespace and ensure string
        chunk[hs_col] = chunk[hs_col].astype(str).str.strip().str.replace(".", "", regex=False)
        # Match by prefix
        mask = chunk[hs_col].str.startswith(prefix_tuple)
        if mask.any():
            sub = chunk.loc[mask].copy()
            sub["_flow"] = flow
            sub["_year_file"] = year
            sub["_hs_full"] = sub[hs_col]
            sub["_hs6"] = sub[hs_col].str[:6]
            yield sub


_CTY_LINE = re.compile(r"^([A-Z]{2})\s+\d+\s+\d{6}\s+\d{6}\s+(.+?)\s{3,}")
_HS10_LINE = re.compile(r"^(\d{10})\s+(\d{6})\s+(\d{6})\s+(\S{1,5})\s+(.+?)\s{3,}")


def _load_country_names(zip_path: Path) -> dict[str, str]:
    """Read CIMT's bundled ODPF_6_CtyDesc.TXT to map 2-letter country code → English name.
    Lines are fixed-width: code, numeric id, two YYYYMM dates, English name, French name."""
    names: dict[str, str] = {}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            cty_files = [n for n in zf.namelist() if n.lower().endswith("ctydesc.txt")]
            if not cty_files:
                return names
            with zf.open(cty_files[0]) as f:
                for raw in f:
                    line = raw.decode("latin-1", errors="replace")
                    m = _CTY_LINE.match(line)
                    if m:
                        names[m.group(1)] = m.group(2).strip()
    except Exception as e:
        log.warning(f"  could not load country names from {zip_path.name}: {e}")
    return names


def _load_hs10_descriptions(zip_path: Path) -> dict[str, str]:
    """Read CIMT's bundled ODPF_1_HS10Desc.TXT → HS-10 code → English description.
    Codes appear multiple times with different validity periods; keep the one
    with the latest end period so retired codes don't shadow current ones."""
    desc: dict[str, str] = {}
    end_per: dict[str, str] = {}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            files = [n for n in zf.namelist() if n.lower().endswith("hs10desc.txt")]
            if not files:
                return desc
            with zf.open(files[0]) as f:
                for raw in f:
                    line = raw.decode("latin-1", errors="replace")
                    m = _HS10_LINE.match(line)
                    if not m:
                        continue
                    code, _start, end, _unit, eng = m.groups()
                    if code not in end_per or end > end_per[code]:
                        end_per[code] = end
                        desc[code] = eng.strip()
    except Exception as e:
        log.warning(f"  could not load HS-10 descriptions from {zip_path.name}: {e}")
    return desc


def _pick_detail_csv(zf: zipfile.ZipFile, csv_names: list[str]) -> str | None:
    """Among CIMT CSVs in a zip, return the one with the most granular HS column.
    CIMT zips ship parallel files at HS10/HS8/HS6/HS2 aggregation; using more
    than one double-counts the same trade."""
    rank = {"hs10": 4, "hs8": 3, "hs6": 2, "hs2": 1}
    best_name = None
    best_rank = -1
    for name in csv_names:
        try:
            with zf.open(name) as f:
                header = f.readline().decode("utf-8", errors="replace")
        except Exception:
            continue
        for col in header.split(","):
            base = col.strip().strip('"').lower().split("/")[0].strip()
            if base in rank and rank[base] > best_rank:
                best_rank = rank[base]
                best_name = name
                break
    return best_name


def _find_hs_column(columns) -> str | None:
    """CIMT column names vary. Find the most granular HS column available."""
    cols_lower = {c.lower(): c for c in columns}
    # Preference order: HS10 > HS8 > HS6 > generic 'hs'
    for key in ("hs10", "hs_10", "hscode10", "hs10code"):
        if key in cols_lower:
            return cols_lower[key]
    for key in ("hs8", "hs_8", "hscode8", "hs8code"):
        if key in cols_lower:
            return cols_lower[key]
    for key in ("hs6", "hs_6", "hscode6", "hs6code"):
        if key in cols_lower:
            return cols_lower[key]
    # Fallback: any column literally named 'HS' or starting with 'HS'
    for col in columns:
        if col.lower() == "hs":
            return col
    for col in columns:
        if col.lower().startswith("hs") and len(col) <= 8:
            return col
    return None


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names so all years and flows can be concatenated."""
    if df.empty:
        return df

    cols_lower = {c.lower(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n.lower() in cols_lower:
                return cols_lower[n.lower()]
        return None

    rename = {}
    if (c := pick("Value", "TradeValue", "Trade_Value", "Value_CAD", "Value/Valeur")):
        rename[c] = "value_cad"
    if (c := pick("Quantity1", "Quantity_1", "Qty1", "Quantity", "Quantity/Quantité")):
        rename[c] = "quantity_1"
    if (c := pick("Unit1", "Unit_1", "UOM1", "Unit", "Unit of Measure/Unité de Mesure")):
        rename[c] = "unit_1"
    if (c := pick("Quantity2", "Quantity_2", "Qty2")):
        rename[c] = "quantity_2"
    if (c := pick("Unit2", "Unit_2", "UOM2")):
        rename[c] = "unit_2"
    if (c := pick("Country", "Partner", "TradingPartner", "CountryName", "Country/Pays")):
        rename[c] = "country"
    if (c := pick("Year")):
        rename[c] = "year"
    if (c := pick("Month")):
        rename[c] = "month"
    if (c := pick("HSDescription", "Description", "HS_Description", "CommodityDescription")):
        rename[c] = "hs_description"
    if (c := pick("ProvinceClearance", "ProvinceOfClearance", "Province")):
        rename[c] = "province_clearance"
    if (c := pick("ProvinceOrigin", "ProvinceOfOrigin")):
        rename[c] = "province_origin"
    if (c := pick("State", "USState", "State/État")):
        rename[c] = "us_state"

    df = df.rename(columns=rename)

    # Newer CIMT schema combines year and month into one YYYYMM column.
    if (ym_col := pick("YearMonth", "Year_Month", "YearMonth/AnnéeMois")):
        ym = df[ym_col].astype(str).str.strip()
        df["year"] = pd.to_numeric(ym.str[:4], errors="coerce")
        df["month"] = pd.to_numeric(ym.str[4:6], errors="coerce")

    # Coerce numerics
    for col in ("value_cad", "quantity_1", "quantity_2"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Year fallback
    if "year" not in df.columns:
        df["year"] = df["_year_file"]
    else:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(df["_year_file"]).astype(int)

    # Standard column order
    keep_cols = [
        "year", "month", "_flow", "_hs6", "_hs_full", "hs_description",
        "country", "province_origin", "province_clearance", "us_state",
        "value_cad", "quantity_1", "unit_1", "quantity_2", "unit_2",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].rename(columns={"_flow": "flow", "_hs6": "hs6", "_hs_full": "hs_full"})
    return df


def _load_hs_codes(path: Path) -> tuple[list[str], dict[str, str]]:
    """Read HS code prefixes from a plain-text/markdown file. Tolerates a leading
    'HS' prefix, embedded dots/spaces, blank lines, and '#' or '//' comments.
    A line may carry an optional description after a ';' or tab separator."""
    if not path.exists():
        log.error(f"HS priority file not found: {path.resolve()}")
        sys.exit(1)
    codes: list[str] = []
    descriptions: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        desc = ""
        for sep in (";", "\t"):
            if sep in line:
                code_part, _, desc_part = line.partition(sep)
                line, desc = code_part.strip(), desc_part.strip()
                break
        if line[:2].upper() == "HS":
            line = line[2:].strip()
        line = line.replace(".", "").replace(" ", "")
        if line.isdigit():
            codes.append(line)
            if desc:
                descriptions[line] = desc
        else:
            log.warning(f"  ignored non-numeric HS line: {raw!r}")
    return codes, descriptions


def main():
    log.info("=" * 70)
    log.info(f"GESC trade data extraction started {datetime.now().isoformat(timespec='seconds')}")
    log.info(f"Years: {YEARS[0]}-{YEARS[-1]}  ({len(YEARS)} years)")
    log.info(f"Flows: {FLOWS}")

    hs_prefixes, hs_descriptions = _load_hs_codes(HS_PRIORITY_FILE)
    if not hs_prefixes:
        log.error(f"No HS codes parsed from {HS_PRIORITY_FILE}")
        sys.exit(1)
    log.info(
        f"HS code prefixes: {len(hs_prefixes)} (from {HS_PRIORITY_FILE}), "
        f"descriptions: {len(hs_descriptions)}"
    )
    log.info(f"Output dir: {OUTPUT_DIR.resolve()}")
    log.info("=" * 70)

    all_dfs = []
    country_names: dict[str, str] = {}
    hs10_descriptions: dict[str, str] = {}
    for flow in FLOWS:
        for year in YEARS:
            log.info(f"--- {flow} {year} ---")
            zip_path = download_zip(year, flow)
            if zip_path is None:
                continue
            if not country_names:
                country_names = _load_country_names(zip_path)
                if country_names:
                    log.info(f"  loaded {len(country_names)} country names")
            if not hs10_descriptions:
                hs10_descriptions = _load_hs10_descriptions(zip_path)
                if hs10_descriptions:
                    log.info(f"  loaded {len(hs10_descriptions):,} HS-10 descriptions")
            df = parse_csv_in_zip(zip_path, hs_prefixes, flow, year)
            if not df.empty:
                df = normalize(df)
                all_dfs.append(df)
            if not KEEP_RAW_ZIPS:
                zip_path.unlink(missing_ok=True)

    if not all_dfs:
        log.error("No data extracted. Check network access and HS code list.")
        sys.exit(1)

    long_df = pd.concat(all_dfs, ignore_index=True)
    log.info(f"Total rows extracted: {len(long_df):,}")

    # Pivot HS level (used by both annual and per-country pivots).
    if PIVOT_HS_LEVEL == 6:
        long_df["hs_pivot"] = long_df["hs6"]
    else:
        long_df["hs_pivot"] = long_df["hs_full"].str[:PIVOT_HS_LEVEL]

    # Join human-readable country names if we loaded a lookup.
    if country_names and "country" in long_df.columns:
        long_df["country_name"] = long_df["country"].map(country_names)

    # Join user-supplied HS descriptions (overrides any CIMT-provided one).
    if hs_descriptions:
        long_df["hs_description"] = long_df["hs6"].map(hs_descriptions)

    # Write long-format output
    long_csv = OUTPUT_DIR / "cimt_trade_long.csv"
    long_df.to_csv(long_csv, index=False)
    log.info(f"Wrote: {long_csv}  ({long_csv.stat().st_size:,} bytes)")

    # Annual pivot: HS code x year (totals across all countries).
    pivot = (
        long_df.groupby(["hs_pivot", "year", "flow"], as_index=False)["value_cad"]
        .sum()
        .pivot_table(
            index=["hs_pivot", "flow"], columns="year", values="value_cad", fill_value=0
        )
        .reset_index()
    )
    if hs_descriptions:
        pivot.insert(2, "hs_description", pivot["hs_pivot"].map(hs_descriptions))
    pivot_csv = OUTPUT_DIR / "cimt_trade_annual_pivot.csv"
    pivot.to_csv(pivot_csv, index=False)
    log.info(f"Wrote: {pivot_csv}  ({pivot_csv.stat().st_size:,} bytes)")

    # Per-country pivot: HS code x origin country -> annual totals + grand total.
    if "country" in long_df.columns:
        country_pivot = (
            long_df.groupby(["hs_pivot", "flow", "country", "year"], as_index=False)["value_cad"]
            .sum()
            .pivot_table(
                index=["hs_pivot", "flow", "country"],
                columns="year",
                values="value_cad",
                fill_value=0,
            )
            .reset_index()
        )
        year_cols = [y for y in YEARS if y in country_pivot.columns]
        country_pivot["total_value_cad"] = country_pivot[year_cols].sum(axis=1)
        if country_names:
            country_pivot["country_name"] = country_pivot["country"].map(country_names)
        if hs_descriptions:
            country_pivot["hs_description"] = country_pivot["hs_pivot"].map(hs_descriptions)
        # Drop rows that contributed nothing (all-zero across years).
        country_pivot = country_pivot[country_pivot["total_value_cad"] > 0]
        # Sort: largest origin first within each HS code.
        country_pivot = country_pivot.sort_values(
            ["hs_pivot", "flow", "total_value_cad"], ascending=[True, True, False]
        )
        out_cols = ["hs_pivot"]
        if "hs_description" in country_pivot.columns:
            out_cols.append("hs_description")
        out_cols.extend(["flow", "country"])
        if "country_name" in country_pivot.columns:
            out_cols.append("country_name")
        out_cols.extend(year_cols)
        out_cols.append("total_value_cad")
        country_pivot = country_pivot[out_cols]
        country_pivot_csv = OUTPUT_DIR / "cimt_trade_by_country_pivot.csv"
        country_pivot.to_csv(country_pivot_csv, index=False)
        log.info(f"Wrote: {country_pivot_csv}  ({country_pivot_csv.stat().st_size:,} bytes)")

    # Summary by HS6 across all years
    summary = (
        long_df.groupby(["hs6", "flow"], as_index=False)["value_cad"]
        .agg(["sum", "count"])
        .reset_index()
        .rename(columns={"sum": "total_value_cad", "count": "row_count"})
    )
    if hs_descriptions:
        summary.insert(1, "hs_description", summary["hs6"].map(hs_descriptions))
    summary_csv = OUTPUT_DIR / "cimt_trade_summary_by_hs6.csv"
    summary.to_csv(summary_csv, index=False)
    log.info(f"Wrote: {summary_csv}")

    # Slim parquet — small enough to commit to git for cloud-deployed dashboards.
    # Aggregated to (year, hs6, hs_full, country) so the dashboard can drill
    # from HS-6 to HS-10. Unit is constant per hs_full in CIMT, so summing
    # quantity within an hs_full group is safe.
    slim_cols = ["year", "hs6", "hs_full", "country"]
    agg_dict = {"value_cad": "sum"}
    if "quantity_1" in long_df.columns:
        agg_dict["quantity_1"] = "sum"
    slim = long_df.groupby(slim_cols, as_index=False, dropna=False).agg(agg_dict)
    if "hs_description" in long_df.columns:
        slim["hs_description"] = slim["hs6"].map(
            long_df.drop_duplicates("hs6").set_index("hs6")["hs_description"]
        )
    if hs10_descriptions:
        slim["hs_full_description"] = slim["hs_full"].map(hs10_descriptions)
    if "country_name" in long_df.columns:
        slim["country_name"] = slim["country"].map(
            long_df.dropna(subset=["country_name"])
            .drop_duplicates("country")
            .set_index("country")["country_name"]
        )
    if "unit_1" in long_df.columns:
        slim["unit_1"] = slim["hs_full"].map(
            long_df.dropna(subset=["unit_1"])
            .drop_duplicates("hs_full")
            .set_index("hs_full")["unit_1"]
        )
    slim_parquet = OUTPUT_DIR / "cimt_trade_slim.parquet"
    slim.to_parquet(slim_parquet, index=False)
    log.info(f"Wrote: {slim_parquet}  ({slim_parquet.stat().st_size:,} bytes)")

    # Sanity flags
    missing_codes = set(c[:6] for c in hs_prefixes) - set(long_df["hs6"].unique())
    if missing_codes:
        log.warning(
            f"HS codes with no rows in any year/flow ({len(missing_codes)}): "
            f"{sorted(missing_codes)}"
        )
        log.warning("  Possible causes: code retired, no trade, or column-name mismatch.")

    log.info("Done.")


if __name__ == "__main__":
    main()