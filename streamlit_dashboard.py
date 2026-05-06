"""
Canadian Imports Dashboard (CIMT)

Reads cimt_output/cimt_trade_long.csv produced by extract_cimt_trade.py and
shows a flow map: Canada hub + sized circles per origin country + connecting
lines.

Run:
    pip install streamlit plotly pandas
    streamlit run streamlit_dashboard.py
"""

from pathlib import Path
import math

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
LONG_PARQUET = ROOT / "cimt_output" / "cimt_trade_slim.parquet"
LONG_CSV = ROOT / "cimt_output" / "cimt_trade_long.csv"
COORDS_CSV = ROOT / "country_coords.csv"
HS4_PRIORITY_FILE = ROOT / "hs_priority_4"
HS6_PRIORITY_FILE = ROOT / "hs_priority_6.md"
CATEGORIZATION_FILE = ROOT / "categorization.md"
LOGO_PATH = ROOT / "assets" / "transition_accelerator.png"
CANADA_GEOJSON = ROOT / "assets" / "canada.geojson"

CANADA_LAT, CANADA_LON = 56.130, -106.347
ALL = "All"

# Statistics Canada IPPI — NAPCS P73 (Electrical, electronic, audiovisual and
# telecommunication products), Canada, annual averages. Index base 2020 = 100.
# See Price Adjustments.md for sourcing and methodology.
IPPI_P73: dict[int, float] = {
    2016:  99.98,
    2017:  99.25,
    2018:  99.58,
    2019: 100.53,
    2020: 100.00,
    2021: 106.26,
    2022: 121.44,
    2023: 128.52,
    2024: 134.35,
    2025: 142.03,
}
IPPI_BASE_YEAR = 2025
NOMINAL_BASIS = "Nominal CAD"
REAL_BASIS = "2025 CAD"


def deflation_factors() -> dict[int, float]:
    base = IPPI_P73[IPPI_BASE_YEAR]
    return {y: base / v for y, v in IPPI_P73.items()}


