"""Homeowners Rate Filings dashboard.

    streamlit run dashboard/app.py

Reads the tables produced by `make pipeline` (data/processed, data/external, models/).
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ho_rate_filings.config import (
    COVID_BREAK,
    EXTERNAL_DATA_DIR,
    MODELS_DIR,
    PROCESSED_DATA_DIR,
    START_YEAR,
)
from ho_rate_filings.features import GROUP_ORDER
from ho_rate_filings.reference.states import REGIMES

st.set_page_config(page_title="Homeowners Rate Filings", page_icon="🏠", layout="wide")

# ---------------------------------------------------------------------------
# Visual system: validated categorical slots; regimes take the first three (the slots that
# validate all-pairs for maps and scatters). One sequential hue for magnitude.
# ---------------------------------------------------------------------------
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
REGIME_COLORS = {
    "Prior Approval": SLOTS[0],
    "File and Use": SLOTS[1],
    "Use and File": SLOTS[2],
    "Other": "#898781",
}
PERIOD_COLORS = {
    f"Pre-COVID ({START_YEAR}-{COVID_BREAK - 1})": "#86b6ef",
    f"Post-COVID ({COVID_BREAK}+)": "#1c5cab",
}
BLUE_SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
MUTED, GRID = "#898781", "rgba(137,135,129,0.25)"
TOP10 = [g for g in GROUP_ORDER if g != "Other"]


def style(fig: go.Figure, height: int = 380, y_title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 40, "b": 24},
        font={"family": "system-ui, -apple-system, Segoe UI, sans-serif", "size": 13},
        legend={"orientation": "h", "yanchor": "top", "y": -0.12, "x": 0, "title": None},
        hoverlabel={"font_size": 12},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=MUTED, title=None)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=y_title)
    fig.update_traces(
        selector={"type": "scatter", "mode": "lines+markers"},
        line={"width": 2},
        marker={"size": 8},
    )
    return fig


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _data_version() -> float:
    """Latest modification time of the pipeline outputs, so the cache refreshes after a rerun."""
    files = [*PROCESSED_DATA_DIR.glob("*.parquet"), *MODELS_DIR.glob("*.csv")]
    return max((f.stat().st_mtime for f in files), default=0.0)


@st.cache_data
def load(version: float) -> dict[str, pd.DataFrame]:
    p = PROCESSED_DATA_DIR
    data = {
        "filings": pd.read_parquet(p / "filings.parquet"),
        "csy": pd.read_parquet(p / "company_state_year.parquet"),
        "panel": pd.read_parquet(p / "state_year.parquet"),
        "regimes": pd.read_csv(EXTERNAL_DATA_DIR / "state_regimes.csv"),
        "gao": pd.read_csv(EXTERNAL_DATA_DIR / "gao_approval_days.csv"),
    }
    for name in [
        "period_comparison",
        "driver_models",
        "event_study",
        "event_summary",
        "structural_break",
    ]:
        path = MODELS_DIR / f"{name}.csv"
        data[name] = pd.read_csv(path) if path.exists() else pd.DataFrame()
    data["filings"]["group"] = data["filings"]["group"].astype(str)
    return data


try:
    D = load(_data_version())
except FileNotFoundError as err:
    st.error(f"Missing data ({err.filename}). Run `make pipeline` first.")
    st.stop()

filings, panel, regimes = D["filings"], D["panel"], D["regimes"]
max_year = int(filings["year"].max())

# ---------------------------------------------------------------------------
# Header and filters (one row, above everything)
# ---------------------------------------------------------------------------
st.title("Homeowners rate filings, 2016–present")
st.caption(
    "Rate filings by the 10 largest homeowners insurance groups, how each state regulates them, "
    "and how filings relate to disasters and the housing market. Filing-level data come from "
    "regulators that publish them for public use (California, Florida, Texas); state-level "
    "indicators cover all 50 states and DC."
)

c1, c2, c3 = st.columns([2, 3, 2])
years = c1.slider("Filing years", START_YEAR, max_year, (START_YEAR, max_year))
companies = c2.multiselect("Insurance groups", TOP10, default=TOP10)
include_other = c3.toggle("Compare with all other insurers", value=True)

f = filings[filings["year"].between(*years)]
f_top = f[f["group"].isin(companies)]
rate_top = f_top[f_top["is_rate"].fillna(False)]


def pct(x: float) -> str:
    return "–" if pd.isna(x) else f"{x:.1%}"


def num(x: float, fmt: str = "{:,.0f}") -> str:
    return "–" if pd.isna(x) else fmt.format(x)


tabs = st.tabs(
    [
        "Overview",
        "States & regimes",
        "Company comparison",
        "Pre vs post COVID",
        "Disasters & housing",
        "Data & methods",
    ]
)

# ---------------------------------------------------------------------------
# 1. Overview
# ---------------------------------------------------------------------------
with tabs[0]:
    disp = rate_top[rate_top["dispositioned"]]
    k = st.columns(5)
    k[0].metric(
        "Top-10 rate filings", num(len(rate_top)), help="CA, FL and TX, selected years and groups"
    )
    k[1].metric(
        "Median days to approval",
        num(rate_top["days_to_approval"].median()),
        help="CA and FL (TX does not publish closing dates)",
    )
    k[2].metric(
        "Disapproved",
        pct(disp["is_disapproved"].mean()),
        help="Strict rejection: disapproved / dispositioned",
    )
    k[3].metric(
        "Disapproved or withdrawn",
        pct(disp["is_rejected_broad"].mean()),
        help="Broad rejection: withdrawals are often negotiated rejections",
    )
    k[4].metric(
        "Mean approved change",
        num(rate_top["approved_pct"].mean(), "{:+.1f}%"),
        help="CA and TX (FL does not publish % changes in search results)",
    )

    left, right = st.columns([3, 2])
    with left:
        st.subheader("How each state regulates homeowners rates")
        m = regimes.copy()
        fig = px.choropleth(
            m,
            locations="state",
            locationmode="USA-states",
            scope="usa",
            color="regime_name",
            color_discrete_map=REGIME_COLORS,
            category_orders={"regime_name": list(REGIME_COLORS)},
            hover_name="state_name",
            hover_data={"state": False, "raw_regime": True, "notes": True, "regime_name": False},
        )
        fig.update_traces(marker_line_color="white", marker_line_width=1)
        fig.update_layout(geo={"bgcolor": "rgba(0,0,0,0)", "lakecolor": "rgba(0,0,0,0)"})
        st.plotly_chart(style(fig, 420), use_container_width=True)
    with right:
        st.subheader("Regimes")
        counts = regimes["regime_name"].value_counts()
        for name, desc in REGIMES.values():
            st.markdown(f"**{name}** — {counts.get(name, 0)} jurisdictions  \n{desc}")
        st.caption(
            "Source: Federal Insurance Office (Jan 2025), App. A.4, from the NAIC chart "
            "*Rate Filing Methods for P/C Insurance* (2022). 'Other' = Wyoming (open rating) "
            "and Alaska (flex band). Definitions: Guidewire, *US rate filings 101*."
        )

    st.subheader("Average approved rate change by year (filing states)")
    yearly = (
        f[f["is_rate"].fillna(False) & f["approved_pct"].notna()]
        .assign(
            insurers=lambda d: np.where(
                d["group"].isin(companies), "Top-10 groups", "All other insurers"
            )
        )
        .groupby(["state", "year", "insurers"], as_index=False)["approved_pct"]
        .mean()
    )
    if not include_other:
        yearly = yearly[yearly["insurers"] == "Top-10 groups"]
    fig = px.line(
        yearly,
        x="year",
        y="approved_pct",
        color="state",
        line_dash="insurers",
        markers=True,
        color_discrete_map={"CA": SLOTS[0], "TX": SLOTS[1]},
        labels={"approved_pct": "Approved change (%)", "state": "State"},
    )
    fig.add_vline(x=COVID_BREAK - 0.5, line_dash="dot", line_color=MUTED)
    fig.add_annotation(
        x=COVID_BREAK - 0.5,
        y=1,
        yref="paper",
        text="COVID",
        showarrow=False,
        font={"color": MUTED},
    )
    st.plotly_chart(style(fig, 360, "Mean approved change (%)"), use_container_width=True)
    st.caption(
        "California is prior approval; Texas is file and use. Florida does not publish % changes in its search results."
    )

# ---------------------------------------------------------------------------
# 2. States & regimes
# ---------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Approval times by state")
    gao = D["gao"].merge(regimes[["state", "state_name", "regime_name"]], on="state")
    ours = (
        f[f["days_to_approval"].notna()]
        .groupby("state")["days_to_approval"]
        .median()
        .rename("our_median_days")
        .reset_index()
    )
    gao = gao.merge(ours, on="state", how="left")
    bins = ["<=100", "101-200", ">300", "n/a (no review)"]
    fig = px.choropleth(
        gao,
        locations="state",
        locationmode="USA-states",
        scope="usa",
        color="gao_bin",
        category_orders={"gao_bin": bins},
        color_discrete_map={
            "<=100": BLUE_SEQ[1],
            "101-200": BLUE_SEQ[3],
            ">300": BLUE_SEQ[6],
            "n/a (no review)": "#e6e5e1",
        },
        hover_name="state_name",
        hover_data={
            "state": False,
            "regime_name": True,
            "gao_median_days": True,
            "our_median_days": True,
        },
        labels={
            "gao_bin": "Median days, 2020–24 (GAO)",
            "our_median_days": "Median days (this project)",
        },
    )
    fig.update_traces(marker_line_color="white", marker_line_width=1)
    fig.update_layout(geo={"bgcolor": "rgba(0,0,0,0)"})
    st.plotly_chart(style(fig, 420), use_container_width=True)
    st.caption(
        "GAO-26-107867 (Feb 2026), fig. 4: median days from submission to approval, 2020–2024, "
        "from NAIC data. GAO gives exact values only for Colorado (331) and California (305). "
        "Hover for this project's own medians in California and Florida."
    )

    st.subheader("State detail")
    pick = st.selectbox(
        "State",
        ["CA", "FL", "TX"],
        format_func=lambda s: regimes.set_index("state").loc[s, "state_name"],
    )
    r = regimes.set_index("state").loc[pick]
    st.markdown(f"**{r['state_name']}** — {r['regime_name']} ({r['raw_regime']}). {r['notes']}")
    s = f[(f["state"] == pick) & f["is_rate"].fillna(False)]
    tl = (
        s.groupby([s["received_date"].dt.to_period("Q").dt.start_time, "outcome"])
        .size()
        .reset_index(name="filings")
    )
    tl.columns = ["quarter", "outcome", "filings"]
    fig = px.bar(
        tl,
        x="quarter",
        y="filings",
        color="outcome",
        color_discrete_map={
            "approved": SLOTS[0],
            "withdrawn": SLOTS[3],
            "disapproved": SLOTS[7],
            "other": "#c3c2b7",
            "open": "#e6e5e1",
        },
        category_orders={"outcome": ["approved", "withdrawn", "disapproved", "other", "open"]},
    )
    fig.update_traces(marker_line_color="white", marker_line_width=1)
    st.plotly_chart(
        style(fig, 320, "Rate filings received (all insurers)"), use_container_width=True
    )
    if pick == "CA" and s["received_date"].isna().mean() > 0.2:
        st.caption(
            "California received dates come from WARFF public notices; filings without a notice are not shown in this timeline."
        )

    tbl = (
        s[s["group"].isin(companies)]
        .groupby("group")
        .agg(
            rate_filings=("filing_id", "nunique"),
            disapproved=("is_disapproved", "sum"),
            withdrawn=("is_withdrawn", "sum"),
            median_days=("days_to_approval", "median"),
            mean_requested=("requested_pct", "mean"),
            mean_approved=("approved_pct", "mean"),
            haircut_share=("haircut", "mean"),
        )
        .reindex(companies)
        .dropna(how="all")
    )
    st.dataframe(
        tbl,
        use_container_width=True,
        column_config={
            "rate_filings": "Rate filings",
            "disapproved": "Disapproved",
            "withdrawn": "Withdrawn",
            "median_days": st.column_config.NumberColumn("Median days to approval", format="%.0f"),
            "mean_requested": st.column_config.NumberColumn("Mean requested %", format="%.1f"),
            "mean_approved": st.column_config.NumberColumn("Mean approved %", format="%.1f"),
            "haircut_share": st.column_config.NumberColumn(
                "Approved below request", format="percent"
            ),
        },
    )

# ---------------------------------------------------------------------------
# 3. Company comparison
# ---------------------------------------------------------------------------
with tabs[2]:
    disp = rate_top[rate_top["dispositioned"]]
    metric = st.radio(
        "Measure",
        [
            "Broad rejection rate",
            "Strict rejection rate",
            "Median days to approval",
            "Mean approved change (%)",
        ],
        horizontal=True,
    )
    if metric == "Broad rejection rate":
        grid = disp.groupby(["group", "state"])["is_rejected_broad"].mean()
        fmt = ".0%"
    elif metric == "Strict rejection rate":
        grid = disp.groupby(["group", "state"])["is_disapproved"].mean()
        fmt = ".1%"
    elif metric == "Median days to approval":
        grid = rate_top.groupby(["group", "state"])["days_to_approval"].median()
        fmt = ".0f"
    else:
        grid = rate_top.groupby(["group", "state"])["approved_pct"].mean()
        fmt = ".1f"
    n = disp.groupby(["group", "state"]).size()
    hm = grid.unstack("state").reindex(
        [c for c in companies if c in grid.index.get_level_values(0)]
    )
    nn = n.unstack("state").reindex(hm.index).reindex(columns=hm.columns)
    fig = go.Figure(
        go.Heatmap(
            z=hm.values,
            x=hm.columns,
            y=hm.index,
            colorscale=[[i / (len(BLUE_SEQ) - 1), c] for i, c in enumerate(BLUE_SEQ)],
            text=hm.map(lambda v: "" if pd.isna(v) else format(v, fmt)).values,
            texttemplate="%{text}",
            customdata=nn.values,
            hovertemplate="%{y} · %{x}<br>%{text}<br>n=%{customdata} dispositioned<extra></extra>",
            xgap=2,
            ygap=2,
            colorbar={"title": None},
        )
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(style(fig, 440), use_container_width=True)
    st.caption(
        "Broad rejection = disapproved + withdrawn, over dispositioned rate filings. Days to approval: "
        "CA (public notice to approval) and FL (filed to closed). Approved change: CA and TX. Blank = "
        "not published or no filings. Erie writes no homeowners business in these three states."
    )

    st.subheader("Requested vs approved change (California)")
    ca = rate_top[
        (rate_top["state"] == "CA")
        & rate_top["requested_pct"].notna()
        & rate_top["approved_pct"].notna()
    ]
    fig = px.scatter(
        ca,
        x="requested_pct",
        y="approved_pct",
        hover_name="company",
        hover_data={"group": True, "year": True, "filing_id": True},
        labels={"requested_pct": "Requested (%)", "approved_pct": "Approved (%)"},
    )
    fig.update_traces(
        marker={
            "size": 9,
            "color": SLOTS[0],
            "opacity": 0.7,
            "line": {"color": "white", "width": 2},
        }
    )
    lim = (
        [
            min(ca["requested_pct"].min(), ca["approved_pct"].min(), 0),
            max(ca["requested_pct"].max(), 1),
        ]
        if len(ca)
        else [0, 1]
    )
    fig.add_trace(
        go.Scatter(
            x=lim,
            y=lim,
            mode="lines",
            line={"color": MUTED, "dash": "dot", "width": 1},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    st.plotly_chart(style(fig, 420, "Approved (%)"), use_container_width=True)
    st.caption(
        "Points below the dotted line were approved at less than requested (a 'haircut') — the typical outcome under California's prior approval."
    )

# ---------------------------------------------------------------------------
# 4. Pre vs post COVID
# ---------------------------------------------------------------------------
with tabs[3]:
    st.subheader(f"Before ({START_YEAR}–{COVID_BREAK - 1}) vs after ({COVID_BREAK}–{max_year})")
    pc = D["period_comparison"]
    if not pc.empty:
        if not include_other:
            pc = pc[pc["insurers"] == "Top 10"]
        long = []
        for _, r in pc.iterrows():
            for measure, key in [
                ("Rate filings per year", "filings_per_year"),
                ("Mean approved change (%)", "mean_approved_pct"),
                ("Broad rejection rate (%)", "broad_rejection_rate"),
                ("Median days to approval", "median_days_to_approval"),
            ]:
                for per, label in [
                    ("pre", next(iter(PERIOD_COLORS))),
                    ("post", list(PERIOD_COLORS)[1]),
                ]:
                    v = r[f"{per}_{key}"]
                    if key == "broad_rejection_rate" and pd.notna(v):
                        v *= 100
                    long.append(
                        {
                            "measure": measure,
                            "state": f"{r['state']}<br>{r['insurers']}",
                            "period": label,
                            "value": v,
                        }
                    )
        long = pd.DataFrame(long).dropna()
        cols = st.columns(2)
        for i, measure in enumerate(long["measure"].unique()):
            sub = long[long["measure"] == measure]
            fig = px.bar(
                sub,
                x="state",
                y="value",
                color="period",
                barmode="group",
                color_discrete_map=PERIOD_COLORS,
                title=measure,
            )
            fig.update_traces(marker_line_color="white", marker_line_width=2)
            fig = style(fig, 340)
            fig.update_xaxes(tickangle=0)
            fig.update_layout(legend={"y": -0.25})
            cols[i % 2].plotly_chart(fig, use_container_width=True)
        st.dataframe(
            pc[["state", "insurers", "approved_pct_ttest_p", "days_mannwhitney_p"]].rename(
                columns={
                    "approved_pct_ttest_p": "p: approved % (Welch t)",
                    "days_mannwhitney_p": "p: days (Mann-Whitney)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    brk = D["structural_break"]
    if not brk.empty:
        st.markdown(
            "**Structural break at 2020** (approved % on a time trend, level and slope allowed to shift in 2020)"
        )
        st.dataframe(brk.round(3), use_container_width=True, hide_index=True)
    st.caption(
        "Drivers that changed around 2020: construction input prices rose ~17% in both 2021 and 2022 "
        "(BLS PPI via FRED), house prices surged (FHFA), and reinsurance costs climbed from 2022."
    )
    macro = panel.drop_duplicates("year")[
        ["year", "ppi_res_construction_growth", "cpi_home_insurance_growth", "cpi_all_growth"]
    ]
    macro = macro[macro["year"].between(START_YEAR, max_year)].melt(
        "year", var_name="series", value_name="growth"
    )
    macro["series"] = macro["series"].map(
        {
            "ppi_res_construction_growth": "Construction inputs (PPI)",
            "cpi_home_insurance_growth": "Tenants' & household insurance (CPI)",
            "cpi_all_growth": "All items (CPI)",
        }
    )
    fig = px.line(
        macro,
        x="year",
        y="growth",
        color="series",
        markers=True,
        color_discrete_sequence=SLOTS[:3],
    )
    fig.add_vline(x=COVID_BREAK - 0.5, line_dash="dot", line_color=MUTED)
    st.plotly_chart(style(fig, 340, "Year-over-year change (%)"), use_container_width=True)

# ---------------------------------------------------------------------------
# 5. Disasters & housing
# ---------------------------------------------------------------------------
with tabs[4]:
    st.subheader("Is there a connection?")
    coefs = D["driver_models"]
    if not coefs.empty:
        show = coefs.copy()
        show["estimate"] = show.apply(
            lambda r: f"{r['coef']:+.3f} [{r['ci_low']:+.3f}, {r['ci_high']:+.3f}]", axis=1
        )
        show["significant (p<0.05)"] = np.where(show["p_value"] < 0.05, "yes", "no")
        st.dataframe(
            show[["model", "sample", "label", "estimate", "p_value", "significant (p<0.05)", "n"]],
            use_container_width=True,
            hide_index=True,
            column_config={"p_value": st.column_config.NumberColumn("p", format="%.3f")},
        )
        st.caption(
            "Filing-level OLS with state and insurer-group fixed effects, SEs clustered by state-year; "
            "panel models with year fixed effects, SEs clustered by state. Associations, not causal effects."
        )

    st.subheader("Disaster damage vs premium growth, all states (FIO, 2019–2022)")
    p = panel[panel["fio_premium_growth"].notna()].copy()
    prev = (
        panel[["state", "year", "damage_pc"]]
        .assign(year=lambda d: d["year"] + 1)
        .rename(columns={"damage_pc": "damage_prev"})
    )
    p = p.merge(prev, on=["state", "year"], how="left")
    p["regime"] = p["regime_3way"].map(
        {"PA": "Prior Approval", "FU": "File and Use", "UF": "Use and File"}
    )
    fig = px.scatter(
        p,
        x="damage_prev",
        y="fio_premium_growth",
        color="regime",
        color_discrete_map=REGIME_COLORS,
        category_orders={"regime": list(REGIME_COLORS)[:3]},
        hover_name="state_name",
        hover_data={"year": True, "regime": False},
        log_x=True,
        labels={
            "damage_prev": "Storm damage per resident, prior year ($, log)",
            "fio_premium_growth": "Median ZIP premium growth (%)",
            "regime": "Regime",
        },
    )
    fig.update_traces(marker={"size": 9, "line": {"color": "white", "width": 2}})
    st.plotly_chart(style(fig, 420, "Premium growth (%)"), use_container_width=True)

    st.subheader("Rate filings around major catastrophes")
    es = D["event_study"]
    if not es.empty:
        ev = st.selectbox("Event", es.drop_duplicates("event")["event"].tolist())
        e = es[es["event"] == ev]
        fig = go.Figure()
        fig.add_bar(
            x=e["quarter"],
            y=e["filings_all"],
            name="All rate filings",
            marker_color=BLUE_SEQ[2],
            marker_line_color="white",
            marker_line_width=2,
        )
        fig.add_bar(
            x=e["quarter"],
            y=e["filings_top10"],
            name="Top-10 groups",
            marker_color=BLUE_SEQ[5],
            marker_line_color="white",
            marker_line_width=2,
        )
        fig.add_vline(x=-0.5, line_dash="dot", line_color=MUTED)
        fig.update_layout(barmode="overlay")
        fig.update_xaxes(title="Quarters relative to event", dtick=1)
        st.plotly_chart(style(fig, 340, "Rate filings received"), use_container_width=True)
        st.dataframe(D["event_summary"].round(2), use_container_width=True, hide_index=True)

    st.subheader("House prices vs approved rate changes")
    hp = panel[panel["state"].isin(["CA", "TX"]) & panel["mean_approved_pct"].notna()][
        ["state", "year", "hpi_growth", "mean_approved_pct"]
    ]
    hp = hp.melt(["state", "year"], var_name="series", value_name="value")
    hp["series"] = hp["series"].map(
        {
            "hpi_growth": "House-price growth (FHFA)",
            "mean_approved_pct": "Mean approved rate change",
        }
    )
    fig = px.line(
        hp,
        x="year",
        y="value",
        color="series",
        facet_col="state",
        markers=True,
        color_discrete_sequence=SLOTS[:2],
    )
    st.plotly_chart(style(fig, 340, "%"), use_container_width=True)

    st.markdown(
        """
