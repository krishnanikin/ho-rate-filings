"""Build analysis tables in data/processed.

python -m ho_rate_filings.features

Outputs
-------
filings.parquet            one row per filing (CA, FL, TX) with regime, period, durations,
                           haircut and lagged disaster/housing drivers for the filing state
company_state_year.parquet top-10 groups x filing state x year: counts, rejection rates,
                           approval days, requested/approved rate change
state_year.parquet         all 51 jurisdictions x year: regime, disasters, housing, FIO
                           premium/loss/nonrenewal, population, and filing metrics where
                           available
"""

from loguru import logger
import numpy as np
import pandas as pd
import typer

from ho_rate_filings.config import (
    COVID_BREAK,
    DRIVER_START_YEAR,
    EXTERNAL_DATA_DIR,
    INTERIM_DATA_DIR,
    PROCESSED_DATA_DIR,
    START_YEAR,
    STATES,
)

app = typer.Typer()

GROUP_ORDER = [
    "State Farm",
    "Allstate",
    "USAA",
    "Liberty Mutual",
    "Farmers",
    "Travelers",
    "American Family",
    "Nationwide",
    "Chubb",
    "Erie",
    "Other",
]


def period_label(year: pd.Series) -> pd.Series:
    return np.where(
        year < COVID_BREAK,
        f"Pre-COVID ({START_YEAR}-{COVID_BREAK - 1})",
        f"Post-COVID ({COVID_BREAK}+)",
    )


def enrich_filings(
    filings: pd.DataFrame, regimes: pd.DataFrame, drivers: pd.DataFrame
) -> pd.DataFrame:
    df = filings.copy()
    # Filing year: received date where known; otherwise the CA file-number year prefix or
    # the closing year.
    ca_year = pd.to_numeric(df["filing_id"].str.extract(r"^(\d{2})-")[0], errors="coerce") + 2000
    df["year"] = (
        df["received_date"]
        .dt.year.fillna(ca_year.where(df["state"] == "CA"))
        .fillna(df["closed_date"].dt.year)
    ).astype("Int64")
    df = df[df["year"] >= START_YEAR]
    df["period"] = period_label(df["year"])
    df["post_covid"] = (df["year"] >= COVID_BREAK).astype(int)
    df = df.merge(regimes[["state", "regime", "regime_name"]], on="state", how="left")

    df["days_to_close"] = (df["closed_date"] - df["received_date"]).dt.days
    df.loc[df["days_to_close"] < 0, "days_to_close"] = np.nan
    df["days_to_approval"] = df["days_to_close"].where(df["outcome"] == "approved")
    df["days_to_effective"] = (df["effective_date"] - df["received_date"]).dt.days
    df["haircut_pts"] = df["requested_pct"] - df["approved_pct"]
    df["haircut"] = (df["haircut_pts"] > 0.05).where(
        (df["outcome"] == "approved") & df["requested_pct"].notna() & df["approved_pct"].notna()
    )
    for flag in ["approved", "disapproved", "withdrawn"]:
        df[f"is_{flag}"] = (df["outcome"] == flag).astype(int)
    df["is_rejected_broad"] = df["is_disapproved"] | df["is_withdrawn"]
    df["dispositioned"] = df["outcome"].isin(["approved", "disapproved", "withdrawn"])
    df["top10"] = df["group"] != "Other"

    lagged = drivers.copy()
    lag_cols = [
        "damage_pc",
        "damage_pc_hurricane",
        "damage_pc_wildfire",
        "fema_assistance_pc",
        "hpi_growth",
        "ppi_res_construction_growth",
    ]
    for lag in (1, 2):
        shifted = lagged[["state", "year", *lag_cols]].copy()
        shifted["year"] += lag
        df = df.merge(
            shifted.rename(columns={c: f"{c}_l{lag}" for c in lag_cols}),
            on=["state", "year"],
            how="left",
        )
    df["group"] = pd.Categorical(df["group"], GROUP_ORDER)
    return df.reset_index(drop=True)


def company_state_year(df: pd.DataFrame) -> pd.DataFrame:
    rate = df[df["is_rate"].fillna(False)]
    disp = rate[rate["dispositioned"]]
    g = ["state", "group", "year"]
    counts = rate.groupby(g, observed=True).agg(rate_filings=("filing_id", "nunique"))
    outcomes = disp.groupby(g, observed=True).agg(
        dispositioned=("filing_id", "nunique"),
        disapproved=("is_disapproved", "sum"),
        withdrawn=("is_withdrawn", "sum"),
    )
    approved = (
        rate[rate["outcome"] == "approved"]
        .groupby(g, observed=True)
        .agg(
            median_days_to_approval=("days_to_approval", "median"),
            mean_days_to_approval=("days_to_approval", "mean"),
            mean_requested_pct=("requested_pct", "mean"),
            mean_approved_pct=("approved_pct", "mean"),
            haircut_share=("haircut", "mean"),
        )
    )
    out = counts.join(outcomes, how="left").join(approved, how="left").reset_index()
    out["strict_rejection_rate"] = out["disapproved"] / out["dispositioned"]
    out["broad_rejection_rate"] = (out["disapproved"] + out["withdrawn"]) / out["dispositioned"]
    return out


