# Strengthening Canada's Grid-Equipment Supply Chain — Insights (first draft)

> Working draft. The focus right now is **Section 1 (Import concentration)**;
> Sections 2 and 3 are stubbed with their agreed scope and methodology so the
> structure is visible, to be developed next. All figures recomputed from
> `cimt_output/cimt_trade_slim.parquet`; refine before circulation.

## Report structure (all three sections share one shape)

Each section is written in two parts, so the analysis is auditable and the
takeaways are easy to find:

1. **Data and methodology** — the source(s) and how they were processed (the
   grid-specific cut on the trade data; the HS→category concordance; the
   NAICS→I/O mapping; the filtering to grid-relevant NAICS codes). Concise, but
   specific enough that a reader sees the analytical basis.
2. **Key insights** — the findings *and the "so what":* why it matters, what it
   reveals that wasn't visible before, and how it should inform decisions about
   where to build domestic capacity or manage supply risk.

---

## 1. Import concentration [NM1.1]

### Data and methodology

Drawn directly from the grid-equipment trade dataset — StatCan's **Canadian
International Merchandise Trade (CIMT)**, imports flow, 2016–2025. The value of
this analysis is **not** the underlying trade data (NRCan can obtain that from
StatCan) but two layers built on top of it:

- **The grid-specific cut.** 67 HS-6 codes were selected as grid equipment plus
  its upstream feedstock and grouped into plain-English equipment categories via
  a curated concordance (see the Appendix). For the two categories where the
  HS-6 is too broad, the cut descends to HS-10 detail so the figure captures only
  the grid-relevant slice — large power transformers isolated to `8504230030`
  (>100 MVA, liquid-dielectric), HVDC converters to the high-power converter
  codes, excluding consumer power supplies and chargers. This grid-equipment cut,
  plus the concordance, is the part NRCan is unlikely to have produced.
- **Concentration measured consistently.** For each category and year we compute
  total import value, partner count, top-partner shares, and a Herfindahl–
  Hirschman Index (HHI) on the country-share distribution — so "concentration" is
  quantified, not asserted. **All dollar figures are in constant 2025 CAD**
  (nominal CAD deflated by the StatCan IPPI, NAPCS P73, rebased to 2025 = 1.0),
  so growth reflects real volume rather than price inflation. Concentration
  shares are basis-independent. Figures **exclude HS-6 `850431` (≤1 kVA) and
  `850432` (>1–16 kVA)** — sub-grid-scale control/electronic transformers — and
  the **HS-4 9030 measuring instruments** (`903031/032/033/039/084/089` —
  multimeters, oscilloscopes, electrical-quantity meters; predominantly non-grid
  lab/test gear), to match the dashboard's grid-scope definition.

### Key insights

**1. The aggregate picture looks reassuring — and that is the trap.** In constant
2025 CAD, grid-equipment imports grew from ~$14.3B (2016) to ~$17.4B (2025) — a
real increase of just **~22%** over the decade. (The headline +73% nominal growth
is mostly price inflation, not rising volume.) On supplier mix, the U.S. share
*eased* from 46% to 42%, the
top-three share from 72% to 66%, and the aggregate HHI from 0.25 to 0.21. Read
alone, this says Canada's supplier base is broad and slowly diversifying.

**2. Concentration is highly uneven by component — and inverted from intuition.**
The aggregate average hides the real story. The most strategically critical,
longest-lead, hardest-to-replace item — **large power transformers (>100 MVA)** —
is the *most diversified* slice we track: $204M in 2025 across 10 countries with
**no U.S. supplier in the top four** (South Korea 21%, Poland 16%, Austria 15%,
China 12%; HHI 0.14). The *commodity backbone* items — the ones every line build
consumes — are the concentrated ones:

