# Grid-Equipment Categorization

Maps every HS-6 code in `hs_priority_6.md` (67 codes) to one of the equipment
categories you specified, plus a **Raw Materials** bucket (the former
"Critical Inputs", renamed). All 67 codes are assigned.

**Method caveat.** HS codes classify goods by *what they are* (product type,
voltage band, power rating, material), not by *where they're used*. Your
categories are application/equipment buckets, so some codes are forced into
their nearest home. Weak/forced fits are marked **⚠ FLAG** with the reason and
listed together at the bottom — review those and move any you disagree with.

Decisions applied per your review:
- **8536 (≤1,000 V) switchgear** → folded into *Medium-Voltage Switchgear* (no separate LV bucket).
- **Non-grid / electronic codes** → forced into nearest best-fit category (all flagged).
- **Transmission towers (730820)** → grouped with *Overhead Conductor*.
- **Large Power Transformer split at HS-10** → `8504230030` (>100 MVA) only; the rest of
  850423 (lower bands, exports, pre-2019 imports) drops to *Medium / Substation Transformer*.
  Note: this category is therefore **imports-only, 2019 onward** — HS-8 exports and 2016–2018
  imports have no >100 MVA breakout.
- **HVDC Converter Station refined at HS-10** → high-power converter codes only (drops PC/IT
  power supplies, battery/USB chargers, motor drives), cutting the import base from $20.8B to
  ~$9.9B. Includes the `8504409099` "static converters, nes" catch-all (flagged). Exports
  (HS-8 `85044000`) can't be refined.
- **Underground / Submarine Cable** → kept whole at HS-6 (`854460` = all HV insulated power
  cable). The submarine-specific HS-10 (`8544601000`) is noted only as an optional sub-figure,
  not the definition (narrowing to it would drop all underground cable).

---

## 1. Large Power Transformer (≥100 MVA)

Defined at **HS-10** (imports only, 2019+).

| Code | Level | Description | Reasoning |
|------|-------|-------------|-----------|
| 8504230030 | HS-10 | Liquid dielectric transformers, >100,000 kVA (>100 MVA) | Cleanly isolates >100 MVA. Import-side only; no HS-8 export equivalent and not reported before 2019. |

## 2. Medium / Substation Transformer

The remainder of 850423 (everything except the >100 MVA HS-10) lands here.

| Code | Level | Description | Reasoning |
|------|-------|-------------|-----------|
| 850421 | HS-6 | Liquid dielectric transformers, ≤650 kVA | Distribution/substation-scale liquid-filled units. |
| 850422 | HS-6 | Liquid dielectric transformers, >650 ≤10,000 kVA | Core substation/distribution power transformer band. |
| 850433 | HS-6 | Transformers, >16 ≤500 kVA, nes | Dry-type distribution/substation transformers. |
| 850434 | HS-6 | Transformers, >500 kVA, nes | Larger dry-type substation transformers. |
| 8504230010 | HS-10 | Liquid dielectric transformers, >10,000 ≤59,000 kVA (10–59 MVA) | Below the LPT threshold; substation power transformer. |
| 8504230020 | HS-10 | Liquid dielectric transformers, >59,000 ≤100,000 kVA (59–100 MVA) | Below the LPT threshold; substation power transformer. |
| 8504230000 | HS-10 | Liquid dielectric transformers, >10,000 kVA (imports 2016–2018, no band detail) | Pre-2019 aggregate of the >10 MVA band; no >100 MVA breakout available. |
| 85042300 | HS-8 | Liquid dielectric transformers, >10,000 kVA (domestic exports) | Exports have no band split; the whole >10 MVA bucket sits here. |

## 3. High-Voltage Switchgear

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 853510 | Electrical fuses, >1,000 V | HV protective fuses. |
| 853529 | Automatic circuit breakers, >1,000 V, nes | "nes" = ≥72.5 kV breakers → transmission/HV. |
| 853590 | Switching/protecting apparatus, >1,000 V, nes | Catch-all HV switching/protection gear. |
| 853540 | Lightning arresters, surge suppressors, >1,000 V | ⚠ FLAG — Surge protection, not switchgear proper; no arrester bucket, parked in HV. |

## 4. Medium-Voltage Switchgear

Includes 8536 (≤1,000 V, technically Low-Voltage) folded in per your decision.

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 853521 | Automatic circuit breakers, >1,000 V but <72.5 kV | ⚠ FLAG — Straddles MV/sub-transmission; MV vs HV boundary fuzzy. |
| 853610 | Electrical fuses, ≤1,000 V | ⚠ FLAG — Technically LV; folded into MV. |
| 853620 | Automatic circuit breakers, ≤1,000 V | ⚠ FLAG — Technically LV; folded into MV. |
| 853630 | Apparatus for protecting circuits, ≤1,000 V, nes | ⚠ FLAG — Technically LV; folded into MV. |
| 853650 | Electrical switches, ≤1,000 V, nes | ⚠ FLAG — Technically LV; much is non-grid (industrial/building). |
| 853690 | Switching/protecting apparatus, ≤1,000 V, nes | ⚠ FLAG — Technically LV; broad catch-all. |