**How this connects to the economy and housing**

* **Disasters → losses → filings.** Storm damage raises loss ratios in the same year and is followed by
  larger approved rate changes and more filings. Insurers need the losses in their experience data before
  regulators accept the higher rates, so the effect shows up with a lag.
* **Construction costs and home values → coverage amounts.** Premiums are priced on replacement cost. The
  2021–22 surge in building-material prices raised claim costs and coverage amounts, which is the main reason
  rate changes stepped up after 2020 even in states without new disasters.
* **Regulation → timing, not direction.** Prior-approval states (CA) take months longer and approve less
  than requested. Increases still arrive, later, and sometimes after insurers have stopped writing new
  business. GAO finds longer approval times go with bigger FAIR-plan (last-resort insurer) market shares.
* **Insurance → housing.** Higher premiums raise monthly housing costs (escrowed with mortgages), weigh on
  affordability in coastal and wildfire areas, and non-renewals push owners to FAIR plans. Mortgage
  delinquency and price effects are an extension (see Data & methods).
"""
    )

# ---------------------------------------------------------------------------
# 6. Data & methods
# ---------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Coverage")
    cov = filings.groupby(["state", "year"]).size().unstack("year").fillna(0).astype(int)
    st.dataframe(cov, use_container_width=True)
    st.markdown(
        """
