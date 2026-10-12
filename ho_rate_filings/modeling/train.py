"""Fit the project's statistical models and write results to models/.

1. Pre- vs post-COVID comparison (2016-19 vs 2020+) of rate filings in CA, FL and TX:
   frequency, size of rate changes, rejection/withdrawal rates and days to approval, with
   Welch t-tests (means) and Mann-Whitney tests (approval days).
2. Rate changes vs disasters, construction costs and house prices (filing level, CA + TX,
   where % changes are published): OLS of the approved % change on lagged storm damage per
   resident, lagged FHFA house-price growth and lagged construction input-price growth,
   with a post-2020 interaction, state and insurer-group fixed effects; SEs clustered by
   state-year.
3. Approval time (filing level, CA + FL): OLS of log days to approval on the same drivers.
4. All-states panel (FIO ZIP data aggregated to state-year, 2018-2022): premium growth,
   loss ratio and non-renewal rate on storm damage per resident, house-price growth and
   the state's regime; year fixed effects; SEs clustered by state. Ecological, not causal.
5. Event studies around large catastrophes: top-10 rate filings and mean requested change
   in the 8 quarters before vs after.
6. Structural break at 2020: does the trend in approved rate changes shift (CA, TX)?

    python -m ho_rate_filings.modeling.train
"""

import json

from loguru import logger
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.formula.api as smf
import typer

from ho_rate_filings.config import COVID_BREAK, MODELS_DIR, PROCESSED_DATA_DIR

app = typer.Typer()

# Large catastrophes in the filing states (state, event, date).
EVENTS = [
    ("TX", "Hurricane Harvey", "2017-08-25"),
    ("FL", "Hurricane Irma", "2017-09-10"),
    ("FL", "Hurricane Michael", "2018-10-10"),
    ("CA", "Camp & Woolsey fires", "2018-11-08"),
    ("CA", "2020 wildfire season", "2020-08-15"),
    ("TX", "Winter Storm Uri", "2021-02-13"),
    ("FL", "Hurricane Ian", "2022-09-28"),
    ("TX", "Hurricane Beryl", "2024-07-08"),
    ("FL", "Hurricanes Helene & Milton", "2024-09-26"),
    ("CA", "Los Angeles fires", "2025-01-07"),
]

DRIVERS = {
    "damage_pc_l1": "Storm damage per resident, prior year ($100s)",
    "damage_pc_l2": "Storm damage per resident, two years prior ($100s)",
    "hpi_growth_l1": "House-price growth, prior year (%)",
    "ppi_res_construction_growth_l1": "Construction input-price growth, prior year (%)",
    "post_covid": "Post-COVID (2020+)",
    "damage_pc_l1:post_covid": "Storm damage x post-COVID",
}


def _coef_table(fit, model: str, sample: str, labels: dict[str, str]) -> list[dict]:
    rows = []
    ci = fit.conf_int()
    for term, label in labels.items():
        if term not in fit.params:
            continue
        rows.append(
            {
                "model": model,
                "sample": sample,
                "term": term,
                "label": label,
                "coef": fit.params[term],
                "ci_low": ci.loc[term, 0],
                "ci_high": ci.loc[term, 1],
                "p_value": fit.pvalues[term],
                "n": int(fit.nobs),
                "r2": getattr(fit, "rsquared", np.nan),
            }
        )
    return rows