def apply_deflation(frame: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Scale ``value_cad`` to base-year dollars when ``basis == REAL_BASIS``.

    Years outside the IPPI coverage table are left at nominal value.
    Returns a new frame; the caller's frame is not mutated.
    """
    if basis != REAL_BASIS:
        return frame
    factor = frame["year"].map(deflation_factors()).fillna(1.0).astype(float)
    return frame.assign(value_cad=frame["value_cad"] * factor)


@st.cache_data(show_spinner="Loading trade data…")
def load_data() -> pd.DataFrame:
    """Prefer the slim Parquet (committed to git for cloud deploy); fall back to
    the full CSV produced by extract_cimt_trade.py for local development."""
    if LONG_PARQUET.exists():
        df = pd.read_parquet(LONG_PARQUET)
    else:
        df = pd.read_csv(
            LONG_CSV,
            dtype={"hs6": str, "hs_full": str, "country": str},
            low_memory=False,
        )
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value_cad"] = pd.to_numeric(df["value_cad"], errors="coerce").fillna(0)
    return df


@st.cache_data
def load_coords() -> pd.DataFrame:
    return pd.read_csv(COORDS_CSV)


@st.cache_data
def load_canada_geojson() -> dict | None:
    if not CANADA_GEOJSON.exists():
        return None
    import json
    return json.loads(CANADA_GEOJSON.read_text(encoding="utf-8"))


@st.cache_data
def load_hs_priority(path: Path) -> tuple[list[str], dict[str, str]]:
    """Read HS code prefixes + optional descriptions from a text/md file."""
    if not path.exists():
        return [], {}
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
    return codes, descriptions


@st.cache_data
def load_categorization(path: Path) -> list[dict]:
    """Parse categorization.md into [{tier, hs4, label}] entries.

    Recognizes ``## <Tier name>: ...`` headings and the first two columns of
    each markdown table row beneath them (HS-4 code + plain-English label).
    """
    if not path.exists():
        return []
    out: list[dict] = []
    current_tier: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## ") and not line.startswith("###"):
            title = line[3:].strip()
            if title.lower().startswith("notes"):
                current_tier = None
                continue
            current_tier = title.split(":", 1)[0].strip()
            continue
        if not current_tier or not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 2:
            continue
        code = cols[0].replace(" ", "")
        if not code.isdigit() or len(code) < 4:
            continue
        out.append({"tier": current_tier, "hs4": code, "label": cols[1]})
    return out


def fmt_cad(v: float) -> str:
    if v >= 1e9:
        return f"CAD ${v/1e9:,.2f}B"
    if v >= 1e6:
        return f"CAD ${v/1e6:,.2f}M"
    if v >= 1e3:
        return f"CAD ${v/1e3:,.1f}K"
    return f"CAD ${v:,.0f}"


def main():
    st.set_page_config(
        page_title="Strengthening Canada's Grid Equipment Supply Chain",
        layout="wide",
    )

    # Allow long filter labels (Category / HS-4 / HS-6) to wrap onto multiple
    # lines instead of being truncated with ellipsis. BaseWeb's option items
    # nest the text in inner <div>s with their own white-space/overflow rules,
    # so we have to override the descendants too.
    st.markdown(
        """
        <style>
        [data-baseweb="popover"] li[role="option"],
        [data-baseweb="popover"] li[role="option"] *,
        ul[role="listbox"] li,
        ul[role="listbox"] li * {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            word-break: break-word !important;
            line-height: 1.35 !important;
            height: auto !important;
            max-width: none !important;
        }
        [data-baseweb="popover"] li[role="option"] {
            padding-top: 6px !important;
            padding-bottom: 6px !important;
            min-height: 36px !important;
        }
        /* Currently-selected value in a selectbox */
        [data-baseweb="select"] [data-baseweb="tag"],
        [data-baseweb="select"] div[role="combobox"],
        [data-baseweb="select"] div[role="combobox"] > div,
        [data-baseweb="select"] div[role="combobox"] * {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            line-height: 1.3 !important;
            height: auto !important;
        }
        /* Remove Streamlit's default ~5rem bottom padding on the main
           content container, so the in-flow footer sits flush at the bottom
           edge of the page instead of leaving a big empty band below it. */
        section.main > div.block-container,
        [data-testid="stMain"] > div.block-container,
        .main .block-container {
            padding-bottom: 0 !important;
        }
        /* 13" laptop tweaks — tighten vertical rhythm so the dashboard fits
           in a single screen without aggressive scrolling. */
        @media (max-height: 850px) {
            section.main > div.block-container,
            [data-testid="stMain"] > div.block-container,
            .main .block-container {
                padding-top: 1rem !important;
            }
            h1 { font-size: 1.6rem !important; line-height: 1.2 !important; }
            h2 { font-size: 1.2rem !important; }
            h3 { font-size: 1.05rem !important; }
            [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
            [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
            [data-testid="stCaptionContainer"] { font-size: 0.78rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    title_col, basis_col = st.columns([4, 1])
    with title_col:
        st.title("Strengthening Canada's Grid Equipment Supply Chain")
        st.caption("Canadian Imports — CIMT")
    with basis_col:
        cad_basis = st.radio(
            "CAD basis",
            options=[NOMINAL_BASIS, REAL_BASIS],
            index=0,
            horizontal=True,
            help=(
                "Nominal CAD: as-recorded values. "
                "2025 CAD: deflated using the StatCan IPPI for NAPCS P73 "
                "(electrical/electronic equipment). See Price Adjustments.md."
            ),
        )
    basis_label = "nominal CAD" if cad_basis == NOMINAL_BASIS else "2025 CAD"

    if not LONG_PARQUET.exists() and not LONG_CSV.exists():
        st.error(
            f"Data file not found at either {LONG_PARQUET} or {LONG_CSV}.\n\n"
            "Run `python extract_cimt_trade.py` first to generate the trade data."
        )
        st.stop()

    df = load_data()
    coords = load_coords()

    years_avail = sorted(df["year"].dropna().unique().tolist())
    hs_avail = (
        df[["hs6", "hs_description"]]
        .drop_duplicates("hs6")
        .sort_values("hs6")
    )
    hs6_desc = dict(zip(hs_avail["hs6"], hs_avail["hs_description"].fillna("")))
    all_hs6 = hs_avail["hs6"].tolist()

    # HS-4 codes from the priority file; fall back to HS-4 prefixes that exist
    # in the data when descriptions aren't available.
    hs4_codes, hs4_desc = load_hs_priority(HS4_PRIORITY_FILE)
    hs4_in_data = sorted({c[:4] for c in all_hs6})
    hs4_codes = [c for c in hs4_codes if c in hs4_in_data] or hs4_in_data

    # Plain-English categories from categorization.md, scoped to HS-4 codes
    # that actually appear in the data.
    categories = [
        c for c in load_categorization(CATEGORIZATION_FILE) if c["hs4"] in set(hs4_in_data)
    ]
    cat_to_hs4 = {c["label"]: c["hs4"] for c in categories}
    cat_to_tier = {c["label"]: c["tier"] for c in categories}

    # ------------------------------------------------------------------
    # Sidebar filters
    # ------------------------------------------------------------------
    with st.sidebar:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), use_container_width=True)
        else:
            st.caption(
                f"Logo placeholder — save the Transition Accelerator banner to "
                f"`{LOGO_PATH.relative_to(ROOT)}` to display it here."
            )

        st.header("Filters")

        # Reusable "All vs specifics" auto-deselect logic, parameterized by
        # the session-state keys used by each multiselect.
        def _make_all_or_specific_callback(state_key: str, prev_key: str):
            def _cb() -> None:
                sel = list(st.session_state.get(state_key, []) or [])
                prev = list(st.session_state.get(prev_key, [ALL]))
                if ALL in sel and ALL not in prev:
                    new_sel = [ALL]
                elif ALL in sel and any(c != ALL for c in sel):
                    new_sel = [c for c in sel if c != ALL]
                elif not sel:
                    new_sel = [ALL]
                else:
                    new_sel = sel
                st.session_state[state_key] = new_sel
                st.session_state[prev_key] = new_sel
            return _cb

        # ---- Tier filter ------------------------------------------------
        tiers_avail = sorted({c["tier"] for c in categories})
        if "tier_select" not in st.session_state:
            st.session_state["tier_select"] = [ALL]
        sel_tiers_raw = st.multiselect(
            "Tier",
            options=[ALL] + tiers_avail,
            key="tier_select",
            on_change=_make_all_or_specific_callback("tier_select", "tier_prev"),
            help=(
                "High-level grouping from categorization.md. "
                "Filters the Category list below."
            ),
        )
        st.session_state.setdefault("tier_prev", list(sel_tiers_raw))
        if ALL in sel_tiers_raw or not sel_tiers_raw:
            sel_tiers = set(tiers_avail)
        else:
            sel_tiers = {t for t in sel_tiers_raw if t != ALL}

        # ---- Category filter (scoped by Tier) ---------------------------
        visible_categories = [c for c in categories if c["tier"] in sel_tiers]
        if "category_select" not in st.session_state:
            st.session_state["category_select"] = [ALL]
        sel_categories_raw = st.multiselect(
            "Category",
            options=[ALL] + [c["label"] for c in visible_categories],
            format_func=lambda c: c,
            key="category_select",
            on_change=_make_all_or_specific_callback(
                "category_select", "category_prev"
            ),
            help=(
                "Grid-equipment categories. Pick one or several — the "
                "matching HS-4 codes are used automatically."
            ),
        )
        st.session_state.setdefault("category_prev", list(sel_categories_raw))

        if ALL in sel_categories_raw or not sel_categories_raw:
            sel_categories = []
        else:
            sel_categories = [c for c in sel_categories_raw if c != ALL]

        if sel_categories:
            selected_hs4_set = {cat_to_hs4[c] for c in sel_categories}
            sel_hs4 = ALL  # individual HS-4 picker is hidden when categories rule
            codes_str = ", ".join(f"`{h}`" for h in sorted(selected_hs4_set))
            st.markdown(
                f"<div style='color:#444;font-size:13px;margin:4px 0 8px;'>"
                f"<b>HS-4:</b> {codes_str} "
                f"<span style='color:#888;'>(from {len(sel_categories)} "
                f"categor{'ies' if len(sel_categories) != 1 else 'y'})</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            selected_hs4_set = None
            sel_hs4 = st.selectbox(
                "HS-4 (heading)",
                options=[ALL] + hs4_codes,
                format_func=lambda c: c if c == ALL else f"{c} — {hs4_desc.get(c, '')}",
            )

        # HS-6 options scoped by either the categories' HS-4 set or the
        # individual HS-4 picker.
        if selected_hs4_set:
            visible_hs6 = [c for c in all_hs6 if c[:4] in selected_hs4_set]
        elif sel_hs4 == ALL:
            visible_hs6 = all_hs6
        else:
            visible_hs6 = [c for c in all_hs6 if c.startswith(sel_hs4)]

        if "hs6_select" not in st.session_state:
            st.session_state["hs6_select"] = [ALL]
        sel_hs_raw = st.multiselect(
            "HS-6 code",
            options=[ALL] + visible_hs6,
            format_func=lambda c: c if c == ALL else f"{c} — {hs6_desc.get(c, '')}",
            key="hs6_select",
            on_change=_make_all_or_specific_callback("hs6_select", "hs6_prev"),
        )
        st.session_state.setdefault("hs6_prev", list(sel_hs_raw))
        st.caption(
            "**HS** (Harmonized System) is the 6-digit international product "
            "code used in customs declarations. It overlaps in scope with "
            "**NAICS / NAPCS** (the StatCan industry / product classifications) "
            "but is organized by *product type* rather than *industry*, so "
            "exact one-to-one mapping isn't possible."
        )
        # 'All' (or empty) expands to everything visible.
        if ALL in sel_hs_raw or not sel_hs_raw:
            sel_hs = visible_hs6
        else:
            sel_hs = [c for c in sel_hs_raw if c != ALL]

        CUSTOM_RANGE = "Custom range…"
        year_options = list(years_avail) + [CUSTOM_RANGE]
        sel_year_choice = st.selectbox(
            "Year",
            options=year_options,
            index=len(years_avail) - 1 if years_avail else 0,
            format_func=lambda y: y if y == CUSTOM_RANGE else str(int(y)),
        )
        if sel_year_choice == CUSTOM_RANGE and years_avail:
            min_y, max_y = int(min(years_avail)), int(max(years_avail))
            if min_y == max_y:
                sel_years = [min_y]
                st.caption(f"Only one year available: {min_y}")
            else:
                default_lo = max(min_y, max_y - 4)
                year_range = st.slider(
                    "Year range",
                    min_value=min_y,
                    max_value=max_y,
                    value=(default_lo, max_y),
                    step=1,
                )
                sel_years = [
                    int(y) for y in years_avail
                    if year_range[0] <= int(y) <= year_range[1]
                ]
        else:
            sel_years = [int(sel_year_choice)] if sel_year_choice is not None else []

        top_n = st.slider(
            "Top N origins on map", min_value=5, max_value=100, value=30, step=5
        )
        log_size = st.checkbox(
            "Log-scale marker sizes",
            value=False,
            help=(
                "Off (default): flag area is proportional to import value. "
                "On: log scaling compresses the range so small origins are still visible."
            ),
        )

        st.divider()
        show_ippi = st.checkbox(
            "Show IPPI deflator table",
            value=False,
            help="Reveal the StatCan IPPI values used to convert nominal → 2025 CAD.",
        )
        if show_ippi:
            ippi_years = list(IPPI_P73.items())
            ippi_table = pd.DataFrame(
                [
                    {
                        "Year": y,
                        "IPPI": v,
                        "YoY": (
                            None if i == 0
                            else (v / ippi_years[i - 1][1] - 1)
                        ),
                        f"× {IPPI_BASE_YEAR}": IPPI_P73[IPPI_BASE_YEAR] / v,
                    }
                    for i, (y, v) in enumerate(ippi_years)
                ]
            )
            st.dataframe(
                ippi_table,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Year": st.column_config.NumberColumn(format="%d", width="small"),
                    "IPPI": st.column_config.NumberColumn(format="%.2f", width="small"),
                    "YoY": st.column_config.NumberColumn(format="percent", width="small"),
                    f"× {IPPI_BASE_YEAR}": st.column_config.NumberColumn(
                        format="%.3f", width="small"
                    ),
                },
            )
            st.caption(
                "StatCan IPPI · NAPCS P73 (Electrical, electronic, audiovisual "
                "and telecommunication products), Canada, annual avg, 2020 = 100."
            )

    if not sel_years or not sel_hs:
        st.warning("Pick a year (or year range) and at least one HS code.")
        st.stop()

    year_label = (
        f"{min(sel_years)}–{max(sel_years)}" if len(sel_years) > 1 else str(sel_years[0])
    )

    # ------------------------------------------------------------------
    # Filter & aggregate
    # ------------------------------------------------------------------
    mask = df["year"].isin(sel_years) & df["hs6"].isin(sel_hs)
    view = apply_deflation(df.loc[mask], cad_basis)

    if view.empty:
        st.info("No data for the selected filters.")
        st.stop()

    # Years in the user's selection that fall outside IPPI coverage.
    if cad_basis == REAL_BASIS:
        uncovered = sorted(int(y) for y in sel_years if int(y) not in IPPI_P73)
        if uncovered:
            st.caption(
                f"⚠ IPPI coverage starts at {min(IPPI_P73)}. Values for "
                f"{', '.join(str(y) for y in uncovered)} are shown at nominal CAD."
            )

    agg = (
        view.groupby(["country", "country_name"], as_index=False, dropna=False)["value_cad"]
        .sum()
        .sort_values("value_cad", ascending=False)
    )
    total = float(agg["value_cad"].sum())

    # ------------------------------------------------------------------
    # Headline metrics
    # ------------------------------------------------------------------
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Total imports ({basis_label})", fmt_cad(total))
    c2.metric("Origin countries", f"{(agg['value_cad'] > 0).sum():,}")
    c3.metric("Year", year_label)

    # Show selected HS code descriptions (count surfaced in the expander
    # label since the headline metric row was reduced from 4 → 3 cells).
    if sel_hs:
        with st.expander(f"Selected HS codes ({len(sel_hs)})"):
            for c in sel_hs:
                st.markdown(f"- **{c}** — {hs6_desc.get(c, '')}")

    # ------------------------------------------------------------------
    # Build map
    # ------------------------------------------------------------------
    # Canada is the destination hub; remove it from origin list if present.
    agg = agg[agg["country"] != "CA"]
    agg = agg.merge(coords, left_on="country", right_on="iso2", how="left")

    missing = agg[agg["lat"].isna()]
    plotted = agg.dropna(subset=["lat", "lon"]).copy()

    # Limit to top-N for the map (table below shows everything)
    map_df = plotted.head(top_n).copy()

    # Marker sizes — flag *area* is proportional to import value, so the
    # diameter scales as sqrt(value). Log scaling is offered as an opt-in
    # for HS selections that mix tiny and dominant origins.
    if not map_df.empty:
        max_v = float(map_df["value_cad"].max()) or 1.0
        min_size, max_size = 14.0, 80.0
        span = max_size - min_size
        if log_size:
            denom = math.log10(max(max_v, 10))
            map_df["marker_size"] = (
                map_df["value_cad"].clip(lower=1).apply(math.log10) / denom
            ) * span + min_size
        else:
            map_df["marker_size"] = (
                (map_df["value_cad"].clip(lower=0) / max_v) ** 0.5 * span + min_size
            )

    folium_map_html = _build_folium_map(map_df, total)

    # Treemap data: each origin sized by current-window value, coloured by
    # YoY change (most recent selected year vs the year before).
    latest_yr = max(sel_years)
    prior_yr = latest_yr - 1
    deflated_full = apply_deflation(
        df[df["hs6"].isin(sel_hs) & (df["country"] != "CA")], cad_basis
    )
    cur_by_country = (
        deflated_full[deflated_full["year"] == latest_yr]
        .groupby("country")["value_cad"].sum()
    )
    prv_by_country = (
        deflated_full[deflated_full["year"] == prior_yr]
        .groupby("country")["value_cad"].sum()
    )

    def _yoy(iso: str) -> float | None:
        prv = float(prv_by_country.get(iso, 0.0))
        cur = float(cur_by_country.get(iso, 0.0))
        if prv <= 0:
            return None
        return (cur - prv) / prv * 100.0

    treemap_df = plotted[["country", "country_name", "value_cad"]].copy()
    treemap_df = treemap_df.dropna(subset=["country_name"])
    treemap_df = treemap_df[treemap_df["value_cad"] > 0]
    treemap_df["yoy_pct"] = treemap_df["country"].apply(_yoy)
    treemap_fig = _build_treemap(
        treemap_df, basis_label, prior_yr, latest_yr
    )

    # ------------------------------------------------------------------
    # Stacked bar chart: per-year imports across the full year range.
    # Each year shows its OWN top 5 origins plus an "Others" bucket, so the
    # set of named countries can shift between years.
    # ------------------------------------------------------------------
    bar_view = apply_deflation(
        df[df["hs6"].isin(sel_hs) & (df["country"] != "CA")], cad_basis
    )
    country_label = (
        bar_view.dropna(subset=["country_name"])
        .drop_duplicates("country")
        .set_index("country")["country_name"]
        .to_dict()
    )

    # Rank countries within each year; rank > 5 collapses into "Others".
    yearly_country = (
        bar_view.dropna(subset=["year"])
        .groupby(["year", "country"], as_index=False, dropna=False)["value_cad"]
        .sum()
    )
    yearly_country["rank"] = yearly_country.groupby("year")["value_cad"].rank(
        method="first", ascending=False
    )
    yearly_country["bucket"] = yearly_country["country"].where(
        yearly_country["rank"] <= 5, "Others"
    )
    yearly = yearly_country.groupby(
        ["year", "bucket"], as_index=False
    )["value_cad"].sum()
    year_totals = yearly.groupby("year")["value_cad"].sum().to_dict()
    yearly["pct"] = yearly.apply(
        lambda r: (r["value_cad"] / year_totals[r["year"]] * 100.0)
        if year_totals.get(r["year"], 0) else 0.0,
        axis=1,
    )

    # Union of countries that ever appeared in any year's top 5,
    # ordered by cumulative value across the full window.
    top5_union = (
        yearly_country[yearly_country["rank"] <= 5]
        .groupby("country")["value_cad"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )

    # Stable colour per country, drawn from the brand palette extended with
    # darker variants for the long-tail countries that may appear in only one
    # or two years.
    palette_extended = [
        "#F53C23", "#A59669", "#8282EB", "#0AB96E", "#FFB300", "#1A98AF",
        "#B22A18", "#6F6346", "#4F4FCC", "#066E42", "#C28A00", "#107488",
    ]
    country_colors = {
        c: palette_extended[i % len(palette_extended)]
        for i, c in enumerate(top5_union)
    }
    others_color = "#9AA0A6"

    bar_fig = go.Figure()
    for country in top5_union:
        sub = yearly[yearly["bucket"] == country].sort_values("year")
        if sub.empty or sub["value_cad"].sum() == 0:
            continue
        name = country_label.get(country, country)
        bar_fig.add_trace(
            go.Bar(
                name=name,
                x=sub["year"].astype(int),
                y=sub["value_cad"],
                customdata=sub["pct"],
                marker_color=country_colors[country],
                hovertemplate=(
                    f"<b>{name}</b><br>$%{{y:,.0f}}<br>"
                    "%{customdata:.1f}% of year<extra></extra>"
                ),
            )
        )

    others_sub = yearly[yearly["bucket"] == "Others"].sort_values("year").copy()
    if not others_sub.empty:
        others_per_year = (
            yearly_country.loc[
                (yearly_country["rank"] > 5)
                & (yearly_country["value_cad"] > 0)
            ]
            .groupby("year")["country"]
            .nunique()
            .to_dict()
        )
        others_sub["n"] = (
            others_sub["year"].map(others_per_year).fillna(0).astype(int)
        )
        bar_fig.add_trace(
            go.Bar(
                name="Others",
                x=others_sub["year"].astype(int),
                y=others_sub["value_cad"],
                customdata=others_sub[["pct", "n"]].to_numpy(),
                marker_color=others_color,
                hovertemplate=(
                    "<b>Others (%{customdata[1]})</b><br>$%{y:,.0f}<br>"
                    "%{customdata[0]:.1f}% of year<extra></extra>"
                ),
            )
        )
    # Dynamically size the bottom margin so a legend with many countries (the
    # union of every year's top 5 can easily reach 10+ entries) never spills
    # back into the plot area.
    n_traces = len(bar_fig.data)
    legend_rows = max(1, math.ceil(n_traces / 3))
    legend_px = 30 + legend_rows * 22
    plot_px = 380
    fig_height = plot_px + legend_px

    bar_fig.update_layout(
        barmode="stack",
        height=fig_height,
        margin=dict(l=10, r=10, t=30, b=legend_px),
        title=dict(
            text=(
                "Annual imports — each year's top 5 origins + Others "
                f"({basis_label})"
            ),
            x=0,
            font=dict(size=14),
        ),
        xaxis=dict(title=None, dtick=1, automargin=True),
        yaxis=dict(
            title=f"Value ({basis_label})",
            tickformat="$,.0s",
            automargin=True,
        ),
        legend=dict(
            orientation="h",
            yref="container",
            yanchor="bottom",
            y=8 / fig_height,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
            bgcolor="rgba(255,255,255,0.95)",
        ),
    )

    # ------------------------------------------------------------------
    # Layout: map (left, smaller) + bar chart (right)
    # ------------------------------------------------------------------
    map_col, chart_col = st.columns([3, 2])
    with map_col:
        view_mode = st.radio(
            "View",
            options=["Map", "Treemap"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key="map_view_mode",
        )
        if view_mode == "Map":
            components.html(folium_map_html, height=420)
            if not missing.empty:
                st.caption(
                    f"Excluded from map (no coordinates on file): "
                    f"{', '.join(sorted(missing['country'].dropna().unique()))}"
                )
        else:
            st.plotly_chart(treemap_fig, use_container_width=True)
            st.caption(
                f"Rectangles sized by import value ({basis_label}); "
                f"colour shows year-over-year change ({prior_yr} → {latest_yr}). "
                "Grey = no prior-year data."
            )
    with chart_col:
        st.plotly_chart(bar_fig, use_container_width=True)

    # ------------------------------------------------------------------
    # Bottom row: origin breakdown (left) + YoY insights (right)
    # ------------------------------------------------------------------
    breakdown_col, yoy_col = st.columns(2, gap="large", vertical_alignment="top")
    with breakdown_col:
        st.subheader("Origin breakdown")
        st.markdown(
            "<div style='min-height:46px;color:#666;font-size:13px;"
            "line-height:1.4;margin-bottom:8px;'>"
            f"All origin countries for {year_label} (sorted by value, {basis_label}). "
            "Click a row to see that country's HS-6 breakdown."
            "</div>",
            unsafe_allow_html=True,
        )

        breakdown_df = plotted[["country", "country_name", "value_cad"]].copy()
        breakdown_df["flag"] = (
            "https://flagcdn.com/24x18/" + breakdown_df["country"].str.lower() + ".png"
        )
        breakdown_df["share"] = (
            breakdown_df["value_cad"] / total if total > 0 else 0.0
        )

        # Persistent text search — survives year/basis changes since the
        # widget keeps its value via Streamlit's session storage.
        search = st.text_input(
            "Filter countries",
            key="origin_search",
            placeholder="Type a country name (e.g. 'norw')",
        ).strip()
        if search:
            s = search.lower()
            mask = (
                breakdown_df["country_name"].fillna("").str.lower().str.contains(s, regex=False)
                | breakdown_df["country"].fillna("").str.lower().str.contains(s, regex=False)
            )
            breakdown_df = breakdown_df[mask]

        breakdown_df = breakdown_df.reset_index(drop=True)
        breakdown_display = breakdown_df[
            ["flag", "country_name", "value_cad", "share"]
        ]

        if breakdown_df.empty:
            st.info(
                f"No countries match '{search}' for the current filter."
                if search else "No data."
            )
            selected_rows: list[int] = []
        else:
            # Keying the dataframe on the current data scope (year set + search)
            # forces selection state to reset when the data underneath changes —
            # otherwise a stale row index would point to a different country
            # (e.g. selecting Norway for 2016+2017 then switching to 2016 only
            # would silently jump to whoever held that row index in the new
            # data set).
            year_key = "_".join(str(y) for y in sorted(sel_years))
            selection_key = f"origin_table::{year_key}::{search}"

            selection = st.dataframe(
                breakdown_display,
                hide_index=True,
                use_container_width=True,
                height=360,
                column_config={
                    "flag": st.column_config.ImageColumn(label="", width="small"),
                    "country_name": st.column_config.TextColumn(label="Country"),
                    "value_cad": st.column_config.NumberColumn(
                        label=f"Value ({basis_label})", format="dollar"
                    ),
                    "share": st.column_config.NumberColumn(label="Share", format="percent"),
                },
                on_select="rerun",
                selection_mode="single-row",
                key=selection_key,
            )
            selected_rows = (
                selection.selection.rows if selection and selection.selection else []
            )

        if selected_rows:
            idx = selected_rows[0]
            iso = breakdown_df.iloc[idx]["country"]
            cname = breakdown_df.iloc[idx]["country_name"] or iso

            country_view = view[view["country"] == iso]
            hs_breakdown = (
                country_view.groupby(
                    ["hs6", "hs_description"], as_index=False, dropna=False
                )["value_cad"]
                .sum()
                .sort_values("value_cad", ascending=False)
            )
            country_total = float(hs_breakdown["value_cad"].sum())
            hs_breakdown["share"] = (
                hs_breakdown["value_cad"] / country_total
                if country_total > 0 else 0.0
            )

            st.markdown(
                f"**HS-6 breakdown — {cname}** &nbsp;"
                f"<span style='color:#666;font-size:13px;'>"
                f"Total {fmt_cad(country_total)} ({basis_label}) "
                f"across {len(hs_breakdown)} HS-6 code(s) in current filter</span>",
                unsafe_allow_html=True,
            )
            st.dataframe(
                hs_breakdown[["hs6", "hs_description", "value_cad", "share"]],
                hide_index=True,
                use_container_width=True,
                height=280,
                column_config={
                    "hs6": st.column_config.TextColumn(label="HS-6", width="small"),
                    "hs_description": st.column_config.TextColumn(label="Description"),
                    "value_cad": st.column_config.NumberColumn(
                        label=f"Value ({basis_label})", format="dollar"
                    ),
                    "share": st.column_config.NumberColumn(
                        label="Share of country", format="percent"
                    ),
                },
            )

    with yoy_col:
        st.subheader("Notable year-over-year changes")
        insights = _compute_yoy_insights(bar_view, country_label)
        st.markdown(
            "<div style='min-height:46px;color:#666;font-size:13px;"
            "line-height:1.4;margin-bottom:8px;'>"
            "Transitions where imports moved by ≥50% <b>and</b> ≥CAD $1M, "
            "or where a supplier started/stopped. Sorted chronologically."
            "</div>"
            # Invisible spacer matching the height of the breakdown column's
            # "Filter countries" text input (label + input + Streamlit's
            # built-in vertical padding) so both tables start at the same y.
            "<div style='height:78px;' aria-hidden='true'></div>",
            unsafe_allow_html=True,
        )
        if insights.empty:
            st.info(
                "No standout year-over-year changes (≥50% and ≥CAD $1M) for the current "
                "HS selection. Try widening the HS filter."
            )
        else:
            st.markdown(_render_yoy_table(insights), unsafe_allow_html=True)

    st.markdown(
        "<hr style='margin-top:32px;margin-bottom:6px;border:none;"
        "border-top:1px solid #eee;'>"
        "<div style='text-align:right;color:#888;font-size:11px;"
        "padding-bottom:16px;'>"
        "Version 1.0 · Developed by Rami F. · Data extracted 5 May 2026"
        "</div>",
        unsafe_allow_html=True,
    )


def _build_treemap(
    rows: pd.DataFrame,
    basis_label: str,
    prior_yr: int,
    latest_yr: int,
) -> go.Figure:
    """Stock-market-style treemap: every origin country a rectangle sized by
    import value (in the current selection), coloured by year-over-year
    percentage change (red ↘ ··· grey 0% ··· green ↗)."""
    fig = go.Figure()
    if rows.empty:
        return fig

    yoy_color = rows["yoy_pct"].fillna(0.0).clip(-100, 100)
    customdata = rows[["value_cad", "yoy_pct"]].copy()
    customdata["yoy_display"] = customdata["yoy_pct"].apply(
        lambda v: "n/a" if pd.isna(v) else f"{v:+.1f}%"
    )

    fig.add_trace(
        go.Treemap(
            labels=rows["country_name"],
            parents=[""] * len(rows),
            values=rows["value_cad"],
            customdata=customdata.to_numpy(),
            marker=dict(
                colors=yoy_color,
                colorscale=[
                    [0.0, "#c0392b"],   # ≤ −100 % (clamped): deep red
                    [0.5, "#e8e8e8"],   # 0 %: neutral grey
                    [1.0, "#1b8a5a"],   # ≥ +100 % (clamped): deep green
                ],
                cmin=-100,
                cmid=0,
                cmax=100,
                line=dict(color="white", width=1),
                colorbar=dict(
                    title=dict(text="YoY", font=dict(size=11)),
                    ticksuffix="%",
                    thickness=12,
                    len=0.7,
                    x=1.0,
                ),
            ),
            textinfo="label",
            textfont=dict(size=13, color="#111"),
            hovertemplate=(
                "<b>%{label}</b><br>"
                f"Value ({basis_label}): $%{{customdata[0]:,.0f}}<br>"
                f"YoY ({prior_yr} → {latest_yr}): %{{customdata[2]}}"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    return fig


def _flag_marker_html(iso2: str, size: int, *, ring_color: str = "white", ring_width: int = 2) -> str:
    """Square div with circular clip + the country flag as background image."""
    iso = iso2.lower()
    return (
        f"<div style='width:{size}px;height:{size}px;border-radius:50%;"
        f"overflow:hidden;border:{ring_width}px solid {ring_color};"
        f"box-shadow:0 1px 4px rgba(0,0,0,0.45);background:#eee;"
        f"display:flex;align-items:center;justify-content:center;'>"
        f"<img src='https://flagcdn.com/96x72/{iso}.png' "
        f"style='width:100%;height:100%;object-fit:cover;display:block;' "
        f"alt='{iso2}' onerror=\"this.style.display='none'\">"
        f"</div>"
    )


def _build_folium_map(map_df: pd.DataFrame, total: float) -> str:
    """Return a self-contained HTML string with a Folium map: Canada shaded
    as the destination, plus per-origin circular flag markers sized by value."""
    m = folium.Map(
        location=[20, -30],
        zoom_start=2,
        tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
        attr='&copy; OpenStreetMap contributors &copy; CARTO',
        world_copy_jump=False,
        min_zoom=2,
    )

    # Canada shaded as the destination.
    canada_geo = load_canada_geojson()
    if canada_geo is not None:
        canada_tooltip = folium.Tooltip(
            f"<div style='font-family:system-ui,sans-serif;font-size:13px;'>"
            f"<b>Canada (destination)</b><br>Total: {fmt_cad(total)}</div>",
            sticky=False,
        )
        folium.GeoJson(
            canada_geo,
            style_function=lambda _f: {
                "fillColor": "#F53C23",
                "color": "#F53C23",
                "weight": 1,
                "fillOpacity": 0.55,
            },
            highlight_function=lambda _f: {"fillOpacity": 0.7},
            tooltip=canada_tooltip,
        ).add_to(m)

    # Origin flag markers, sized by value.
    for _, row in map_df.iterrows():
        size = int(round(float(row["marker_size"])))
        size = max(12, min(size, 90))
        iso = str(row["country"])
        name = row["country_name"] if pd.notna(row.get("country_name")) else iso
        share = (row["value_cad"] / total * 100.0) if total > 0 else 0.0
        tooltip = (
            f"<div style='font-family:system-ui,sans-serif;font-size:13px;'>"
            f"<b>{name}</b> ({iso})<br>"
            f"{fmt_cad(float(row['value_cad']))}<br>"
            f"{share:.1f}% of total</div>"
        )
        folium.Marker(
            location=[float(row["lat"]), float(row["lon"])],
            icon=folium.DivIcon(
                html=_flag_marker_html(iso, size),
                icon_size=(size, size),
                icon_anchor=(size // 2, size // 2),
            ),
            tooltip=folium.Tooltip(tooltip, sticky=False),
        ).add_to(m)

    return m.get_root().render()


def _compute_yoy_insights(
    view: pd.DataFrame,
    country_label: dict,
    min_change_pct: float = 50.0,
    min_change_cad: float = 1_000_000.0,
    top_n: int = 25,
) -> pd.DataFrame:
    """Per (country, year-transition) row, flag transitions that are notable
    in either relative (≥min_change_pct) or category-shift (new/stopped) terms,
    subject to an absolute floor (min_change_cad) to suppress noise."""
    if view.empty:
        return pd.DataFrame()
    panel = (
        view.groupby(["country", "year"], as_index=False, dropna=False)["value_cad"]
        .sum()
        .pivot(index="country", columns="year", values="value_cad")
        .fillna(0.0)
    )
    years = [y for y in panel.columns if pd.notna(y)]
    years = sorted(int(y) for y in years)
    records = []
    for country in panel.index:
        for prev_y, curr_y in zip(years, years[1:]):
            prev_v = float(panel.at[country, prev_y])
            curr_v = float(panel.at[country, curr_y])
            if prev_v == 0 and curr_v == 0:
                continue
            delta = curr_v - prev_v
            if prev_v == 0 and curr_v >= min_change_cad:
                tag, pct = "New supplier", float("inf")
            elif curr_v == 0 and prev_v >= min_change_cad:
                tag, pct = "Stopped supplying", -100.0
            elif prev_v > 0:
                pct = delta / prev_v * 100.0
                if abs(delta) < min_change_cad or abs(pct) < min_change_pct:
                    continue
                if pct >= 200:
                    tag = "Surge"
                elif pct >= min_change_pct:
                    tag = "Sharp increase"
                elif pct <= -75:
                    tag = "Collapse"
                else:
                    tag = "Sharp decline"
            else:
                continue
            records.append({
                "country": country,
                "country_name": country_label.get(country, country),
                "transition": f"{prev_y} → {curr_y}",
                "curr_y": curr_y,
                "prev_value": prev_v,
                "curr_value": curr_v,
                "delta_cad": delta,
                "delta_pct": pct,
                "tag": tag,
            })
    out = pd.DataFrame(records)
    if out.empty:
        return out
    # Pick the top-N by absolute $ movement, then display them chronologically
    # (newer transitions last; ties within a year by absolute movement).
    out = (
        out.assign(_abs=out["delta_cad"].abs())
        .sort_values("_abs", ascending=False)
        .head(top_n)
        .sort_values(["curr_y", "_abs"], ascending=[False, False])
        .drop(columns=["_abs", "curr_y"])
    )
    return out


def _render_yoy_table(rows: pd.DataFrame) -> str:
    body = []
    current_transition: str | None = None
    for _, r in rows.iterrows():
        if r["transition"] != current_transition:
            body.append(
                "<tr style='background:#eef2f7;'>"
                "<td colspan='6' style='padding:8px 12px;text-align:center;"
                "font-weight:600;color:#1f3a68;letter-spacing:0.3px;'>"
                f"{r['transition']}"
                "</td></tr>"
            )
            current_transition = r["transition"]

        iso = str(r.get("country") or "").lower()
        flag = (
            f'<img src="https://flagcdn.com/24x18/{iso}.png" '
            f'style="vertical-align:middle;margin-right:8px;'
            f'box-shadow:0 0 1px rgba(0,0,0,0.4);" alt="" '
            f'onerror="this.style.visibility=\'hidden\'">'
            if iso else ""
        )
        name = r["country_name"] or r["country"]
        delta = r["delta_cad"]
        pct = r["delta_pct"]
        delta_sign = "+" if delta >= 0 else "−"
        delta_str = f"{delta_sign}${abs(delta):,.0f}"
        if pct == float("inf"):
            pct_str, arrow = "—", "▲"
        elif pct == -100.0:
            pct_str, arrow = "−100%", "▼"
        else:
            pct_str = f"{'+' if pct >= 0 else ''}{pct:.0f}%"
            arrow = "▲" if pct >= 0 else "▼"
        color = "#1b8a5a" if delta >= 0 else "#c0392b"
        body.append(
            "<tr>"
            f"<td style='padding:5px 12px;'>{flag}{name}</td>"
            f"<td style='padding:5px 12px;text-align:right;color:#666;'>${r['prev_value']:,.0f}</td>"
            f"<td style='padding:5px 12px;text-align:right;'>${r['curr_value']:,.0f}</td>"
            f"<td style='padding:5px 12px;text-align:right;color:{color};font-weight:500;'>{delta_str}</td>"
            f"<td style='padding:5px 12px;text-align:right;color:{color};'>{arrow} {pct_str}</td>"
            f"<td style='padding:5px 12px;color:#555;font-style:italic;'>{r['tag']}</td>"
            "</tr>"
        )
    return (
        "<div style='max-width:980px;overflow-x:auto;'>"
        "<table style='border-collapse:collapse;font-size:13px;width:100%;'>"
        "<thead><tr style='border-bottom:1px solid #ccc;background:#f5f5f5;'>"
        "<th style='text-align:left;padding:6px 12px;'>Country</th>"
        "<th style='text-align:right;padding:6px 12px;'>From</th>"
        "<th style='text-align:right;padding:6px 12px;'>To</th>"
        "<th style='text-align:right;padding:6px 12px;'>Δ CAD</th>"
        "<th style='text-align:right;padding:6px 12px;'>Δ %</th>"
        "<th style='text-align:left;padding:6px 12px;'>Note</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


if __name__ == "__main__":
    main()
