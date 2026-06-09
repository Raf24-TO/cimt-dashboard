# Price Adjustments

Use Statistics Canada's **Industrial Product Price Index (IPPI)** to convert
nominal CAD values across years into a single base year (2025 CAD), so that
imports from different years can be compared on equivalent purchasing-power
terms.

## Source data

**Series:** Industrial product price index, by major product group, monthly
**Classification:** North American Product Classification System (NAPCS)
**Group:** Electrical, electronic, audiovisual and telecommunication products
**NAPCS code:** P73
**Geography:** Canada
**Index base:** 2020 = 100 (annual average)

| Year | Avg. Annual IPPI | YoY Change |
|------|------------------|------------|
| 2016 |  99.98           | —          |
| 2017 |  99.25           | −0.7%      |
| 2018 |  99.58           | +0.3%      |
| 2019 | 100.53           | +1.0%      |
| 2020 | 100.00           | −0.5%      |
| 2021 | 106.26           | +6.3%      |
| 2022 | 121.44           | +14.3%     |
| 2023 | 128.52           | +5.8%      |
| 2024 | 134.35           | +4.5%      |
| 2025 | 142.03           | +5.7%      |

**Note:** the index was nearly flat from 2016 to 2020 (electrical-equipment
prices barely moved, even falling slightly in 2017 and 2020). The cumulative
~42% rise in 2025 CAD relative to 2020 is driven almost entirely by the
2021–2022 supply-chain shock and the continued ~5%/year growth since.

## Adjustment formula

For a nominal value `V` recorded in year `Y`, the equivalent value in 2025 CAD is:

```
V_2025 = V × (IPPI_2025 / IPPI_Y)
```

Pre-computed multipliers (base year = 2025):

| Year | IPPI   | × Multiplier to 2025 CAD |
|------|--------|--------------------------|
| 2016 |  99.98 | 1.4206                   |
| 2017 |  99.25 | 1.4310                   |
| 2018 |  99.58 | 1.4263                   |
| 2019 | 100.53 | 1.4128                   |
| 2020 | 100.00 | 1.4203                   |
| 2021 | 106.26 | 1.3367                   |
| 2022 | 121.44 | 1.1696                   |
| 2023 | 128.52 | 1.1051                   |
| 2024 | 134.35 | 1.0572                   |
| 2025 | 142.03 | 1.0000                   |

## Brainstorm: how to apply this in the dashboard

### 1. Where in the pipeline to apply the deflator

Applying *after* the year/HS filter but *before* any aggregation keeps the
cached raw `df` immutable (good for Streamlit's `@st.cache_data`) and only
multiplies the small filtered slice. Both `view` (year-filtered) and `bar_view`
(all-years, used for the stacked bar + YoY insights) need the same treatment so
the bar chart shows real-terms growth instead of inflation.

```python
factor = view["year"].map(year_to_multiplier).fillna(1.0)
view = view.assign(value_cad=view["value_cad"] * factor)
```

### 2. Which IPPI series to use

The P73 group is a strong fit for **Tier 1** equipment (8504, 8535, 8536, 8537,
8544 — all electrical/electronic) and **Tier 2** (8532 — capacitors). It is a
worse fit for **Critical Inputs**:

| HS code | What it covers      | Better-fitting IPPI         |
|---------|---------------------|-----------------------------|
| 7225/7226/7308 | Steel mill products / structures | Primary metals — iron & steel (P32) |
| 7407/7408/7413 | Copper rod, wire, conductors | Copper products (sub-series of P32) |
| 7604/7605/7614 | Aluminum rod, wire, conductors | Aluminum products (sub-series of P32) |
| 8546/8547      | Insulators / insulating fittings | P73 is fine                 |

**Recommendation:** ship with P73 applied uniformly as a v1 (simple, transparent,
correct for the bulk of the dollar volume which is Tier 1). Note in the UI that
metals deflation is approximate. Add per-tier deflators in v2 if the analysis
needs metal-price separation.

### 3. Coverage

The trade data spans **2016–2025** and the IPPI table now covers all of those
years, so every row in the dashboard has a deflator available — no
out-of-coverage warning is needed in normal use. The "missing year" code path
is still worth keeping in case the data is ever extended further back than the
IPPI; it should fall back to nominal CAD for those rows and flag them to the
user.

### 4. UI presentation

- **Toggle location:** top-right of the page, opposite the title, using a
  `st.radio` (horizontal) or `st.segmented_control` for a clear two-state
  switch labelled `Nominal CAD` / `2025 CAD`.
- **Persist state:** Streamlit auto-persists widget state across reruns; no
  extra `session_state` plumbing needed.
- **Surface the basis everywhere a dollar value appears:** the headline
  metric label, the bar-chart y-axis title, map tooltips, the origin
  breakdown column header, and the YoY insights table. Easiest is a single
  `basis_label` string ("nominal CAD" / "2025 CAD") interpolated into all
  those captions.
- **YoY insights:** with the toggle on, the YoY changes become *real* changes
  (volume + price-relative-to-electrical-equipment-inflation), which is
  arguably more useful for spotting structural shifts. Worth keeping the
  default on `Nominal CAD` so the dashboard matches the underlying CSV when
  cross-referencing.

### 5. Open questions

- Do we want a small **info popover** next to the toggle citing the IPPI
  source / NAPCS code so a viewer knows what's being applied?
- Should the **map circle sizes** stay value-driven (and so re-scale with
  basis) or normalize within the selected year so the map looks the same
  regardless of toggle state? Default: value-driven, since the rest of the
  dashboard already does that.
- Long term: **monthly** deflation if we ever break out monthly views. The
  StatCan table is monthly; we're collapsing to annual here.
