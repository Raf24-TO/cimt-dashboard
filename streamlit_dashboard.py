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
import base64
import html
import math
import re

import folium
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative as plotly_qual
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
LONG_PARQUET = ROOT / "cimt_output" / "cimt_trade_slim.parquet"
LONG_CSV = ROOT / "cimt_output" / "cimt_trade_long.csv"
COORDS_CSV = ROOT / "country_coords.csv"
HS4_PRIORITY_FILE = ROOT / "hs_priority_4"
HS6_PRIORITY_FILE = ROOT / "hs_priority_6.md"
CATEGORIZATION_FILE = ROOT / "categorization.md"
EQUIPMENT_CATEGORIES_FILE = ROOT / "equipment_categories.md"
MAJOR_IMPORTERS_PARQUET = ROOT / "cimt_output" / "major_importers.parquet"

# HS-6 codes intentionally excluded from the dashboard. 850431 (≤1 kVA) and
# 850432 (>1 ≤16 kVA) are sub-grid-scale — electronic / equipment-internal /
# small dry-type & control transformers — not grid hardware. The 9030xx codes
# are HS-4 9030 electrical-measuring instruments (multimeters, oscilloscopes,
# spectrum analyzers, lab/test gear) — predominantly non-grid and indistinguishable
# from grid metering in the HS, so dropped entirely. Filtered out at data-load so
# the existing parquets don't have to be regenerated.
EXCLUDED_HS6: set[str] = {
    "850431", "850432",
    "903031", "903032", "903033", "903039", "903084", "903089",
}
LOGO_PATH = ROOT / "assets" / "transition_accelerator.png"
CANADA_GEOJSON = ROOT / "assets" / "canada.geojson"

CANADA_LAT, CANADA_LON = 56.130, -106.347
ALL = "All"

# Trade-flow display labels used wherever we surface the flow to the user.
FLOW_LABELS = {
    "imports": "Imports",
    "domestic_exports": "Domestic exports",
    "total_exports": "Total exports",
}
# Per-flow noun + Canada's role on the map.
FLOW_NOUN = {
    "imports": "imports",
    "domestic_exports": "domestic exports",
    "total_exports": "total exports",
}
# "Origin" vs "Destination" labels for the partner countries.
PARTNER_NOUN = {
    "imports": "origin",
    "domestic_exports": "destination",
    "total_exports": "destination",
}
CANADA_ROLE = {
    "imports": "destination",
    "domestic_exports": "origin",
    "total_exports": "origin",
}

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


def _data_file_signature() -> tuple[str, float, int]:
    """Cache-buster: when the slim parquet (or fallback CSV) changes on disk,
    its mtime/size shift and st.cache_data treats it as a new input."""
    for p in (LONG_PARQUET, LONG_CSV):
        if p.exists():
            stat = p.stat()
            return (str(p), stat.st_mtime, stat.st_size)
    return ("", 0.0, 0)


def _path_signature(path: Path) -> tuple[str, float, int]:
    """Cache-buster for file-backed parsers: when the file changes on disk its
    mtime/size shift, so st.cache_data treats it as a new input and reparses.
    Without this, parsers keyed only on the path serve a stale parse until the
    app process restarts (e.g. edits to equipment_categories.md not showing)."""
    if path.exists():
        stat = path.stat()
        return (str(path), stat.st_mtime, stat.st_size)
    return (str(path), 0.0, 0)


@st.cache_data(show_spinner="Loading trade data…")
def load_data(signature: tuple[str, float, int] | None = None) -> pd.DataFrame:
    """Prefer the slim Parquet (committed to git for cloud deploy); fall back to
    the full CSV produced by extract_cimt_trade.py for local development.

    The signature parameter is unused inside the body — it exists only to
    invalidate the cache when the source file's mtime/size change."""
    del signature  # only consumed by @st.cache_data's hashing
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
    if "quantity_1" in df.columns:
        df["quantity_1"] = pd.to_numeric(df["quantity_1"], errors="coerce").fillna(0)
    if "unit_1" not in df.columns:
        df["unit_1"] = pd.NA
    if "hs6" in df.columns:
        df = df[~df["hs6"].isin(EXCLUDED_HS6)].copy()
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
def load_equipment_categories(
    path: Path, sig: tuple[str, float, int] | None = None
) -> list[dict]:
    """Parse equipment_categories.md into grid-equipment categories.

    ``sig`` is unused in the body; it only lets st.cache_data reparse when the
    file changes (pass ``_path_signature(path)``).

    Each ``## N. <Category Name>`` heading starts a category; the first column
    of every markdown table row beneath it holds an HS code. Codes are
    classified by length:
      * 6 digits  → whole HS-6 (every detail code under it belongs)
      * 8/10 digits → an HS-8 / HS-10 carve-out (only that detail code belongs)

    Returns ``[{"name", "hs6": set, "full": set}]``. Non-numbered headings
    (e.g. the "⚠ Flagged" review tables) are ignored so flagged codes aren't
    double-counted.
    """
    if not path.exists():
        return []
    out: list[dict] = []
    cur: dict | None = None
    head_re = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            m = head_re.match(line)
            if m:
                cur = {"name": m.group(1).strip(), "hs6": set(), "full": set()}
                out.append(cur)
            else:
                cur = None  # flag/notes section — stop collecting codes
            continue
        if cur is None or not line.startswith("|"):
            continue
        code = line.strip("|").split("|")[0].strip().replace(" ", "")
        if not code.isdigit():
            continue
        if len(code) == 6:
            cur["hs6"].add(code)
        elif len(code) in (8, 10):
            cur["full"].add(code)
    return [c for c in out if c["hs6"] or c["full"]]


def fmt_cad(v: float) -> str:
    if v >= 1e9:
        return f"CAD ${v/1e9:,.2f}B"
    if v >= 1e6:
        return f"CAD ${v/1e6:,.2f}M"
    if v >= 1e3:
        return f"CAD ${v/1e3:,.1f}K"
    return f"CAD ${v:,.0f}"


def _inject_global_css():
    """Shared styling for every page: let long filter labels wrap instead of
    truncating, trim the main container's bottom padding, and scale type down
    on 13" laptops. BaseWeb nests option text in inner <div>s with their own
    white-space/overflow rules, so the descendants are overridden too."""
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
        /* Currently-selected value in a selectbox / multiselect chip */
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
        /* BaseWeb caps each multiselect chip's width (~150px) and ellipsises
           the inner span. Lift the cap so chips expand to the container width
           and wrap to multiple lines instead of truncating. */
        [data-baseweb="select"] [data-baseweb="tag"] {
            max-width: 100% !important;
            width: auto !important;
        }
        [data-baseweb="select"] [data-baseweb="tag"] *,
        [data-baseweb="select"] [data-baseweb="tag"] span,
        [data-baseweb="select"] [data-baseweb="tag"] div {
            max-width: none !important;
            width: auto !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            word-break: break-word !important;
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


def _excel_download(data_bytes: bytes, filename: str, label: str):
    """Right-aligned download link styled as a button, with an Excel-style green
    mark (embedded SVG) rather than a generic download glyph."""
    excel_svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
        "<rect x='3' y='5' width='26' height='22' rx='3' fill='#1D6F42'/>"
        "<path d='M12 11 L20 21 M20 11 L12 21' stroke='#fff' "
        "stroke-width='2.6' stroke-linecap='round'/></svg>"
    )
    icon_uri = base64.b64encode(excel_svg.encode()).decode()
    data_uri = base64.b64encode(data_bytes).decode()
    st.markdown(
        f"<div style='text-align:right;margin:-4px 0 8px;'>"
        f"<a href='data:text/csv;base64,{data_uri}' download='{filename}' "
        f"style='display:inline-flex;align-items:center;gap:8px;"
        f"text-decoration:none;border:1px solid #d0d4d9;border-radius:8px;"
        f"padding:6px 14px;background:#fff;color:#1f2937;font-size:14px;"
        f"font-weight:600;'>"
        f"<img src='data:image/svg+xml;base64,{icon_uri}' width='18' "
        f"height='18' style='vertical-align:middle'/>{label}</a></div>",
        unsafe_allow_html=True,
    )