## 5. Underground / Submarine Cable

Kept whole at HS-6 — all HV insulated power cable is underground or submarine
(overhead lines are bare conductors in 7413/7614).

| Code | Level | Description | Reasoning |
|------|-------|-------------|-----------|
| 854460 | HS-6 | Insulated electric conductors, >1,000 V, nes | All HV insulated power cable (underground + submarine). |

*Optional sub-figure:* `8544601000` ("flameproof for mines; submarine cables", ~$157M imports)
isolates the explicitly-submarine slice if you ever want an "of which submarine" callout.
| 854420 | Co-axial cable and co-axial conductors | ⚠ FLAG — Telecom/signal cable, not power; forced to nearest cable bucket. |
| 854442 | Insulated conductors ≤1,000 V, w/ connectors | ⚠ FLAG — LV cable, much non-grid; forced to nearest cable bucket. |
| 854449 | Insulated conductors ≤80 V, nes | ⚠ FLAG — LV/electronics wiring; forced to nearest cable bucket. |

## 6. HVDC Converter Station

Refined at **HS-10** (imports) to high-power converters; exports are a single
un-splittable HS-8 code. Excludes PC/ADP power supplies ($2.0B), generic power
supplies nes ($4.2B), battery/USB chargers ($1.7B), and motor speed-drive
controllers ($1.7B) — all non-grid.

| Code | Level | Description | Value (imp) | Reasoning |
|------|-------|-------------|-------------|-----------|
| 8504409032 | HS-10 | Inverters (incl. >100 A converting element) | $2,990M | High-power inverter — grid/solar. |
| 8504409035 | HS-10 | Power supplies, with a device >100 A | $447M | High-power industrial converter. |
| 8504409039 | HS-10 | Semiconductor converters, >100 A | $436M | High-power converter. |
| 8504409031 | HS-10 | Rectifiers, with/without device >100 A | $432M | High-power AC→DC. |
| 8504409034 | HS-10 | Direct current converters, >100 A | $420M | High-power DC. |
| 8504409033 | HS-10 | AC & cycle converters, >100 A | $166M | High-power converter. |
| 8504409099 | HS-10 | Static converters, nes | $4,993M | ⚠ FLAG — catch-all; ~half the category, grid relevance uncertain (included per review). |
| 85044000 | HS-8 | Static electric converters, nes (domestic exports) | $3,967M (exp) | ⚠ FLAG — exports can't be refined; includes the same non-grid mix as imports. |

## 7. Overhead Conductor

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 741300 | Stranded copper wire/cable, not insulated | Bare copper overhead/earthing conductor. |
| 761410 | Stranded aluminum, steel core, not insulated | ACSR — dominant overhead transmission conductor. |
| 761490 | Stranded aluminum, not insulated, nes | All-aluminum overhead conductor (AAC/AAAC). |
| 730820 | Towers and lattice masts, iron or steel | ⚠ FLAG — Transmission towers (the structures that carry overhead lines); 7308 also covers bridges/building frames, so trade volume isn't tower-specific. |

## 8. Substation reactive-power equipment (shunt reactors, capacitor banks, SVC/STATCOM)

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 853210 | Fixed capacitors, 50/60 Hz, ≥0.5 kvar | Power-factor / capacitor-bank capacitors — direct fit. |
| 850450 | Inductors, electric | ⚠ FLAG — Maps to shunt reactors, but also includes small electronic inductors/chokes. |
| 853229 | Fixed capacitors, nes | ⚠ FLAG — Mostly electronic capacitors, not reactive-power banks; forced to nearest bucket. |
| 853230 | Variable/adjustable capacitors | ⚠ FLAG — Electronics tuning components; forced to nearest bucket. |
| 853290 | Parts of capacitors | ⚠ FLAG — Component parts; forced to nearest bucket. |

## 9. Protection & Control panels

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 853710 | Boards/panels/consoles, ≤1,000 V | LV control & relay panels. |
| 853720 | Boards/panels/consoles, >1,000 V | HV switchboards / control panels. |
| 853649 | Electrical relays, >60 V ≤1,000 V | Protective relays. |
| 853641 | Electrical relays, ≤60 V | ⚠ FLAG — LV control relays; some non-grid (auto/electronics). |
| 903033 | Instruments measuring voltage/current/power, w/o recording, nes | ⚠ FLAG — Grid metering vs lab/test indistinguishable in HS. |
| 903084 | Instruments measuring electrical quantities, with recording, nes | ⚠ FLAG — Could be PMU/recording metering, but mostly test instruments. |
| 903031 | Multimeters, w/o recording | ⚠ FLAG — Predominantly lab/test, not grid. |
| 903032 | Multimeters, with recording | ⚠ FLAG — Predominantly lab/test, not grid. |
| 903039 | Instruments measuring voltage/current, w/o recording dev | ⚠ FLAG — Broad lab/test category. |
| 903089 | Instruments measuring electrical quantities, nes | ⚠ FLAG — Broad lab/test category. |