| Slice (2025 imports) | Value | Top supplier(s) | Top-3 | HHI |
|---|---|---|---|---|
| Overhead conductor | $0.34B | **U.S. 59%** | 84% | 0.39 |
| HV switchgear | $0.52B | **U.S. 53%** | 77% | 0.32 |
| Underground/submarine cable | $3.27B | **U.S. 51%**, China 23% | 81% | 0.32 |
| Electrical steel (raw feedstock) | $0.71B | **Japan 33%, U.S. 32%**, Korea 15% | 79% | 0.24 |
| MV switchgear | $2.66B | U.S. 37%, Mexico 18%, China 13% | 68% | 0.20 |
| Large power transformer (>100 MVA) | $0.20B | Korea 21%, Poland 16% | 53% | 0.14 |

**3. The U.S. exposure is concrete, and it sits in the high-volume backbone.**
Roughly *half* of Canada's switchgear, cable, and conductor imports come from a
single country. In a tariff or border-disruption scenario the risk is not in
exotic high-voltage hardware — it's in the commodity components that every
distribution build-out needs, and the aggregate HHI masks it.

**4. The China exposure is steady and cable-shaped.** China holds a stable ~14%
of total grid imports (2016: 15.2% → 2025: 14.1%), but it is concentrated in
underground/submarine cable — ~$0.75B, about 23% of that category, essentially
unchanged for a decade. So the China question is narrow and specific (cable),
not diffuse.

**5. The upstream chokepoint is electrical steel.** Grain-oriented electrical
steel — the core input to *every* transformer — has effectively no Canadian
production, and ~80% of imports come from just three countries (Japan, U.S.,
Korea). Any domestic transformer strategy inherits this dependency one tier up;
building transformer capacity without securing core-steel supply moves the
bottleneck rather than removing it.

**So what — for investment and risk decisions:**

- **Split the strategy by component, not by aggregate.** *Hedge* the concentrated
  commodity items where domestic greenfield is hard to justify (conductor,
  commodity cable) via multi-sourcing, qualified second suppliers, and strategic
  inventory. *Prioritize domestic capacity / friend-shoring* where concentration
  meets strategic criticality and an existing industrial base — transformers and
  their steel feedstock.
- **Large power transformers need resilience, not de-concentration.** They are
  already well-diversified across allied suppliers; the exposure there is
  lead-time and surge capacity, not single-source risk.
- **Don't read slow diversification as self-correction.** Three points of U.S.
  share over a decade, with backbone components still ~50% single-sourced, means
  the market is not resolving the concentration on its own.

---

## 2. Import dependency (high level) *(to develop)*

### Data and methodology
Triangulate the grid-equipment **import dollar values** (Section 1) against
**sector size** by mapping the relevant NAICS into StatCan's **input–output
tables** (GDP, value-added), consistent with the BDC work. This reframes raw
import dollars as a *dependency ratio* — imports relative to domestic
value-added / sector output — rather than an absolute number.

### Key insights *(to develop)*
- Express import reliance as a share of sector size to show how much of domestic
  grid-equipment demand is met from abroad vs. produced at home.
- Connect to Section 1: the components that are both import-concentrated *and*
  high-dependency are the priority targets.

---

## 3. Evidence of domestic capacity constraints *(to develop)*

### Data and methodology
StatCan **unfilled orders** from Manufacturers' Sales, Inventories and Orders
(**Table 16-10-0047-01**), filtered to the three relevant NAICS codes —
transformer (335311), switchgear (335315), and wiring-device manufacturing
(33592) — showing the backlog ramp after 2022.

### Key insights *(to develop)*
- Preliminary signal: transformer unfilled-orders-to-sales backlog roughly
  **doubled (~4.7 → ~9.6 months)** since 2016, the clearest capacity-constraint
  evidence; switchgear milder; wire & cable backlog series ends early (2023).
- Ties the report together: demand is outrunning domestic transformer capacity at
  the same time that imports are concentrated and feedstock is import-dependent.

---

## Appendix [NM2.1]
**Concordance table** — grid-equipment categories mapped to HS-4 / HS-6 / HS-10
codes (with the carve-out detail codes and forced-fit flags). Source of record:
`equipment_categories.md` / `hs_priority_6.md`.

---

### Open items for Section 1
- Extend the per-component concentration table to all categories, or keep to the
  strategically salient subset shown?
