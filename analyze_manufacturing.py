"""Charts for StatCan table 16-10-0047 — Manufacturing sales, inventories & orders.

Focused on three priority NAICS industries (see naics_priority.md):
  335311  Power, distribution and specialty transformers manufacturing
  335315  Switchgear, switchboard, relay and industrial control apparatus mfg
  33592   Communication and energy wire and cable manufacturing

Only Unadjusted data exists for these detailed codes, so trends use a 12-month
rolling average rather than a seasonally-adjusted series. Some months are
suppressed by StatCan (gaps in the lines are real, not interpolated).

Reads 16100047_manufacturing_sales.parquet, writes PNGs to manufacturing_charts/.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parent
PARQUET = ROOT / "16100047_manufacturing_sales.parquet"
OUT = ROOT / "manufacturing_charts"
OUT.mkdir(exist_ok=True)

NAICS_COL = "North American Industry Classification System (NAICS)"
STAT_COL = "Principal statistics"

SHIPMENTS = "Sales of goods manufactured (shipments)"
NEW_ORDERS = "New orders, estimated values of orders received during month"
UNFILLED = "Unfilled orders, estimated values of orders at end of month"
TOTAL_INV = "Total inventory, estimated values of total inventory at end of the month"
RAW_MAT = "Raw materials, fuel, supplies, components, estimated values at end of month"
WIP = "Goods or work in process, estimated values at end of month"
FINISHED = "Finished goods manufactured, estimated values at end of  month"  # sic: double space in source

# code -> (short label, colour)
CODES = {
    "335311": ("Transformers", "#1f5fa8"),
    "335315": ("Switchgear & controls", "#c0392b"),
    "33592": ("Wire & cable", "#2e8b57"),
}

sns.set_theme(style="whitegrid", context="talk")


def load() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET)
    df["date"] = pd.to_datetime(df["REF_DATE"], format="%Y-%m")
    df["value_m"] = df["VALUE"] / 1e3  # source is in thousands -> millions of $
    return df


def series(df, stat, code, col="value_m", interpolate=True):
    """Monthly series for one NAICS code + statistic, indexed by date.

    Suppressed/missing months are linearly interpolated *between* available
    values (limit_area="inside") so gaps are bridged without extrapolating past
    the first/last real observation. Pass interpolate=False to keep raw gaps.
    """
    m = df[NAICS_COL].str.contains(f"[{code}]", regex=False) & (df[STAT_COL] == stat)
    s = df.loc[m].sort_values("date").set_index("date")[col]
    # continuous monthly index so interpolation has a row for every gap month
    full = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    s = s.reindex(full)
    if interpolate:
        s = s.interpolate(method="linear", limit_area="inside")
    return s


def millions_fmt(ax):
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}M"))


def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


# ----------------------------------------------------- 1. Sales trends (all 3)
def chart_sales_trends(df):
    fig, ax = plt.subplots(figsize=(13, 7))
    for code, (label, color) in CODES.items():
        s = series(df, SHIPMENTS, code)
        roll = s.rolling(12, min_periods=8).mean()
        ax.plot(s.index, s.values, color=color, lw=0.9, alpha=0.30)
        ax.plot(roll.index, roll.values, color=color, lw=2.6, label=f"{label} (12-mo avg)")
    ax.set_title("Monthly sales (shipments) — priority electrical industries", fontweight="bold")
    ax.set_ylabel("Sales per month")
    millions_fmt(ax)
    ax.legend(frameon=False, fontsize=12, loc="upper left")
    save(fig, "01_sales_trends.png")


# ------------------------------------------- 2. Indexed growth (2016 avg = 100)
def chart_sales_indexed(df):
    fig, ax = plt.subplots(figsize=(13, 7))
    for code, (label, color) in CODES.items():
        s = series(df, SHIPMENTS, code).rolling(12, min_periods=8).mean()
        base = s.loc["2016"].mean()
        idx = s / base * 100
        ax.plot(idx.index, idx.values, color=color, lw=2.6, label=label)
    ax.axhline(100, ls="--", lw=1.1, color="#888")
    ax.set_title("Sales growth indexed to 2016 average = 100", fontweight="bold")
    ax.set_ylabel("Index (2016 = 100)")
    ax.legend(frameon=False, fontsize=12, loc="upper left")
    save(fig, "02_sales_indexed.png")


# ------------------------------------- 3. Inventory components per code (facets)
def chart_inventory_components(df):
    fig, axes = plt.subplots(1, 3, figsize=(19, 6.5), sharex=True)
    for ax, (code, (label, _)) in zip(axes, CODES.items()):
        raw = series(df, RAW_MAT, code)
        wip = series(df, WIP, code)
        fin = series(df, FINISHED, code)
        # series() already interpolates internal gaps; drop any leading/trailing
        # NaN rows so stackplot (which can't take NaN) stays continuous.
        comp = pd.concat([raw, wip, fin], axis=1).dropna()
        ax.stackplot(
            comp.index, comp.iloc[:, 0], comp.iloc[:, 1], comp.iloc[:, 2],
            labels=["Raw materials", "Work in process", "Finished goods"],
            colors=["#8e8e93", "#f0ad4e", "#5cb85c"], alpha=0.9,
        )
        ax.set_title(label, fontweight="bold", fontsize=15)
        millions_fmt(ax)
    axes[0].set_ylabel("Inventory value (end of month)")
    axes[0].legend(frameon=False, fontsize=11, loc="upper left")
    fig.suptitle("Inventories by stage — priority electrical industries", fontweight="bold", y=1.02)
    fig.text(0.5, -0.02, "Suppressed months linearly interpolated between available values; Wire & cable has the most gaps.",
             ha="center", fontsize=11, style="italic", color="#666")
    save(fig, "03_inventory_components.png")


# --------------------------------------- 4. Orders: new received & unfilled backlog
def chart_orders(df):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 10), sharex=True)
    for code, (label, color) in CODES.items():
        new = series(df, NEW_ORDERS, code).rolling(12, min_periods=8).mean()
        unf = series(df, UNFILLED, code)
        ax1.plot(new.index, new.values, color=color, lw=2.4, label=label)
        ax2.plot(unf.index, unf.values, color=color, lw=2.4, label=label)
    ax1.set_title("New orders received per month (12-mo avg)", fontweight="bold")
    ax1.set_ylabel("Value")
    millions_fmt(ax1)
    ax1.legend(frameon=False, fontsize=12, loc="upper left")
    ax2.set_title("Unfilled orders — backlog at end of month", fontweight="bold")
    ax2.set_ylabel("Value")
    millions_fmt(ax2)
    save(fig, "04_orders.png")


# ------------------------------- 5. Inventory-to-sales ratio (computed per code)
def chart_inv_sales_ratio(df):
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for code, (label, color) in CODES.items():
        inv = series(df, TOTAL_INV, code)
        sales = series(df, SHIPMENTS, code)
        ratio = (inv / sales).rolling(6, min_periods=4).mean()
        ax.plot(ratio.index, ratio.values, color=color, lw=2.4, label=label)
    ax.set_title("Inventory-to-sales ratio (total inventory ÷ monthly sales)", fontweight="bold")
    ax.set_ylabel("Ratio")
    ax.legend(frameon=False, fontsize=12, loc="upper left")
    save(fig, "05_inventory_to_sales_ratio.png")


# ----------------------- 6. Unfilled-orders-to-sales ratio — one chart per code
def chart_unfilled_to_sales(df):
    for code, (label, color) in CODES.items():
        unf = series(df, UNFILLED, code)
        sales = series(df, SHIPMENTS, code)
        ratio = unf / sales  # backlog expressed in months of current sales
        roll = ratio.rolling(6, min_periods=4).mean()
        fig, ax = plt.subplots(figsize=(13, 6.5))
        ax.plot(ratio.index, ratio.values, color=color, lw=1.0, alpha=0.35, label="Monthly")
        ax.plot(roll.index, roll.values, color=color, lw=2.8, label="6-mo avg")
        valid = ratio.dropna()
        if not valid.empty:
            ax.axhline(valid.mean(), ls="--", lw=1.1, color="#888",
                       label=f"mean = {valid.mean():.1f}")
        ax.set_title(f"Unfilled orders ÷ sales — {label} [{code}]", fontweight="bold")
        ax.set_ylabel("Ratio")
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=12, loc="upper left")
        if valid.index.max() < pd.Timestamp("2025-01-01"):
            ax.text(0.99, 0.02, f"backlog data ends {valid.index.max():%Y-%m}",
                    transform=ax.transAxes, ha="right", fontsize=10,
                    style="italic", color="#666")
        save(fig, f"06_unfilled_to_sales_{code}.png")


# -------- 7. Unfilled-to-sales ratio for the parent group NAICS 3353 (rollup)
def chart_ratio_3353(df):
    code, label, color = "3353", "Electrical equipment mfg", "#6a4c93"
    unf = series(df, UNFILLED, code)
    sales = series(df, SHIPMENTS, code)
    ratio = unf / sales
    roll = ratio.rolling(6, min_periods=4).mean()
    fig, ax = plt.subplots(figsize=(13, 6.5))
    ax.plot(ratio.index, ratio.values, color=color, lw=1.0, alpha=0.35, label="Monthly")
    ax.plot(roll.index, roll.values, color=color, lw=2.8, label="6-mo avg")
    valid = ratio.dropna()
    ax.axhline(valid.mean(), ls="--", lw=1.1, color="#888", label=f"mean = {valid.mean():.1f}")
    ax.set_title(f"Unfilled orders ÷ sales — {label} [{code}]", fontweight="bold")
    ax.set_ylabel("Ratio")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=12, loc="upper left")
    save(fig, "07_unfilled_to_sales_3353.png")


def main():
    df = load()
    chart_sales_trends(df)
    chart_sales_indexed(df)
    chart_inventory_components(df)
    chart_orders(df)
    chart_inv_sales_ratio(df)
    chart_unfilled_to_sales(df)
    chart_ratio_3353(df)
    print(f"\nAll charts written to {OUT}")


if __name__ == "__main__":
    main()