| Need | Source | Coverage | Notes |
|---|---|---|---|
| Regime by state | FIO *Analyses of U.S. Homeowners Insurance Markets* (Jan 2025) App. A.4 ← NAIC PA-10 (2022) | 51 | Applied to 2016–2026 |
| Texas filings | TDI open data `ittv-5xew` | TX | % change, Reviewed/Rejected/Withdrawn; no close date |
| Florida filings | FLOIR IRFS search | FL | Dates filed/closed, final action; no % in results |
| California filings | CDI rate-filing approvals lists (2016–18 via Internet Archive) + WARFF public notices | CA | Requested & approved %, status, closed date; notice date = received |
| Approval-time benchmark | GAO-26-107867 fig. 4 | 51 (binned) | 2020–2024 medians |
| Premium, loss ratio, non-renewal | FIO ZIP-level data 2018–2022 | 51 | Median across ZIP codes |
| Disasters | NOAA Storm Events (property damage), OpenFEMA | 51 | 2014– |
| Housing / macro | FHFA HPI, FRED (mortgage rate, PPI construction inputs, CPI) | 51 | |

**Why only three states have filing-level data.** SERFF Filing Access (used by most states) prohibits automated
downloads in its terms of use, and the NAIC and AM Best/S&P datasets are paid. California, Florida and Texas publish
filing lists themselves — one prior-approval state and two file-and-use states, also the three largest
homeowners markets.

**Definitions.** *Strict rejection* = disapproved / dispositioned. *Broad rejection* adds withdrawals (often
negotiated rejections). *Haircut* = approved below requested. *Days to approval* = closed − received for approved
filings. Top-10 groups are matched by NAIC group code (FL, CA) or affiliate names (TX).
"""
    )
