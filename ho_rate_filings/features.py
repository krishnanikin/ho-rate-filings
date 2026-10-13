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
from ho_rate_filings.reference import news as news_ref

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


# Explanations for reports whose figure legitimately differs from the filing record.
NEWS_NOTES = {
    "State Farm rental-dwelling emergency": (
        "News reported the 38% interim emergency rate (May 2025); the filing closed in Aug "
        "2026 at 32.8% after the full rate hearing."
    ),
}
MATCH_WINDOW_DAYS = 456  # ~15 months between a news report and the filing's decision
EXACT_PTS, CLOSE_PTS = 0.15, 1.0


def news_crosscheck(filings: pd.DataFrame, news: pd.DataFrame) -> pd.DataFrame:
    """Match each news-reported rate change to the closest filing in the regulator data."""
    rows = []
    approved = filings[filings["approved_pct"].notna()].copy()
    approved["decision_date"] = approved["closed_date"].fillna(approved["received_date"])
    for _, n in news.iterrows():
        when = pd.Timestamp(n["news_date"])
        cand = approved[
            (approved["state"] == n["state"])
            & approved["company"].str.upper().str.contains(n["company_pattern"], regex=False)
        ].copy()
        # Interim approvals can precede the filing's formal close by months, so measure the
        # gap from whichever filing date (received or closed) is nearer the report.
        gap = pd.concat(
            [(cand["received_date"] - when).abs(), (cand["closed_date"] - when).abs()], axis=1
        ).min(axis=1)
        cand = cand[gap.dt.days <= MATCH_WINDOW_DAYS]
        rec = n.to_dict()
        if cand.empty:
            rec["match_status"] = "No filing found"
            rows.append(rec)
            continue
        cand["diff"] = (cand["approved_pct"] - n["news_approved_pct"]).abs()
        cand["gap_days"] = gap[cand.index].dt.days
        best = cand.sort_values(["diff", "gap_days"]).iloc[0]
        rec.update(
            {
                "filing_id": best["filing_id"],
                "filing_company": best["company"],
                "filing_received": best["received_date"],
                "filing_closed": best["closed_date"],
                "filing_requested_pct": best["requested_pct"],
                "filing_approved_pct": best["approved_pct"],
                "diff_pts": best["approved_pct"] - n["news_approved_pct"],
                "match_status": "Exact match"
                if best["diff"] <= EXACT_PTS
                else "Within 1 point"
                if best["diff"] <= CLOSE_PTS
                else "Different value",
                "note": next(
                    (v for k, v in NEWS_NOTES.items() if n["headline"].startswith(k)), ""
                ),
            }
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def pullback_context(filings: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Each top-10 pullback in a filing state: the group's rate filings 2 years before vs after."""
    rows = []
    rate = filings[filings["is_rate"].fillna(False)].copy()
    rate["decision_date"] = rate["closed_date"].fillna(rate["received_date"])
    for _, a in actions[
        actions["top10"] & actions["state"].isin(rate["state"].unique())
    ].iterrows():
        t0 = pd.Timestamp(a["start"])
        g = rate[(rate["state"] == a["state"]) & (rate["group"].astype(str) == a["group"])]
        before = g[g["decision_date"].between(t0 - pd.DateOffset(years=2), t0)]
        after = g[g["decision_date"].between(t0, t0 + pd.DateOffset(years=2))]
        rows.append(
            {
                **a[["state", "group", "company", "action", "start"]].to_dict(),
                "filings_2y_before": len(before),
                "filings_2y_after": len(after),
                "mean_approved_pct_before": before["approved_pct"].mean(),
                "mean_approved_pct_after": after["approved_pct"].mean(),
                "max_approved_pct_after": after["approved_pct"].max(),
            }
        )
    return pd.DataFrame(rows)


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
    cross = news_crosscheck(filings, news_ref.news_rate_reports())
    cross.to_parquet(PROCESSED_DATA_DIR / "news_crosscheck.parquet", index=False)
    pullback_context(filings, news_ref.market_actions()).to_parquet(
        PROCESSED_DATA_DIR / "pullback_context.parquet", index=False
    )
    logger.info(f"news cross-check: {cross['match_status'].value_counts().to_dict()}")
    logger.success(
        f"features: {len(filings):,} filings, {filings['top10'].sum():,} top-10; panel {panel.shape}"
    )


if __name__ == "__main__":
    app()