def page_dashboard():
    st.title("Strengthening Canada's Grid Equipment Supply Chain")

    if not LONG_PARQUET.exists() and not LONG_CSV.exists():
        st.error(
            f"Data file not found at either {LONG_PARQUET} or {LONG_CSV}.\n\n"
            "Run `python extract_cimt_trade.py` first to generate the trade data."
        )
        st.stop()

    df_all = load_data(_data_file_signature())
    coords = load_coords()

    # ------------------------------------------------------------------
    # Sidebar — pass 1: logo, Filters header, Trade flow toggle.
    # The flow toggle must render BEFORE we derive per-flow lookups
    # (HS-6 list, HS-10 children, year coverage) so they reflect just the
    # selected flow's data.
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

        if "flow" in df_all.columns:
            # Preserve a canonical order so "imports" appears first regardless
            # of alphabetical sort (otherwise "domestic_exports" wins).
            canonical_order = ["imports", "domestic_exports", "total_exports"]
            present = set(df_all["flow"].dropna().unique().tolist())
            flows_in_data = [f for f in canonical_order if f in present] + sorted(
                present - set(canonical_order)
            )
        else:
            flows_in_data = ["imports"]
        sel_flow = st.radio(
            "Trade flow",
            options=flows_in_data,
            format_func=lambda f: FLOW_LABELS.get(f, f),
            horizontal=True,
            key="flow_select",
            help=(
                "Imports: HS-10 detail, by border crossing into Canada. "
                "Domestic exports: HS-8 detail, Canadian-origin goods only "
                "(re-exports excluded). Pick one — they shouldn't be summed."
            ),
        )

    # Slice df to the chosen flow, then derive per-flow lookups.
    if "flow" in df_all.columns:
        df = df_all[df_all["flow"] == sel_flow].copy()
    else:
        df = df_all.copy()
    st.caption(f"Canadian {FLOW_LABELS.get(sel_flow, sel_flow)} — CIMT")

    years_avail = sorted(df["year"].dropna().unique().tolist())
    hs_avail = (
        df[["hs6", "hs_description"]]
        .drop_duplicates("hs6")
        .sort_values("hs6")
    )
    hs6_desc = dict(zip(hs_avail["hs6"], hs_avail["hs_description"].fillna("")))
    all_hs6 = hs_avail["hs6"].tolist()

    # HS-10 → description map (imports only — exports use HS-8). The "(detail)"
    # picker further down only renders when the chosen flow exposes HS-10s.
    if "hs_full" in df.columns and "hs_full_description" in df.columns:
        hs10_avail = df[["hs_full", "hs_full_description", "hs6"]].drop_duplicates("hs_full")
        hs10_desc = dict(
            zip(hs10_avail["hs_full"], hs10_avail["hs_full_description"].fillna(""))
        )
        hs10_to_hs6 = dict(zip(hs10_avail["hs_full"], hs10_avail["hs6"]))
    else:
        hs10_desc = {}
        hs10_to_hs6 = {}

    # HS-4 codes from the priority file; fall back to HS-4 prefixes that exist
    # in the data when descriptions aren't available.
    hs4_codes, hs4_desc = load_hs_priority(HS4_PRIORITY_FILE)
    hs4_in_data = sorted({c[:4] for c in all_hs6})
    hs4_codes = [c for c in hs4_codes if c in hs4_in_data] or hs4_in_data

    # Grid-equipment categories from equipment_categories.md. Each maps to a
    # set of whole HS-6 codes plus (for transformers / converters) specific
    # HS-10 / HS-8 carve-outs. Keep only categories that touch a code present
    # in the current flow's data.
    hs6_in_data = set(all_hs6)
    categories = [
        c for c in load_equipment_categories(
            EQUIPMENT_CATEGORIES_FILE, _path_signature(EQUIPMENT_CATEGORIES_FILE)
        )
        if (c["hs6"] & hs6_in_data) or {f[:6] for f in c["full"]} & hs6_in_data
    ]
    cat_by_name = {c["name"]: c for c in categories}

    # ------------------------------------------------------------------
    # Sidebar — pass 2: per-flow filters (Category, HS-4, HS-6,
    # HS-10, Year, etc.).
    # ------------------------------------------------------------------
    with st.sidebar:

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

        # ---- Equipment-category filter ----------------------------------
        if "category_select" not in st.session_state:
            st.session_state["category_select"] = [ALL]
        sel_categories_raw = st.multiselect(
            "Category",
            options=[ALL] + [c["name"] for c in categories],
            format_func=lambda c: c,
            key="category_select",
            on_change=_make_all_or_specific_callback(
                "category_select", "category_prev"
            ),
            help=(
                "Grid-equipment categories. Pick one or several — the matching "
                "HS codes are selected automatically. A few categories resolve "
                "to specific HS-10/HS-8 detail codes (e.g. Large Power "
                "Transformer = >100 MVA only); the view notes when that happens."
            ),
        )
        st.session_state.setdefault("category_prev", list(sel_categories_raw))

        if ALL in sel_categories_raw or not sel_categories_raw:
            sel_categories = []
        else:
            sel_categories = [c for c in sel_categories_raw if c != ALL]

        # Resolve selected categories → whole HS-6 codes + HS-10/HS-8 carve-outs.
        # full_restrict[hs6] = the only detail codes allowed for that HS-6.
        whole_hs6: set[str] = set()
        full_restrict: dict[str, set[str]] = {}
        for name in sel_categories:
            cat = cat_by_name.get(name, {})
            whole_hs6 |= cat.get("hs6", set())
            for f in cat.get("full", set()):
                full_restrict.setdefault(f[:6], set()).add(f)
        # A parent that's whole in any category wins — drop its restriction.
        for h in list(full_restrict):
            if h in whole_hs6:
                del full_restrict[h]
        touched_hs6 = whole_hs6 | set(full_restrict)

        # HS-4 picker — always visible, sitting between Category and HS-6.
        # When categories are selected, options narrow to the HS-4 headings
        # those categories touch; otherwise the full HS-4 priority list shows.
        if sel_categories:
            hs4_in_scope = sorted({c[:4] for c in touched_hs6})
            hs4_picker_options = (
                [c for c in hs4_codes if c in hs4_in_scope] or hs4_in_scope
            )
            hs4_help = (
                f"Limited to the {len(hs4_in_scope)} HS-4 heading"
                f"{'s' if len(hs4_in_scope) != 1 else ''} touched by the "
                "selected categor"
                + ("ies" if len(sel_categories) != 1 else "y")
                + "."
            )
        else:
            hs4_picker_options = hs4_codes
            hs4_help = "Narrow further to a single HS-4 heading."
        sel_hs4 = st.selectbox(
            "HS-4 (heading)",
            options=[ALL] + hs4_picker_options,
            format_func=lambda c: c if c == ALL else f"{c} — {hs4_desc.get(c, '')}",
            help=hs4_help,
        )

        # HS-6 options scoped by the selected categories first, then narrowed
        # further by the HS-4 picker when set.
        if sel_categories:
            visible_hs6 = [c for c in all_hs6 if c in touched_hs6]
        else:
            visible_hs6 = all_hs6
        if sel_hs4 != ALL:
            visible_hs6 = [c for c in visible_hs6 if c.startswith(sel_hs4)]

        # HS-6 codes that report a quantity for the current flow (any row with
        # quantity_1 > 0). Codes without quantity are tagged "· no quantity" in
        # the picker — CIMT publishes value only for them.
        qty_codes = (
            set(df.loc[df["quantity_1"].fillna(0) > 0, "hs6"].unique())
            if "quantity_1" in df.columns else set()
        )

        if "hs6_select" not in st.session_state:
            st.session_state["hs6_select"] = [ALL]
        st.caption(
            "Codes tagged <span style='color:#c0392b;font-weight:600'>"
            "· no quantity</span> report value only — CIMT publishes "
            "no quantity/unit for them.",
            unsafe_allow_html=True,
        )
        sel_hs_raw = st.multiselect(
            "HS-6 code",
            options=[ALL] + visible_hs6,
            format_func=lambda c: (
                c if c == ALL
                else f"{c} — {hs6_desc.get(c, '')}"
                + ("" if c in qty_codes else "   · no quantity")
            ),
            key="hs6_select",
            on_change=_make_all_or_specific_callback("hs6_select", "hs6_prev"),
        )
        st.session_state.setdefault("hs6_prev", list(sel_hs_raw))
        # Streamlit's multiselect renders option labels as plain text — there's
        # no per-option color hook. This tiny script (mounted via an invisible
        # component iframe, with access to the parent document) walks the
        # dropdown options and selected chips and colors the "· no quantity"
        # suffix red as new ones appear.
        components.html(
            """
            <script>
            (function(){
              const RED='#c0392b', MARK='· no quantity';
              function paint(el){
                const w=document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                const nodes=[]; let n;
                while((n=w.nextNode())) nodes.push(n);
                nodes.forEach(node=>{
                  const i=node.nodeValue.indexOf(MARK);
                  if(i<0) return;
                  if(node.parentElement && node.parentElement.dataset.nq) return;
                  const span=document.createElement('span');
                  span.style.color=RED; span.style.fontWeight='600';
                  span.textContent=MARK; span.dataset.nq='1';
                  const p=node.parentNode;
                  p.insertBefore(document.createTextNode(node.nodeValue.slice(0,i)), node);
                  p.insertBefore(span, node);
                  p.insertBefore(document.createTextNode(node.nodeValue.slice(i+MARK.length)), node);
                  p.removeChild(node);
                });
              }
              function scan(){
                const d=window.parent.document;
                d.querySelectorAll('[data-baseweb="tag"], [role="option"]').forEach(paint);
              }
              scan();
              new MutationObserver(scan).observe(
                window.parent.document.body, {childList:true, subtree:true}
              );
            })();
            </script>
            """,
            height=0,
        )
        # 'All' (or empty) expands to everything visible.
        if ALL in sel_hs_raw or not sel_hs_raw:
            sel_hs = visible_hs6
        else:
            sel_hs = [c for c in sel_hs_raw if c != ALL]

        # ---- HS-10 detail (only when exactly one HS-6 is picked) -------
        sel_hs_full: list[str] = []
        if len(sel_hs) == 1 and hs10_to_hs6:
            single_hs6 = sel_hs[0]
            hs10_options = sorted(
                code for code, parent in hs10_to_hs6.items() if parent == single_hs6
            )
            # When a category carves this HS-6 down to specific detail codes,
            # the picker should only offer those — otherwise "All" would imply
            # the full HS-6 even though the view is already restricted.
            restricted = single_hs6 in full_restrict
            if restricted:
                hs10_options = [c for c in hs10_options if c in full_restrict[single_hs6]]
            # Imports expose 10-digit codes; domestic exports only 8-digit.
            detail_level = "HS-10" if sel_flow == "imports" else "HS-8"
            restrict_note = (
                " Limited to the detail codes that belong to the selected "
                "category." if restricted else ""
            )
            if len(hs10_options) > 1:
                if "hs10_select" not in st.session_state:
                    st.session_state["hs10_select"] = [ALL]
                all_label = "All (in category)" if restricted else ALL
                sel_hs10_raw = st.multiselect(
                    f"{detail_level} (detail)",
                    options=[ALL] + hs10_options,
                    format_func=lambda c: all_label if c == ALL
                    else f"{c} — {hs10_desc.get(c, '')}",
                    key="hs10_select",
                    on_change=_make_all_or_specific_callback(
                        "hs10_select", "hs10_prev"
                    ),
                    help=(
                        f"CIMT splits each HS-6 into one or more {detail_level} "
                        "codes (Canada-specific sub-classifications). Pick one "
                        "or several to narrow the view, or leave on 'All'."
                        + restrict_note
                    ),
                )
                st.session_state.setdefault("hs10_prev", list(sel_hs10_raw))
                # Drop any selections that aren't valid under the current HS-6
                # (otherwise a stale prior selection persists across HS-6 swaps,
                # or across flow swaps where HS-10 ↔ HS-8 codes don't overlap).
                valid_options = set(hs10_options)
                if ALL in sel_hs10_raw or not sel_hs10_raw:
                    sel_hs_full = []
                else:
                    sel_hs_full = [
                        c for c in sel_hs10_raw if c != ALL and c in valid_options
                    ]
            elif len(hs10_options) == 1:
                only = hs10_options[0]
                st.caption(
                    f"{detail_level}: **{only}** — {hs10_desc.get(only, '')[:60]}"
                    + ("  ·  fixed by category" if restricted else "")
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

        top_n = st.slider(
            "Top N origins on map", min_value=5, max_value=100, value=30, step=5
        )
        log_size = st.checkbox(
            "Log-scale marker sizes",
            value=False,
            help=(
                "Off (default): flag area is proportional to the metric "
                "selected in the Value/Quantity toggle. "
                "On: log scaling compresses the range so small origins are "
                "still visible."
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

    # Only carry restrictions for HS-6 codes still in the selection.
    active_restrict = {h: f for h, f in full_restrict.items() if h in sel_hs}

    _render_main_view(
        df, coords, hs6_desc, hs10_desc, sel_years, sel_hs, sel_hs_full,
        year_label, top_n, log_size, sel_flow, active_restrict,
    )

    st.markdown(
        "<hr style='margin-top:32px;margin-bottom:6px;border:none;"
        "border-top:1px solid #eee;'>"
        "<div style='color:#888;font-size:11px;padding-bottom:2px;'>"
        "Source: <a href='https://www150.statcan.gc.ca/n1/pub/71-607-x/"
        "71-607-x2021004-eng.htm' target='_blank' style='color:#888;'>"
        "StatsCanada — Canadian International Merchandise Trade Web Application"
        "</a></div>"
        "<div style='text-align:right;color:#888;font-size:11px;"
        "padding-bottom:16px;'>"
        "Version 1.0 · Developed by Rami F. · Data extracted 5 May 2026"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_main_view(
    df, coords, hs6_desc, hs10_desc, sel_years, sel_hs, sel_hs_full,
    year_label, top_n, log_size, sel_flow, full_restrict=None,
):
    """Unified trade view (Value + Quantity). Origin breakdown shows quantity
    alongside value when the current filter narrows to one CIMT unit. The
    optional sel_hs_full list narrows further to specific HS-10 / HS-8 codes.
    sel_flow labels the flow ('imports', 'domestic_exports', ...) for label
    text and the map's Canada role.

    full_restrict maps an HS-6 code → the only HS-10/HS-8 detail codes that
    belong to the selected category (e.g. {'850423': {'8504230030'}} for Large
    Power Transformer). Such HS-6 codes are included only for those detail
    codes; everything else is taken whole."""
    full_restrict = full_restrict or {}
    flow_noun = FLOW_NOUN.get(sel_flow, "trade")
    partner_noun = PARTNER_NOUN.get(sel_flow, "partner")
    partner_plural = partner_noun.capitalize() + " countries"
    canada_role = CANADA_ROLE.get(sel_flow, "destination")
    cad_basis = st.radio(
        "CAD basis",
        options=[NOMINAL_BASIS, REAL_BASIS],
        index=0,
        horizontal=True,
        key="cad_basis_radio",
        help=(
            "Nominal CAD: as-recorded values. "
            "2025 CAD: deflated using the StatCan IPPI for NAPCS P73 "
            "(electrical/electronic equipment). See Price Adjustments.md."
        ),
    )
    basis_label = "nominal CAD" if cad_basis == NOMINAL_BASIS else "2025 CAD"

    # Build the HS mask. Each selected HS-6 is taken whole unless a category
    # restricts it to specific HS-10/HS-8 detail codes (full_restrict), in
    # which case only those rows count. Used in every downstream filter
    # (headline, deflation, bar chart) so the entire view stays consistent.
    hs_mask = pd.Series(False, index=df.index)
    for h in sel_hs:
        part = df["hs6"] == h
        if h in full_restrict:
            part = part & df["hs_full"].isin(full_restrict[h])
        hs_mask = hs_mask | part
    # Manual HS-10 picker (single HS-6) narrows further still.
    if sel_hs_full:
        hs_mask = hs_mask & df["hs_full"].isin(sel_hs_full)

    # Surface any category-driven HS-10/HS-8 carve-out so the scope is explicit
    # (e.g. "Large Power Transformer → only the >100 MVA detail code").
    for h in sel_hs:
        if h not in full_restrict:
            continue
        children = set(df.loc[df["hs6"] == h, "hs_full"].dropna().unique())
        if not children:
            continue
        included = full_restrict[h] & children
        detail = "HS-10" if sel_flow == "imports" else "HS-8"
        if not included:
            st.warning(
                f"⚠ The selected category restricts **{h}** "
                f"({hs6_desc.get(h, '')}) to detail codes that don't exist for "
                f"**{FLOW_LABELS.get(sel_flow, sel_flow)}** — there is no data "
                f"for this code under the current trade flow. (This detail is "
                f"reported on the import side only.)"
            )
        elif included != children:
            codes_txt = ", ".join(
                f"`{c}` — {hs10_desc.get(c, '')[:48]}" for c in sorted(included)
            )
            st.caption(
                f"ℹ **{h}** ({hs6_desc.get(h, '')}) is scoped by the selected "
                f"category to {len(included)} of {len(children)} {detail} detail "
                f"code(s): {codes_txt}."
            )

    # ------------------------------------------------------------------
    # Filter & aggregate
    # ------------------------------------------------------------------
    mask = df["year"].isin(sel_years) & hs_mask
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

    # Download the exact filtered rows as CSV — reflects the flow, HS/category,
    # year and CAD-basis selections currently in effect.
    export_cols = [
        c for c in [
            "year", "flow", "hs6", "hs_description", "hs_full",
            "hs_full_description", "country", "country_name",
            "quantity_1", "unit_1", "value_cad",
        ] if c in view.columns
    ]
    export_df = view[export_cols].copy()
    export_df.insert(0, "cad_basis", basis_label)
    export_csv = export_df.to_csv(index=False).encode("utf-8-sig")
    export_name = (
        f"cimt_{sel_flow}_{year_label}.csv".replace("–", "-").replace(" ", "")
    )
    _excel_download(export_csv, export_name, "Download filtered data (CSV)")

    agg_spec: dict = {"value_cad": ("value_cad", "sum")}
    if "quantity_1" in view.columns:
        agg_spec["quantity_1"] = ("quantity_1", "sum")
    agg = (
        view.groupby(["country", "country_name"], as_index=False, dropna=False)
        .agg(**agg_spec)
        .sort_values("value_cad", ascending=False)
    )
    total = float(agg["value_cad"].sum())

    # Quantity is shown only when the filter narrows to exactly one HS-6 AND
    # all rows share a single CIMT unit. Aggregating quantity across distinct
    # HS-6 codes is meaningless even when they happen to share a unit
    # (e.g. summing transformers + switchgear in NMB has no real-world
    # interpretation), so we suppress quantity above the HS-6 level.
    single_hs_unit_raw = ""
    if "unit_1" in view.columns:
        units_seen = {str(u) for u in view["unit_1"].dropna().unique() if u}
        if len(units_seen) == 1:
            single_hs_unit_raw = next(iter(units_seen))
    show_quantity = bool(single_hs_unit_raw) and len(sel_hs) == 1
    unit_display = _display_unit(single_hs_unit_raw) if show_quantity else ""
    total_qty = (
        float(view["quantity_1"].sum())
        if show_quantity and "quantity_1" in view.columns
        else 0.0
    )

    # ------------------------------------------------------------------
    # Headline metrics — always 4 cells. The 4th cell is either:
    #   • the real Total quantity (single HS-6 with a CIMT unit),
    #   • "Not reported" (single HS-6 with no unit), or
    #   • a "Select one HS-6" prompt (multi-HS-6 selection).
    # ------------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Total {flow_noun} ({basis_label})", fmt_cad(total))
    if show_quantity:
        c2.metric(f"Total quantity ({unit_display})", _fmt_qty(total_qty, unit_display))
    elif len(sel_hs) == 1:
        c2.metric(
            "Total quantity",
            "Not reported",
            help=(
                "StatCan CIMT tracks this HS code by value only — no "
                "kilogram or unit count is recorded for any transaction. "
                "Common for high-voltage electrical equipment, where items "
                "in the category vary too widely in size/scale to be "
                "meaningfully counted."
            ),
        )
    else:
        n_hs4 = len({c[:4] for c in sel_hs})
        scope = (
            f"{n_hs4} HS-4 categories" if n_hs4 > 1
            else f"{len(sel_hs)} HS-6 codes"
        )
        c2.metric(
            "Total quantity",
            "Select one HS-6",
            help=(
                f"You currently have {scope} selected. Quantity sums "
                "aren't meaningful across distinct HS-6 codes — even within "
                "the same HS-4 category, different HS-6 codes describe "
                "different products. Narrow the sidebar HS-6 filter to a "
                "single code to see total quantity, average unit price, and "
                "the Value/Quantity bar-chart toggle."
            ),
        )
    c3.metric(partner_plural, f"{(agg['value_cad'] > 0).sum():,}")
    c4.metric("Year", year_label)

    # Selected-code list: each HS-6 with its detail (HS-10/HS-8) children listed
    # flush-left — included codes in green, then an "Excluded" sub-list in red
    # for any dropped by the category carve-out (or a manual HS-10 pick), so
    # what's actually counted vs. dropped is explicit.
    if sel_hs:
        detail_kind = "HS-10" if sel_flow == "imports" else "HS-8"
        manual = set(sel_hs_full)
        rows: list[str] = []
        n_incl = n_excl = 0
        for h in sel_hs:
            rows.append(
                f"<div style='margin-top:6px'><b>{h}</b> — "
                f"{html.escape(hs6_desc.get(h, ''))}</div>"
            )
            children = sorted(df.loc[df["hs6"] == h, "hs_full"].dropna().unique())
            allowed = set(children)
            if h in full_restrict:
                allowed &= full_restrict[h]
            if manual:  # manual HS-10 narrowing (single-HS-6 case)
                allowed &= manual
            incl = [c for c in children if c in allowed]
            excl = [c for c in children if c not in allowed]
            for c in incl:
                n_incl += 1
                rows.append(
                    f"<div style='margin-left:16px;color:#157347'>"
                    f"{c} — {html.escape(hs10_desc.get(c, ''))}</div>"
                )
            if excl:
                rows.append(
                    "<div style='margin-left:16px;margin-top:2px;color:#888;"
                    "font-size:12px;font-weight:600'>Excluded</div>"
                )
                for c in excl:
                    n_excl += 1
                    rows.append(
                        f"<div style='margin-left:16px;color:#c0392b'>"
                        f"{c} — {html.escape(hs10_desc.get(c, ''))}</div>"
                    )
        label = f"Selected codes — {len(sel_hs)} HS-6"
        if n_excl:
            label += f" · {n_incl} {detail_kind} included, {n_excl} excluded"
        elif n_incl:
            label += f" · {n_incl} {detail_kind}"
        with st.expander(label):
            st.markdown(
                "<div style='font-size:13px;line-height:1.45'>"
                + "".join(rows) + "</div>",
                unsafe_allow_html=True,
            )

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

    # Marker sizes — flag *area* is proportional to the metric chosen in the
    # Value/Quantity toggle (driven from session state so the same key the
    # bar-chart radio writes is read here too). Diameter scales as sqrt(metric);
    # log scaling is offered as an opt-in for selections that mix tiny and
    # dominant origins.
    map_metric = "value_cad"
    if (
        show_quantity
        and "quantity_1" in map_df.columns
        and st.session_state.get("bar_metric_mode", "Value") == "Quantity"
    ):
        map_metric = "quantity_1"
    if not map_df.empty:
        max_v = float(map_df[map_metric].max()) or 1.0
        min_size, max_size = 14.0, 80.0
        span = max_size - min_size
        if log_size:
            denom = math.log10(max(max_v, 10))
            map_df["marker_size"] = (
                map_df[map_metric].clip(lower=1).apply(math.log10) / denom
            ) * span + min_size
        else:
            map_df["marker_size"] = (
                (map_df[map_metric].clip(lower=0) / max_v) ** 0.5 * span + min_size
            )

    folium_map_html = _build_folium_map(
        map_df, total,
        canada_role=canada_role,
        size_metric=("quantity" if map_metric == "quantity_1" else "value"),
        unit_display=unit_display,
        total_qty=total_qty,
    )

    # Treemap data: each origin sized by current-window value, coloured by
    # YoY change (most recent selected year vs the year before).
    latest_yr = max(sel_years)
    prior_yr = latest_yr - 1
    deflated_full = apply_deflation(
        df[hs_mask & (df["country"] != "CA")], cad_basis
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
    # Bar chart data — built lazily inside the chart column so the toggle
    # (Value / Quantity) can drive which metric is plotted.
    # ------------------------------------------------------------------
    bar_view = apply_deflation(
        df[hs_mask & (df["country"] != "CA")], cad_basis
    )
    country_label = (
        bar_view.dropna(subset=["country_name"])
        .drop_duplicates("country")
        .set_index("country")["country_name"]
        .to_dict()
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
                f"Rectangles sized by {flow_noun} value ({basis_label}); "
                f"colour shows year-over-year change ({prior_yr} → {latest_yr}). "
                "Grey = no prior-year data."
            )
    with chart_col:
        if show_quantity:
            bar_metric_mode = st.radio(
                "Bar metric",
                options=["Value", "Quantity"],
                index=0,
                horizontal=True,
                label_visibility="collapsed",
                key="bar_metric_mode",
            )
        else:
            bar_metric_mode = "Value"
        show_all_legend = st.toggle(
            f"Show all countries in legend",
            value=False,
            key="bar_legend_all",
            help=(
                "Off (default): legend shows only the chosen year's top 4 "
                "destinations + Others. On: show every country in the legend "
                "(can be long when many partners are represented)."
            ),
        )
        bar_fig = _build_yearly_bar_fig(
            bar_view, country_label,
            is_value=(bar_metric_mode == "Value"),
            basis_label=basis_label,
            unit_display=unit_display,
            flow_noun=flow_noun,
            partner_noun=partner_noun,
            show_all_legend=show_all_legend,
        )
        st.plotly_chart(bar_fig, use_container_width=True)

    # ------------------------------------------------------------------
    # Bottom row: origin breakdown (left) + YoY insights (right)
    # ------------------------------------------------------------------
    # Single-unit detection was computed earlier (drives both headline + table).
    breakdown_col, yoy_col = st.columns(2, gap="large", vertical_alignment="top")
    with breakdown_col:
        st.subheader(f"{partner_noun.capitalize()} breakdown")
        intro = (
            f"All {partner_noun} countries for {year_label} "
            f"(sorted by value, {basis_label}). "
            "Click a row to see that country's HS-6 breakdown."
        )
        if show_quantity:
            intro = (
                f"All {partner_noun} countries for {year_label} — "
                f"value ({basis_label}) and quantity ({unit_display}) side by side."
            )
        st.markdown(
            "<div style='min-height:46px;color:#666;font-size:13px;"
            f"line-height:1.4;margin-bottom:8px;'>{intro}</div>",
            unsafe_allow_html=True,
        )

        breakdown_df = plotted[["country", "country_name", "value_cad"]].copy()
        breakdown_df["flag"] = (
            "https://flagcdn.com/24x18/" + breakdown_df["country"].str.lower() + ".png"
        )
        breakdown_df["share"] = (
            breakdown_df["value_cad"] / total if total > 0 else 0.0
        )
        if show_quantity:
            qty_by_country = (
                view.groupby("country", dropna=False)["quantity_1"].sum().to_dict()
            )
            breakdown_df["quantity_1"] = (
                breakdown_df["country"].map(qty_by_country).fillna(0.0)
            )
            breakdown_df["avg_unit_price"] = breakdown_df.apply(
                lambda r: (r["value_cad"] / r["quantity_1"])
                if r["quantity_1"] and r["quantity_1"] > 0
                else None,
                axis=1,
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
        display_cols = ["flag", "country_name", "value_cad"]
        if show_quantity:
            display_cols += ["quantity_1", "avg_unit_price"]
        display_cols.append("share")
        breakdown_display = breakdown_df[display_cols]

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
            selection_key = f"origin_table::{year_key}::{search}::{single_hs_unit_raw}"

            column_config = {
                "flag": st.column_config.ImageColumn(label="", width="small"),
                "country_name": st.column_config.TextColumn(label="Country"),
                "value_cad": st.column_config.NumberColumn(
                    label=f"Value ({basis_label})", format="dollar"
                ),
                "share": st.column_config.NumberColumn(label="Share", format="percent"),
            }
            if show_quantity:
                column_config["quantity_1"] = st.column_config.NumberColumn(
                    label=f"Quantity ({unit_display})", format="localized"
                )
                column_config["avg_unit_price"] = st.column_config.NumberColumn(
                    label=f"Avg unit price ({basis_label} / {unit_display})",
                    format="dollar",
                )
            selection = st.dataframe(
                breakdown_display,
                hide_index=True,
                use_container_width=True,
                height=360,
                column_config=column_config,
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
        st.subheader("Notable changes")
        years_in_view = sorted(int(y) for y in bar_view["year"].dropna().unique())
        if len(years_in_view) >= 2:
            first_y, last_y = years_in_view[0], years_in_view[-1]
        else:
            first_y, last_y = None, None
        intro = (
            (
                f"Movements ≥50% <b>and</b> ≥CAD $1M between {first_y} and "
                f"{last_y}, or suppliers that started/stopped. Expand below "
                "for the year-by-year breakdown."
            )
            if first_y is not None
            else (
                "Movements ≥50% <b>and</b> ≥CAD $1M, or suppliers that "
                "started/stopped."
            )
        )
        st.markdown(
            "<div style='min-height:46px;color:#666;font-size:13px;"
            f"line-height:1.4;margin-bottom:8px;'>{intro}</div>"
            # Invisible spacer matching the height of the breakdown column's
            # "Filter countries" text input (label + input + Streamlit's
            # built-in vertical padding) so both tables start at the same y.
            "<div style='height:78px;' aria-hidden='true'></div>",
            unsafe_allow_html=True,
        )

        # Headline: change between the first and last available year.
        if first_y is not None and last_y is not None and last_y > first_y:
            headline = _compute_period_change(
                bar_view, country_label, first_y, last_y
            )
            if headline.empty:
                st.info(
                    f"No standout changes from {first_y} to {last_y} for the "
                    "current HS selection."
                )
            else:
                # Reuse the yearly renderer's transition banner (`2016 → 2025`)
                # so the table has a clear visual anchor for the period.
                st.markdown(
                    _render_yoy_table(headline, show_transition_header=True),
                    unsafe_allow_html=True,
                )

        # Yearly transitions tucked into an expander so the headline stays
        # the dominant view; click to see the chronological breakdown.
        with st.expander("Yearly transitions", expanded=False):
            insights = _compute_yoy_insights(bar_view, country_label)
            if insights.empty:
                st.info(
                    "No standout year-over-year changes (≥50% and ≥CAD $1M) "
                    "for the current HS selection."
                )
            else:
                st.markdown(_render_yoy_table(insights), unsafe_allow_html=True)



def _display_unit(unit_raw: str) -> str:
    """Map CIMT's raw unit codes to user-facing labels (only NMB so far)."""
    return {"NMB": "units"}.get((unit_raw or "").upper(), unit_raw or "")


def _fmt_qty(v: float, unit: str) -> str:
    return f"{v:,.0f} {unit}"


def _money_tick_text(v: float) -> str:
    """Adaptive $ axis label: $17.4B / $250M / $50k / $0 — matches the headline's
    'B' suffix instead of d3's SI 'G', and scales down for small selections."""
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.1f}".rstrip("0").rstrip(".") + "B"
    if a >= 1e6:
        return f"${v / 1e6:.0f}M"
    if a >= 1e3:
        return f"${v / 1e3:.0f}k"
    return f"${v:.0f}"


def _nice_ticks(ymax: float, target: int = 6) -> list[float]:
    """Tick values 0 … ≥ymax at a 'nice' 1/2/2.5/5 × 10^n step, so the top tick
    always clears the tallest bar (no value floating above the axis)."""
    if not ymax or ymax <= 0:
        return [0.0]
    raw = ymax / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next((mag * m for m in (1, 2, 2.5, 5, 10) if mag * m >= raw), mag * 10)
    n = int(math.ceil(ymax / step))
    return [step * i for i in range(n + 1)]





def _build_yearly_bar_fig(
    bar_view: pd.DataFrame,
    country_label: dict,
    *,
    is_value: bool,
    basis_label: str,
    unit_display: str,
    flow_noun: str = "imports",
    partner_noun: str = "origin",
    show_all_legend: bool = False,
) -> go.Figure:
    """Stacked per-year bar chart by partner country. Same shape for value and
    quantity — the metric column, axis label, and hover format swap between
    modes. flow_noun / partner_noun parameterize the title for exports."""
    metric_col = "value_cad" if is_value else "quantity_1"

    yearly_country = (
        bar_view.dropna(subset=["year"])
        .groupby(["year", "country"], as_index=False, dropna=False)[metric_col]
        .sum()
    )
    # Each year keeps its top 4 partners by name; everything else folds into
    # "Others". TOP_N is 4 so the named bands match the legend exactly.
    TOP_N = 4
    yearly_country["rank"] = yearly_country.groupby("year")[metric_col].rank(
        method="first", ascending=False
    )
    yearly_country["bucket"] = yearly_country["country"].where(
        yearly_country["rank"] <= TOP_N, "Others"
    )
    yearly = yearly_country.groupby(
        ["year", "bucket"], as_index=False
    )[metric_col].sum()
    year_totals = yearly.groupby("year")[metric_col].sum().to_dict()
    yearly["pct"] = yearly.apply(
        lambda r: (r[metric_col] / year_totals[r["year"]] * 100.0)
        if year_totals.get(r["year"], 0) else 0.0,
        axis=1,
    )
    # Chosen year = latest year in the selection; its top 4 always show in the
    # legend and set the stack order.
    chosen_year = (
        int(yearly_country["year"].dropna().max())
        if not yearly_country["year"].dropna().empty else None
    )
    named = yearly_country[yearly_country["rank"] <= TOP_N]
    total_val = named.groupby("country")[metric_col].sum().to_dict()
    chosen_val = (
        named[named["year"] == chosen_year]
        .set_index("country")[metric_col]
        .to_dict()
        if chosen_year is not None else {}
    )
    # Stack order: largest in the chosen year first → rendered at the BOTTOM of
    # the stack, descending upward. Countries absent that year fall back to
    # their cross-year total. "Others" is added last so it always sits on top.
    top_union = sorted(
        total_val,
        key=lambda c: (chosen_val.get(c, float("-inf")), total_val.get(c, 0.0)),
        reverse=True,
    )
    if chosen_year is None:
        top4_chosen: set = set()
    else:
        top4_chosen = set(
            named[named["year"] == chosen_year]
            .sort_values(metric_col, ascending=False)
            .head(TOP_N)["country"]
            .tolist()
        )

    # Large combined palette so every distinct country gets a distinct colour.
    # Top-1 stays the brand red (the dashboard's accent); the rest pulls from
    # Plotly's Dark24 + Light24 + Alphabet qualitative palettes (~70 unique
    # after dedup) — well above the ~50 partners that can show up across
    # 10 years × top-5 + Others.
    base = (
        ["#F53C23"]
        + ["#A59669", "#8282EB", "#0AB96E", "#FFB300", "#1A98AF",
           "#B22A18", "#6F6346", "#4F4FCC", "#066E42", "#C28A00", "#107488"]
        + list(plotly_qual.Dark24)
        + list(plotly_qual.Light24)
        + list(plotly_qual.Alphabet)
    )
    seen: set[str] = set()
    palette_extended: list[str] = []
    for c in base:
        u = c.upper()
        if u not in seen:
            seen.add(u)
            palette_extended.append(c)
    country_colors = {
        c: palette_extended[i % len(palette_extended)]
        for i, c in enumerate(top_union)
    }
    others_color = "#9AA0A6"

    # Mode-specific labels/formats.
    if is_value:
        title_text = (
            f"Annual {flow_noun} — each year's top 4 {partner_noun}s + Others "
            f"({basis_label})"
        )
        yaxis_title = f"Value ({basis_label})"
        # Explicit "nice" ticks with a $-and-B label (e.g. $5B, $10B, $15B) so
        # the axis matches the headline and never mislabels a gridline the way
        # d3's 1-sig-fig ".0s" did (16B/18B/20B all printed "$20G").
        _ymax = max(year_totals.values()) if year_totals else 0.0
        _tickvals = _nice_ticks(_ymax)
        _ticktext = [_money_tick_text(v) for v in _tickvals]
        yaxis_fmt = None
        hover_y = "$%{y:,.0f}"
    else:
        title_text = (
            f"Annual quantity — each year's top 4 {partner_noun}s + Others "
            f"({unit_display})"
        )
        yaxis_title = f"Quantity ({unit_display})"
        yaxis_fmt = ",.2s"
        _tickvals = None
        _ticktext = None
        hover_y = "%{y:,.0f} " + unit_display

    bar_fig = go.Figure()
    for country in top_union:
        sub = yearly[yearly["bucket"] == country].sort_values("year")
        if sub.empty or sub[metric_col].sum() == 0:
            continue
        name = country_label.get(country, country)
        bar_fig.add_trace(
            go.Bar(
                name=name,
                x=sub["year"].astype(int),
                y=sub[metric_col],
                customdata=sub["pct"],
                marker_color=country_colors[country],
                showlegend=show_all_legend or country in top4_chosen,
                hovertemplate=(
                    f"<b>{name}</b><br>{hover_y}<br>"
                    "%{customdata:.1f}% of year<extra></extra>"
                ),
            )
        )

    others_sub = yearly[yearly["bucket"] == "Others"].sort_values("year").copy()
    if not others_sub.empty:
        others_per_year = (
            yearly_country.loc[
                (yearly_country["rank"] > TOP_N)
                & (yearly_country[metric_col] > 0)
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
                y=others_sub[metric_col],
                customdata=others_sub[["pct", "n"]].to_numpy(),
                marker_color=others_color,
                hovertemplate=(
                    "<b>Others (%{customdata[1]})</b><br>" + hover_y + "<br>"
                    "%{customdata[0]:.1f}% of year<extra></extra>"
                ),
            )
        )

    # Legend sizing reflects only the traces actually shown in the legend,
    # otherwise hiding non-top-4 countries leaves big empty space below.
    n_legend = sum(1 for t in bar_fig.data if getattr(t, "showlegend", True))
    legend_rows = max(1, math.ceil(n_legend / 3))
    legend_px = 30 + legend_rows * 22
    plot_px = 380
    fig_height = plot_px + legend_px

    # Value charts use explicit nice ticks ($5B, $10B…) with a forced range so
    # the top tick clears the tallest bar; quantity charts keep SI tick labels.
    if _tickvals and _tickvals[-1] > 0:
        yaxis_opts = dict(
            title=yaxis_title,
            tickmode="array",
            tickvals=_tickvals,
            ticktext=_ticktext,
            range=[0, _tickvals[-1]],
            automargin=True,
        )
    else:
        yaxis_opts = dict(
            title=yaxis_title,
            tickformat=yaxis_fmt,
            automargin=True,
        )

    bar_fig.update_layout(
        barmode="stack",
        height=fig_height,
        margin=dict(l=10, r=10, t=30, b=legend_px),
        title=dict(text=title_text, x=0, font=dict(size=14)),
        xaxis=dict(title=None, dtick=1, automargin=True),
        yaxis=yaxis_opts,
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
    return bar_fig


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


def _build_folium_map(
    map_df: pd.DataFrame,
    total: float,
    *,
    canada_role: str = "destination",
    size_metric: str = "value",
    unit_display: str = "",
    total_qty: float = 0.0,
) -> str:
    """Return a self-contained HTML string with a Folium map: Canada shaded
    as the destination (imports) or origin (exports), plus per-partner
    circular flag markers sized by the chosen metric (value or quantity)."""
    m = folium.Map(
        location=[20, -30],
        zoom_start=2,
        tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
        attr='&copy; OpenStreetMap contributors &copy; CARTO',
        world_copy_jump=False,
        min_zoom=2,
    )

    canada_geo = load_canada_geojson()
    if canada_geo is not None:
        canada_total_line = (
            f"Total: {_fmt_qty(total_qty, unit_display)}"
            if size_metric == "quantity" and unit_display and total_qty
            else f"Total: {fmt_cad(total)}"
        )
        canada_tooltip = folium.Tooltip(
            f"<div style='font-family:system-ui,sans-serif;font-size:13px;'>"
            f"<b>Canada ({canada_role})</b><br>{canada_total_line}</div>",
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
        if size_metric == "quantity" and unit_display and "quantity_1" in row.index:
            qty = float(row.get("quantity_1") or 0.0)
            share = (qty / total_qty * 100.0) if total_qty > 0 else 0.0
            primary = _fmt_qty(qty, unit_display)
            secondary = fmt_cad(float(row["value_cad"]))
            tooltip = (
                f"<div style='font-family:system-ui,sans-serif;font-size:13px;'>"
                f"<b>{name}</b> ({iso})<br>"
                f"{primary}<br>"
                f"<span style='color:#666'>{secondary}</span><br>"
                f"{share:.1f}% of total</div>"
            )
        else:
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


def _compute_period_change(
    view: pd.DataFrame,
    country_label: dict,
    prev_y: int,
    curr_y: int,
    min_change_pct: float = 50.0,
    min_change_cad: float = 1_000_000.0,
    top_n: int = 25,
) -> pd.DataFrame:
    """Per-country change between two specific years (e.g. first → last in the
    window). Same significance thresholds as the year-over-year view."""
    if view.empty:
        return pd.DataFrame()
    panel = (
        view[view["year"].isin([prev_y, curr_y])]
        .groupby(["country", "year"], as_index=False, dropna=False)["value_cad"]
        .sum()
        .pivot(index="country", columns="year", values="value_cad")
        .fillna(0.0)
    )
    if prev_y not in panel.columns or curr_y not in panel.columns:
        return pd.DataFrame()
    records = []
    for country in panel.index:
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
    return (
        out.assign(_abs=out["delta_cad"].abs())
        .sort_values("_abs", ascending=False)
        .head(top_n)
        .drop(columns="_abs")
    )


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


def _render_yoy_table(rows: pd.DataFrame, *, show_transition_header: bool = True) -> str:
    body = []
    current_transition: str | None = None
    for _, r in rows.iterrows():
        if show_transition_header and r["transition"] != current_transition:
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


@st.cache_data
def _category_entries(
    path: Path, sig: tuple[str, float, int] | None = None
) -> list[dict]:
    """Parse equipment_categories.md into per-category rows.

    ``sig`` is unused in the body; it only lets st.cache_data reparse when the
    file changes (pass ``_path_signature(path)``).

    Returns ``[{name, intro, rows:[{code, desc, reason, flagged}]}]`` for each
    numbered ``## N. Name`` category. ``flagged`` is true when the reasoning
    carries a ⚠ / FLAG marker. The dev-facing appendix sections are skipped."""
    if not path.exists():
        return []
    head_re = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$")
    cats: list[dict] = []
    cur: dict | None = None
    cols: dict | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            m = head_re.match(line)
            cur = {"name": m.group(1).strip(), "intro": [], "rows": []} if m else None
            cols = None
            if m:
                cats.append(cur)
            continue
        if cur is None:
            continue
        if not line.startswith("|"):
            if line and cols is None:  # intro paragraph (before the table)
                cur["intro"].append(line)
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        low = [c.lower() for c in cells]
        if cols is None and any("description" in c for c in low):  # header row
            cols = {
                "desc": next((i for i, c in enumerate(low) if "description" in c), 1),
                "reason": next(
                    (i for i, c in enumerate(low) if "reason" in c), len(cells) - 1
                ),
            }
            continue
        if all(set(c) <= set("-: ") for c in cells if c):  # separator row
            continue
        code = cells[0].replace(" ", "")
        if not code.isdigit():
            continue
        di = (cols or {}).get("desc", 1)
        ri = (cols or {}).get("reason", len(cells) - 1)
        desc = cells[di] if di < len(cells) else ""
        reason = cells[ri] if ri < len(cells) else ""
        flagged = ("⚠" in reason) or ("FLAG" in reason.upper())
        cur["rows"].append(
            {"code": code, "desc": desc, "reason": reason, "flagged": flagged}
        )
    return [c for c in cats if c["rows"]]


def page_categorization():
    st.title("Equipment Categorization")
    st.markdown(
        "Every HS code is assigned to one grid-equipment category, laid out as a "
        "**HS-4 → HS-6 → HS-10** hierarchy. Most codes map at the HS-6 level (all "
        "their HS-10 detail codes belong); a few — large transformers and HVDC "
        "converters — are pinned to specific HS-10/HS-8 codes so the category "
        "captures only the grid-relevant slice. "
        "<span style='color:#c0392b;font-weight:600'>Forced or weak fits are "
        "shown in red.</span>",
        unsafe_allow_html=True,
    )

    _cat_sig = _path_signature(EQUIPMENT_CATEGORIES_FILE)
    cats = load_equipment_categories(EQUIPMENT_CATEGORIES_FILE, _cat_sig)
    entries = _category_entries(EQUIPMENT_CATEGORIES_FILE, _cat_sig)
    if not cats or not entries:
        st.error(
            f"Categorization file not found or empty: {EQUIPMENT_CATEGORIES_FILE.name}"
        )
        st.stop()

    n_hs6 = len(
        set().union(*[c["hs6"] for c in cats])
        | {f[:6] for c in cats for f in c["full"]}
    )
    n_carve = len({f for c in cats for f in c["full"]})
    n_flag = sum(1 for e in entries for r in e["rows"] if r["flagged"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Categories", len(cats))
    c2.metric("HS-6 codes", n_hs6)
    c3.metric("HS-10/HS-8 carve-outs", n_carve)
    c4.metric("Flagged", n_flag)

    # Data for HS-10 detail children + descriptions (imports expose 10-digit).
    df_all = load_data(_data_file_signature())
    imp = df_all[df_all["flow"] == "imports"] if "flow" in df_all.columns else df_all
    hs6_to_detail: dict[str, list] = {}
    ch = (
        imp[["hs6", "hs_full", "hs_full_description"]]
        .dropna(subset=["hs_full"])
        .drop_duplicates("hs_full")
    )
    for r in ch.itertuples(index=False):
        hs6_to_detail.setdefault(r.hs6, []).append(
            (r.hs_full, r.hs_full_description or "")
        )
    for k in hs6_to_detail:
        hs6_to_detail[k].sort()
    hd = df_all[["hs6", "hs_description"]].dropna(subset=["hs6"]).drop_duplicates("hs6")
    hs6_desc = dict(zip(hd["hs6"], hd["hs_description"].fillna("")))
    _, hs4_desc = load_hs_priority(HS4_PRIORITY_FILE)

    names = [e["name"] for e in entries]
    pick = st.selectbox("Jump to category", ["All categories"] + names)
    st.divider()

    RED, DARK, MUTED, BLUE = "#c0392b", "#1f2937", "#6b7280", "#1f3a68"
    esc = html.escape

    for e in entries:
        if pick != "All categories" and e["name"] != pick:
            continue
        st.header(e["name"])
        intro = " ".join(e["intro"]).strip()
        if intro:
            st.caption(intro)

        # Group rows into HS-4 → HS-6 → {whole assignment, carve-out details}.
        tree: dict[str, dict[str, dict]] = {}
        for r in e["rows"]:
            code = r["code"]
            node = tree.setdefault(code[:4], {}).setdefault(
                code[:6], {"whole": None, "carve": []}
            )
            if len(code) == 6:
                node["whole"] = r
            else:
                node["carve"].append(r)

        rows = [
            "<tr style='border-bottom:2px solid #d0d0d0;text-align:left'>"
            "<th style='padding:6px 10px'>HS code</th>"
            "<th style='padding:6px 10px'>Description</th>"
            "<th style='padding:6px 10px'>Notes</th></tr>"
        ]
        for hs4 in sorted(tree):
            h4d = hs4_desc.get(hs4, "")
            rows.append(
                "<tr style='background:#eef2f7'>"
                f"<td colspan='3' style='padding:7px 10px;font-weight:700;"
                f"color:{BLUE}'>HS-4 · {hs4}"
                + (f" — {esc(h4d)}" if h4d else "")
                + "</td></tr>"
            )
            for hs6 in sorted(tree[hs4]):
                node = tree[hs4][hs6]
                whole, carve = node["whole"], node["carve"]
                if whole:
                    d = whole["desc"] or hs6_desc.get(hs6, "")
                    flagged, reason = whole["flagged"], whole["reason"]
                else:
                    d = hs6_desc.get(hs6, "")
                    flagged, reason = False, ""
                note6 = "" if whole else (
                    " <span style='color:#888;font-style:italic'>· selected "
                    "detail codes only</span>"
                )
                notes6 = (
                    f"<span style='color:{RED};font-style:italic'>{esc(reason)}</span>"
                    if flagged and reason else ""
                )
                rows.append(
                    "<tr style='border-bottom:1px solid #eee'>"
                    f"<td style='padding:5px 10px 5px 24px;font-weight:600;"
                    f"color:{DARK};white-space:nowrap'>{hs6}</td>"
                    f"<td style='padding:5px 10px;color:{DARK}'>{esc(d)}{note6}</td>"
                    f"<td style='padding:5px 10px'>{notes6}</td></tr>"
                )
                # Detail level: carve-out rows when pinned, else all HS-10 kids.
                if carve:
                    detail = [(r["code"], r["desc"] or "", r) for r in carve]
                else:
                    detail = [(c, dd, None) for c, dd in hs6_to_detail.get(hs6, [])]
                for code, dd, r in detail:
                    cflag = bool(r and r["flagged"])
                    cnotes = (
                        f"<span style='color:{RED};font-style:italic'>"
                        f"{esc(r['reason'])}</span>"
                        if cflag and r and r["reason"] else ""
                    )
                    rows.append(
                        "<tr style='border-bottom:1px solid #f4f4f4'>"
                        f"<td style='padding:4px 10px 4px 48px;color:{MUTED};"
                        f"white-space:nowrap'>{code}</td>"
                        f"<td style='padding:4px 10px;color:{MUTED}'>{esc(dd)}</td>"
                        f"<td style='padding:4px 10px'>{cnotes}</td></tr>"
                    )
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            + "".join(rows) + "</table>",
            unsafe_allow_html=True,
        )
        st.divider()


@st.cache_data
def load_major_importers() -> pd.DataFrame:
    """Slim importer registry (focus HS-6 codes only) from major_importers.parquet."""
    if not MAJOR_IMPORTERS_PARQUET.exists():
        return pd.DataFrame()
    df = pd.read_parquet(MAJOR_IMPORTERS_PARQUET)
    return df[~df["hs6"].isin(EXCLUDED_HS6)].copy()


def page_major_importers():
    st.title("Major importers")
    imp = load_major_importers()
    if imp.empty:
        st.error(
            "Importer data not found. Expected "
            f"`{MAJOR_IMPORTERS_PARQUET.relative_to(ROOT)}` — regenerate it from "
            "the Canadian Importers Database workbook."
        )
        st.stop()

    yr = int(imp["year"].dropna().max()) if imp["year"].notna().any() else ""
    st.markdown(
        f"Companies that imported the focused grid-equipment HS-6 codes into "
        f"Canada in **{yr}**, by country of origin and importer location. "
        "Source: StatCan Canadian Importers Database. Filter by equipment "
        "category, HS-6, origin country, or company name."
    )

    # HS-6 descriptions from the trade data.
    trade = load_data(_data_file_signature())
    hd = trade[["hs6", "hs_description"]].dropna(subset=["hs6"]).drop_duplicates("hs6")
    hs6_desc = dict(zip(hd["hs6"], hd["hs_description"].fillna("")))

    # Category type → the HS-6 codes it covers that exist in the importer data.
    cats = load_equipment_categories(
        EQUIPMENT_CATEGORIES_FILE, _path_signature(EQUIPMENT_CATEGORIES_FILE)
    )
    present = set(imp["hs6"].unique())
    cat_hs6 = {
        c["name"]: (c["hs6"] | {f[:6] for f in c["full"]}) & present for c in cats
    }
    cat_hs6 = {k: v for k, v in cat_hs6.items() if v}

    with st.sidebar:
        st.header("Filters")
        sel_cats = st.multiselect(
            "Category type",
            list(cat_hs6),
            help="Restrict to the HS-6 codes in the chosen grid-equipment "
            "categories. Leave empty for all focus codes.",
        )
        scope = (
            set().union(*[cat_hs6[c] for c in sel_cats]) if sel_cats else present
        )
        sel_hs6 = st.multiselect(
            "HS-6 code",
            sorted(scope),
            format_func=lambda c: f"{c} — {hs6_desc.get(c, '')}",
        )
        hs6_filter = set(sel_hs6) if sel_hs6 else scope
        countries = sorted(
            imp.loc[imp["hs6"].isin(hs6_filter), "country"].dropna().unique()
        )
        sel_countries = st.multiselect("Country of origin", countries)
        company_q = st.text_input("Company name contains")

    view = imp[imp["hs6"].isin(hs6_filter)]
    if sel_countries:
        view = view[view["country"].isin(sel_countries)]
    if company_q.strip():
        view = view[
            view["company"].str.contains(company_q.strip(), case=False, na=False)
        ]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Companies", f"{view['company'].nunique():,}")
    m2.metric("Origin countries", f"{view['country'].nunique():,}")
    m3.metric("HS-6 codes", f"{view['hs6'].nunique():,}")
    m4.metric("Records", f"{len(view):,}")

    if view.empty:
        st.info("No importers match the current filters.")
        st.stop()

    disp = view.copy()
    disp["description"] = disp["hs6"].map(hs6_desc)
    disp = disp[
        ["hs6", "description", "company", "country", "province", "city"]
    ].rename(
        columns={
            "hs6": "HS-6",
            "description": "Description",
            "company": "Company",
            "country": "Imported from",
            "province": "Province",
            "city": "City",
        }
    )

    fname = "major_importers"
    if sel_cats:
        fname += "_" + "_".join(
            "".join(ch for ch in c if ch.isalnum())[:12] for c in sel_cats
        )
    _excel_download(
        disp.to_csv(index=False).encode("utf-8-sig"),
        f"{fname}.csv",
        "Download importer list (CSV)",
    )
    st.dataframe(disp, hide_index=True, use_container_width=True, height=560)


def run():
    """Multipage entry point: page config + shared CSS, then navigation."""
    st.set_page_config(
        page_title="Strengthening Canada's Grid Equipment Supply Chain",
        layout="wide",
    )
    _inject_global_css()
    nav = st.navigation(
        [
            st.Page(page_dashboard, title="Trade Dashboard", icon="📊", default=True),
            st.Page(
                page_categorization,
                title="Equipment Categorization",
                icon="🗂️",
            ),
            st.Page(page_major_importers, title="Major importers", icon="🏭"),
        ]
    )
    nav.run()


if __name__ == "__main__":
    run()