## 10. Disconnect Switches (HV/MV)

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 853530 | Isolating switches and make-and-break switches, >1,000 V | Exactly disconnect/isolator switches at HV/MV. Clean fit. |

## 11. Raw Materials

Upstream materials and components feeding manufacture of the equipment above
(formerly labelled "Critical Inputs").

| HS-6 | Description | Reasoning |
|------|-------------|-----------|
| 722511 | Silicon-electrical (GO) steel, ≥600 mm, grain oriented | Transformer core steel (GOES). |
| 722519 | Silicon-electrical steel, ≥600 mm, nes | Transformer core steel (NOES/GOES). |
| 722611 | Silicon-electrical steel, <600 mm, grain oriented | Transformer core steel, narrow strip. |
| 722619 | Silicon-electrical steel, <600 mm, nes | Transformer core steel, narrow strip. |
| 740710 | Copper bars, rods, profiles | Feedstock for winding wire / busbar. |
| 740811 | Copper wire, >6 mm | Conductor/winding feedstock. |
| 740819 | Copper wire, ≤6 mm | Conductor/winding feedstock. |
| 740821 | Copper-zinc (brass) wire | Hardware/connector feedstock. |
| 740829 | Copper alloy wire, nes | Conductor/connector feedstock. |
| 760410 | Aluminum bars, rods, profiles, not alloyed | Conductor rod stock. |
| 760421 | Aluminum hollow profiles, alloyed | Busbar/structural stock. |
| 760429 | Aluminum bars, rods, profiles, alloyed | Conductor rod stock. |
| 760511 | Aluminum wire, not alloyed, >7 mm | Drawn-wire stock for stranding. |
| 760519 | Aluminum wire, not alloyed, ≤7 mm | Drawn-wire stock for stranding. |
| 760521 | Aluminum alloy wire, >7 mm | Drawn-wire stock for stranding. |
| 760529 | Aluminum alloy wire, ≤7 mm | Drawn-wire stock for stranding. |
| 854411 | Winding wire, insulated, copper | Transformer/motor winding wire. |
| 854419 | Winding wire, insulated, o/t copper | Transformer/motor winding wire. |
| 854610 | Insulators, electrical, glass | Line/substation insulators (component). |
| 854620 | Insulators, electrical, ceramic | Line/substation insulators (component). |
| 854690 | Insulators, electrical, nes | Composite insulators (component). |
| 854710 | Insulating fittings, ceramic | Bushings/spacers. |
| 854720 | Insulating fittings, plastic | Bushings/spacers. |
| 854790 | Insulating fittings, nes | Bushings/spacers. |
| 850490 | Parts of transformers, static converters and inductors | ⚠ FLAG — Parts/components code spanning Transformers + HVDC + Reactive; can't be cleanly attributed to one equipment category, so grouped as a component input. |

---

## ⚠ Flagged for your review (forced or weak fits)

These are assigned but worth a second look — move any you disagree with.

| HS-6 | Assigned to | Why flagged |
|------|-------------|-------------|
| 853540 | High-Voltage Switchgear | Surge arresters; no dedicated bucket. |
| 853521 | Medium-Voltage Switchgear | <72.5 kV — MV/HV boundary fuzzy. |
| 853610 | Medium-Voltage Switchgear | ≤1 kV (LV) folded into MV. |
| 853620 | Medium-Voltage Switchgear | ≤1 kV (LV) folded into MV. |
| 853630 | Medium-Voltage Switchgear | ≤1 kV (LV) folded into MV. |
| 853650 | Medium-Voltage Switchgear | ≤1 kV (LV); much non-grid. |
| 853690 | Medium-Voltage Switchgear | ≤1 kV (LV); broad catch-all. |
| 854420 | Underground / Submarine Cable | Coax — telecom/signal, not power. |
| 854442 | Underground / Submarine Cable | LV cable; much non-grid. |
| 854449 | Underground / Submarine Cable | ≤80 V — LV/electronics wiring. |
| 8504409099 | HVDC Converter Station | "Static converters, nes" catch-all; ~half the import value, grid relevance uncertain. |
| 85044000 | HVDC Converter Station | Export HS-8 — can't refine; includes non-grid converters. |
| 730820 | Overhead Conductor | Towers; 7308 also bridges/buildings. |
| 850450 | Substation reactive-power equipment | Inductors; includes electronic chokes. |
| 853229 | Substation reactive-power equipment | Capacitors nes — mostly electronic. |
| 853230 | Substation reactive-power equipment | Variable capacitors — electronics. |
| 853290 | Substation reactive-power equipment | Parts of capacitors. |
| 853641 | Protection & Control panels | ≤60 V control relays; some non-grid. |
| 903031 | Protection & Control panels | Multimeters — lab/test. |
| 903032 | Protection & Control panels | Multimeters — lab/test. |
| 903033 | Protection & Control panels | Metering vs lab/test indistinguishable. |
| 903039 | Protection & Control panels | Broad lab/test. |
| 903084 | Protection & Control panels | Recording metering vs test. |
| 903089 | Protection & Control panels | Broad lab/test. |
| 850490 | Raw Materials | Parts of transformers/converters/inductors; spans categories, grouped as component input. |