def period_comparison(filings: pd.DataFrame) -> pd.DataFrame:
    rate = filings[filings["is_rate"].fillna(False)]
    rows = []
    for (state, top10), g in rate.groupby(["state", "top10"]):
        pre, post = g[g["post_covid"] == 0], g[g["post_covid"] == 1]
        years = {0: pre["year"].nunique(), 1: post["year"].nunique()}
        rec = {"state": state, "insurers": "Top 10" if top10 else "All other"}
        for name, sub, flag in (("pre", pre, 0), ("post", post, 1)):
            disp = sub[sub["dispositioned"]]
            rec[f"{name}_filings_per_year"] = len(sub) / max(years[flag], 1)
            rec[f"{name}_mean_requested_pct"] = sub["requested_pct"].mean()
            rec[f"{name}_mean_approved_pct"] = sub["approved_pct"].mean()
            rec[f"{name}_broad_rejection_rate"] = disp["is_rejected_broad"].mean()
            rec[f"{name}_median_days_to_approval"] = sub["days_to_approval"].median()
        a, b = pre["approved_pct"].dropna(), post["approved_pct"].dropna()
        rec["approved_pct_ttest_p"] = (
            stats.ttest_ind(a, b, equal_var=False).pvalue if len(a) > 2 and len(b) > 2 else np.nan
        )
        a, b = pre["days_to_approval"].dropna(), post["days_to_approval"].dropna()
        rec["days_mannwhitney_p"] = (
            stats.mannwhitneyu(a, b).pvalue if len(a) > 2 and len(b) > 2 else np.nan
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def _per_100(df: pd.DataFrame) -> pd.DataFrame:
    """Express lagged storm damage per resident in $100s so coefficients read easily."""
    return df.assign(damage_pc_l1=df["damage_pc_l1"] / 100, damage_pc_l2=df["damage_pc_l2"] / 100)


def rate_change_models(filings: pd.DataFrame) -> list[dict]:
    """Approved % change on lagged disaster/housing/cost drivers (CA + TX)."""
    rows = []
    base = filings[
        filings["is_rate"].fillna(False)
        & (filings["outcome"] == "approved")
        & filings["approved_pct"].notna()
        & filings["state"].isin(["CA", "TX"])
    ].pipe(_per_100)
    base["cluster"] = base["state"] + base["year"].astype(str)
    rhs = (
        "damage_pc_l1 + damage_pc_l2 + hpi_growth_l1 + ppi_res_construction_growth_l1"
        " + post_covid + damage_pc_l1:post_covid + C(state) + C(group)"
    )
    for sample, df in {
        "CA + TX, all insurers": base,
        "CA + TX, top-10 groups": base[base["top10"]],
    }.items():
        df = df.dropna(subset=["damage_pc_l1", "damage_pc_l2", "hpi_growth_l1"])
        df = df.assign(group=df["group"].astype(str))
        fit = smf.ols(f"approved_pct ~ {rhs}", data=df).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(df["cluster"])[0]}
        )
        rows += _coef_table(fit, "Approved rate change (%)", sample, DRIVERS)
    return rows


def approval_time_models(filings: pd.DataFrame) -> list[dict]:
    rows = []
    df = filings[filings["days_to_approval"].gt(0) & filings["state"].isin(["CA", "FL"])].pipe(
        _per_100
    )
    df = df.dropna(subset=["damage_pc_l1", "hpi_growth_l1"])
    df["log_days"] = np.log(df["days_to_approval"])
    df["group"] = df["group"].astype(str)
    df["cluster"] = df["state"] + df["year"].astype(str)
    labels = {k: v for k, v in DRIVERS.items() if k != "damage_pc_l2"}
    fit = smf.ols(
        "log_days ~ damage_pc_l1 + hpi_growth_l1 + ppi_res_construction_growth_l1 + post_covid"
        " + damage_pc_l1:post_covid + C(state) + C(group)",
        data=df,
    ).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df["cluster"])[0]})
    rows += _coef_table(fit, "Log days to approval", "CA + FL, all insurers", labels)
    return rows


def national_panel_models(panel: pd.DataFrame) -> list[dict]:
    """FIO state-year outcomes on disasters, housing and regime (all 51 jurisdictions)."""
    rows = []
    df = panel[panel["fio_premium"].notna()].copy()
    df["damage_pc_k"] = df["damage_pc"] / 1000  # $ thousands per resident
    df = df.sort_values(["state", "year"])
    df["damage_pc_k_l1"] = df.groupby("state")["damage_pc_k"].shift(1)
    # 2018 has no FIO lag inside the panel; take it from the full driver table.
    lag = panel[["state", "year", "damage_pc"]].assign(year=lambda x: x["year"] + 1)
    df = df.drop(columns="damage_pc_k_l1").merge(
        lag.rename(columns={"damage_pc": "damage_pc_prev"}), on=["state", "year"], how="left"
    )
    df["damage_pc_k_l1"] = df["damage_pc_prev"] / 1000
    df["regime_3way"] = pd.Categorical(df["regime_3way"], ["FU", "PA", "UF"])
    labels = {
        "damage_pc_k": "Storm damage per resident, same year ($000)",
        "damage_pc_k_l1": "Storm damage per resident, prior year ($000)",
        "hpi_growth": "House-price growth (%)",
        "C(regime_3way)[T.PA]": "Prior approval (vs file & use)",
        "C(regime_3way)[T.UF]": "Use & file (vs file & use)",
    }
    specs = {
        "Premium growth (%)": ("fio_premium_growth", "damage_pc_k_l1 + hpi_growth"),
        "Loss ratio": ("fio_loss_ratio", "damage_pc_k"),
        "Non-renewal rate (%)": ("nonrenewal_pct", "damage_pc_k_l1 + hpi_growth"),
    }
    df["nonrenewal_pct"] = df["fio_nonrenewal"] * 100
    for model, (y, x) in specs.items():
        d = df.dropna(subset=[y, "hpi_growth", "damage_pc_k", "damage_pc_k_l1"])
        fit = smf.ols(f"{y} ~ {x} + C(regime_3way) + C(year)", data=d).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(d["state"])[0]}
        )
        rows += _coef_table(fit, model, "51 jurisdictions, 2018-2022 (FIO)", labels)
    return rows


