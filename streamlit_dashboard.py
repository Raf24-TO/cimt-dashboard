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

        sel_category = st.selectbox(
            "Category",
            options=[ALL] + [c["label"] for c in categories],
            format_func=lambda c: c if c == ALL else f"{cat_to_tier[c]} · {c}",
            help=(
                "Plain-English grid-equipment categories from categorization.md. "
                "Selecting one auto-picks the matching HS-4 code."
            ),
        )

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

        if sel_category != ALL:
            sel_hs4 = cat_to_hs4[sel_category]
            st.markdown(
                f"**HS-4:** `{sel_hs4}` &nbsp;<span style='color:#888;font-size:12px;'>"
                f"(from category)</span>",
                unsafe_allow_html=True,
            )
        else:
            sel_hs4 = st.selectbox(
                "HS-4 (heading)",
                options=[ALL] + hs4_codes,
                format_func=lambda c: c if c == ALL else f"{c} — {hs4_desc.get(c, '')[:90]}",
            )

        # HS-6 options scoped by HS-4 selection.
        if sel_hs4 == ALL:
            visible_hs6 = all_hs6
        else:
            visible_hs6 = [c for c in all_hs6 if c.startswith(sel_hs4)]

        sel_hs_raw = st.multiselect(
            "HS-6 code",
            options=[ALL] + visible_hs6,
            default=[ALL],
            format_func=lambda c: c if c == ALL else f"{c} — {hs6_desc.get(c, '')[:90]}",
        )
        # 'All' (or empty) expands to everything visible.
        if ALL in sel_hs_raw or not sel_hs_raw:
            sel_hs = visible_hs6
        else:
            sel_hs = [c for c in sel_hs_raw if c != ALL]

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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Total imports ({basis_label})", fmt_cad(total))
    c2.metric("Origin countries", f"{(agg['value_cad'] > 0).sum():,}")
    c3.metric("Year", year_label)
    c4.metric("HS codes selected", f"{len(sel_hs)}")

    # Show selected HS code descriptions
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

    # ------------------------------------------------------------------
    # Stacked bar chart: per-year imports across the full year range,
    # top 5 origin countries + "Others". Independent of the year filter.
    # ------------------------------------------------------------------
    bar_view = apply_deflation(
        df[df["hs6"].isin(sel_hs) & (df["country"] != "CA")], cad_basis
    )
    top_origins = (
        bar_view.groupby("country", as_index=False)["value_cad"]
        .sum()
        .nlargest(5, "value_cad")["country"]
        .tolist()
    )
    country_label = (
        bar_view.dropna(subset=["country_name"])
        .drop_duplicates("country")
        .set_index("country")["country_name"]
        .to_dict()
    )
    bar_view = bar_view.assign(
        bucket=lambda d: d["country"].where(d["country"].isin(top_origins), "Others")
    )
    yearly = bar_view.groupby(["year", "bucket"], as_index=False)["value_cad"].sum()
    year_totals = yearly.groupby("year")["value_cad"].sum().to_dict()
    yearly["pct"] = yearly.apply(
        lambda r: (r["value_cad"] / year_totals[r["year"]] * 100.0)
        if year_totals.get(r["year"], 0) else 0.0,
        axis=1,
    )
    others_n = bar_view.loc[
        ~bar_view["country"].isin(top_origins), "country"
    ].dropna().nunique()
    palette = ["#F53C23", "#A59669", "#8282EB", "#0AB96E", "#FFB300"]
    others_color = "#9AA0A6"

    bar_fig = go.Figure()
    for i, bucket in enumerate(top_origins):
        sub = yearly[yearly["bucket"] == bucket].sort_values("year")
        name = country_label.get(bucket, bucket)
        bar_fig.add_trace(
            go.Bar(
                name=name,
                x=sub["year"].astype(int),
                y=sub["value_cad"],
                customdata=sub["pct"],
                marker_color=palette[i % len(palette)],
                hovertemplate=(
                    f"<b>{name}</b><br>$%{{y:,.0f}}<br>"
                    "%{customdata:.1f}% of year<extra></extra>"
                ),
            )
        )
    others_sub = yearly[yearly["bucket"] == "Others"].sort_values("year")
    if not others_sub.empty:
        others_name = f"Others ({others_n})"
        bar_fig.add_trace(
            go.Bar(
                name=others_name,
                x=others_sub["year"].astype(int),
                y=others_sub["value_cad"],
                customdata=others_sub["pct"],
                marker_color=others_color,
                hovertemplate=(
                    f"<b>{others_name}</b><br>$%{{y:,.0f}}<br>"
                    "%{customdata:.1f}% of year<extra></extra>"
                ),
            )
        )
    bar_fig.update_layout(
        barmode="stack",
        height=480,
        margin=dict(l=10, r=10, t=30, b=30),
        title=dict(
            text=f"Annual imports — top 5 origins + others ({basis_label})",
            x=0,
            font=dict(size=14),
        ),
        xaxis=dict(title=None, dtick=1),
        yaxis=dict(title=f"Value ({basis_label})", tickformat="$,.0s"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.28,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        ),
    )

    # ------------------------------------------------------------------
    # Layout: map (left, smaller) + bar chart (right)
    # ------------------------------------------------------------------
    map_col, chart_col = st.columns([3, 2])
    with map_col:
        components.html(folium_map_html, height=500)
        if not missing.empty:
            st.caption(
                f"Excluded from map (no coordinates on file): "
                f"{', '.join(sorted(missing['country'].dropna().unique()))}"
            )
    with chart_col:
        st.plotly_chart(bar_fig, use_container_width=True)

    # ------------------------------------------------------------------
    # Bottom row: origin breakdown (left) + YoY insights (right)
    # ------------------------------------------------------------------
    breakdown_col, yoy_col = st.columns(2)
    with breakdown_col:
        st.subheader("Origin breakdown")
        st.caption(
            f"All origin countries for {year_label} (sorted by value, {basis_label}). "
            "Click a row to see that country's HS-6 breakdown."
        )

        breakdown_df = plotted[["country", "country_name", "value_cad"]].copy()
        breakdown_df["flag"] = (
            "https://flagcdn.com/24x18/" + breakdown_df["country"].str.lower() + ".png"
        )
        breakdown_df["share"] = (
            breakdown_df["value_cad"] / total if total > 0 else 0.0
        )
        breakdown_display = breakdown_df[
            ["flag", "country_name", "value_cad", "share"]
        ].reset_index(drop=True)

        selection = st.dataframe(
            breakdown_display,
            hide_index=True,
            use_container_width=True,
            height=420,
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
            key="origin_table",
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
                height=320,
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
        st.subheader("Notable YoY changes")
        insights = _compute_yoy_insights(bar_view, country_label)
        if insights.empty:
            st.info(
                "No standout YoY changes (≥50% and ≥CAD $1M) for the current "
                "HS selection. Try widening the HS filter."
            )
        else:
            st.caption(
                "Transitions where imports moved by ≥50% **and** ≥CAD $1M, "
                "or where a supplier started/stopped. Sorted by absolute $ change."
            )
            st.markdown(_render_yoy_table(insights), unsafe_allow_html=True)


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
    """Return a self-contained HTML string with a Folium flow map: Canada hub
    (CA flag), per-origin circular flag markers sized by value, and
    blue lines connecting each origin to Canada."""
    m = folium.Map(
        location=[20, -30],
        zoom_start=2,
        tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
        attr='&copy; OpenStreetMap contributors &copy; CARTO',
        world_copy_jump=False,
        min_zoom=2,
    )

    # Connecting lines first so flag markers render on top.
    for _, row in map_df.iterrows():
        folium.PolyLine(
            locations=[(row["lat"], row["lon"]), (CANADA_LAT, CANADA_LON)],
            color="#145ab4",
            weight=1,
            opacity=0.35,
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

    # Canada hub — bigger flag.
    canada_size = 56
    canada_tooltip = (
        f"<div style='font-family:system-ui,sans-serif;font-size:13px;'>"
        f"<b>Canada (destination)</b><br>Total: {fmt_cad(total)}</div>"
    )
    folium.Marker(
        location=[CANADA_LAT, CANADA_LON],
        icon=folium.DivIcon(
            html=_flag_marker_html("CA", canada_size, ring_color="#fff", ring_width=3),
            icon_size=(canada_size, canada_size),
            icon_anchor=(canada_size // 2, canada_size // 2),
        ),
        tooltip=folium.Tooltip(canada_tooltip, sticky=False),
        z_index_offset=1000,
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
                "prev_value": prev_v,
                "curr_value": curr_v,
                "delta_cad": delta,
                "delta_pct": pct,
                "tag": tag,
            })
    out = pd.DataFrame(records)
    if out.empty:
        return out
    out = out.assign(_abs=out["delta_cad"].abs()).sort_values("_abs", ascending=False).head(top_n)
    return out.drop(columns="_abs")


def _render_yoy_table(rows: pd.DataFrame) -> str:
    body = []
    for _, r in rows.iterrows():
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
            f"<td style='padding:5px 12px;'>{r['transition']}</td>"
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
        "<th style='text-align:left;padding:6px 12px;'>Transition</th>"
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