def drivers_table() -> pd.DataFrame:
    """State-year disasters, housing and macro drivers for all 51 jurisdictions."""
    d = INTERIM_DATA_DIR
    grid = pd.MultiIndex.from_product(
        [list(STATES), range(DRIVER_START_YEAR, pd.Timestamp.today().year + 1)],
        names=["state", "year"],
    ).to_frame(index=False)
    storms = pd.read_parquet(d / "storms_state_year.parquet")
    fema = pd.read_parquet(d / "fema_state_year.parquet")
    hpi = pd.read_parquet(d / "hpi_state_year.parquet")
    macro_state = pd.read_parquet(d / "macro_state.parquet")
    national = pd.read_parquet(d / "macro_national.parquet")
    out = (
        grid.merge(storms, on=["state", "year"], how="left")
        .merge(fema, on=["state", "year"], how="left")
        .merge(hpi, on=["state", "year"], how="left")
        .merge(macro_state, on=["state", "year"], how="left")
        .merge(national, on="year", how="left")
    )
    dmg = [c for c in out if c.startswith(("storm_damage_", "fema_"))]
    out[dmg] = out[dmg].fillna(0)
    # Population for the latest year(s) not yet published: carry the last value forward.
    out["population"] = out.groupby("state")["population"].ffill()
    out["homeownership"] = out.groupby("state")["homeownership"].ffill()
    out["damage_pc"] = out["storm_damage_total"] / out["population"]
    out["damage_pc_hurricane"] = out.get("storm_damage_hurricane", 0) / out["population"]
    out["damage_pc_wildfire"] = out.get("storm_damage_wildfire", 0) / out["population"]
    out["fema_assistance_pc"] = out["fema_assistance"] / out["population"]
    return out


def state_year_panel(
    drivers: pd.DataFrame, regimes: pd.DataFrame, filings: pd.DataFrame
) -> pd.DataFrame:
    fio = pd.read_parquet(INTERIM_DATA_DIR / "fio_state_year.parquet")
    panel = drivers.merge(
        regimes[["state", "state_name", "regime", "regime_name", "regime_3way"]], on="state"
    ).merge(fio, on=["state", "year"], how="left")
    panel = panel.sort_values(["state", "year"])
    panel["fio_premium_growth"] = panel.groupby("state")["fio_premium"].pct_change() * 100
    rate = filings[filings["is_rate"].fillna(False)]
    disp = rate[rate["dispositioned"]]
    by_state = (
        rate.groupby(["state", "year"])
        .agg(
            rate_filings=("filing_id", "nunique"),
            median_days_to_approval=("days_to_approval", "median"),
            mean_requested_pct=("requested_pct", "mean"),
            mean_approved_pct=("approved_pct", "mean"),
        )
        .join(
            disp.groupby(["state", "year"]).agg(
                broad_rejection_rate=("is_rejected_broad", "mean"),
                strict_rejection_rate=("is_disapproved", "mean"),
            )
        )
        .reset_index()
    )
    panel = panel.merge(by_state, on=["state", "year"], how="left")
    gao = pd.read_csv(EXTERNAL_DATA_DIR / "gao_approval_days.csv")[
        ["state", "gao_bin", "gao_median_days"]
    ]
    panel = panel.merge(gao, on="state", how="left")
    panel["period"] = period_label(panel["year"])
    return panel


@app.command()
def main():
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    regimes = pd.read_csv(EXTERNAL_DATA_DIR / "state_regimes.csv")
    drivers = drivers_table()
    filings = enrich_filings(
        pd.read_parquet(INTERIM_DATA_DIR / "filings.parquet"), regimes, drivers
    )
    filings.to_parquet(PROCESSED_DATA_DIR / "filings.parquet", index=False)
    company_state_year(filings).to_parquet(
        PROCESSED_DATA_DIR / "company_state_year.parquet", index=False
    )
    panel = state_year_panel(drivers, regimes, filings)
    panel.to_parquet(PROCESSED_DATA_DIR / "state_year.parquet", index=False)
    regimes.to_parquet(PROCESSED_DATA_DIR / "state_regimes.parquet", index=False)
    logger.success(
        f"features: {len(filings):,} filings, {filings['top10'].sum():,} top-10; panel {panel.shape}"
    )


if __name__ == "__main__":
    app()