def event_studies(filings: pd.DataFrame) -> pd.DataFrame:
    """Top-10 rate filings around each event: quarterly counts and mean requested change."""
    rate = filings[filings["is_rate"].fillna(False) & filings["received_date"].notna()]
    rows = []
    for state, name, when in EVENTS:
        t0 = pd.Timestamp(when)
        g = rate[rate["state"] == state].copy()
        g["q"] = ((g["received_date"] - t0).dt.days // 91).astype(int)
        g = g[g["q"].between(-8, 8)]
        for q, sub in g.groupby("q"):
            top = sub[sub["top10"]]
            rows.append(
                {
                    "state": state,
                    "event": name,
                    "event_date": when,
                    "quarter": q,
                    "filings_all": len(sub),
                    "filings_top10": len(top),
                    "mean_requested_pct_all": sub["requested_pct"].mean(),
                    "mean_requested_pct_top10": top["requested_pct"].mean(),
                }
            )
    return pd.DataFrame(rows)


def event_summary(es: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (state, name), g in es.groupby(["state", "event"]):
        pre, post = g[g["quarter"] < 0], g[g["quarter"] >= 0]
        # Only events with a full 8 quarters on both sides are compared.
        complete = pre["quarter"].nunique() >= 6 and post["quarter"].nunique() >= 6
        rows.append(
            {
                "state": state,
                "event": name,
                "event_date": g["event_date"].iloc[0],
                "complete_window": complete,
                "filings_per_q_before": pre["filings_all"].sum() / 8,
                "filings_per_q_after": post["filings_all"].sum()
                / max(post["quarter"].nunique(), 1),
                "requested_pct_before": np.average(
                    pre["mean_requested_pct_all"].fillna(0), weights=pre["filings_all"]
                )
                if pre["mean_requested_pct_all"].notna().any()
                else np.nan,
                "requested_pct_after": np.average(
                    post["mean_requested_pct_all"].fillna(0), weights=post["filings_all"]
                )
                if post["mean_requested_pct_all"].notna().any()
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def structural_break(filings: pd.DataFrame) -> pd.DataFrame:
    """Chow-type test: approved % on a time trend with a level and slope shift at 2020."""
    rows = []
    df = filings[
        filings["is_rate"].fillna(False)
        & (filings["outcome"] == "approved")
        & filings["approved_pct"].notna()
    ].copy()
    df["t"] = df["year"] - COVID_BREAK
    for state, g in df.groupby("state"):
        if len(g) < 30:
            continue
        restricted = smf.ols("approved_pct ~ t", data=g).fit()
        full = smf.ols("approved_pct ~ t + post_covid + t:post_covid", data=g).fit()
        f_stat, p_value, _ = full.compare_f_test(restricted)
        rows.append(
            {
                "state": state,
                "n": int(full.nobs),
                "pre_trend_pts_per_year": full.params["t"],
                "level_shift_2020": full.params["post_covid"],
                "slope_shift_2020": full.params["t:post_covid"],
                "chow_F": f_stat,
                "chow_p": p_value,
            }
        )
    return pd.DataFrame(rows)


@app.command()
def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    filings = pd.read_parquet(PROCESSED_DATA_DIR / "filings.parquet")
    panel = pd.read_parquet(PROCESSED_DATA_DIR / "state_year.parquet")

    period = period_comparison(filings)
    period.to_csv(MODELS_DIR / "period_comparison.csv", index=False)

    coefs = rate_change_models(filings) + approval_time_models(filings)
    coefs += national_panel_models(panel)
    coefs = pd.DataFrame(coefs)
    coefs.to_csv(MODELS_DIR / "driver_models.csv", index=False)

    es = event_studies(filings)
    es.to_csv(MODELS_DIR / "event_study.csv", index=False)
    event_summary(es).to_csv(MODELS_DIR / "event_summary.csv", index=False)

    brk = structural_break(filings)
    brk.to_csv(MODELS_DIR / "structural_break.csv", index=False)

    summary = {
        "n_filings": len(filings),
        "n_top10": int(filings["top10"].sum()),
        "states": sorted(filings["state"].unique().tolist()),
        "significant_driver_terms": coefs.loc[coefs["p_value"] < 0.05, ["model", "label"]]
        .astype(str)
        .agg(" | ".join, axis=1)
        .tolist(),
    }
    (MODELS_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    logger.success(f"models written to {MODELS_DIR}")


if __name__ == "__main__":
    app()
