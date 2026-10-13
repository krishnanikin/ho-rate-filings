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
        "news": pd.read_parquet(p / "news_crosscheck.parquet"),
        "pullback": pd.read_parquet(p / "pullback_context.parquet"),
        "actions": pd.read_csv(EXTERNAL_DATA_DIR / "market_actions.csv"),
        "market_news": pd.read_csv(EXTERNAL_DATA_DIR / "news_market_context.csv"),
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
        "News & pullbacks",
        "Pre vs post COVID",
        "Disasters & housing",
        "Data & methods",
        "Appendix",
    ]
)

# ---------------------------------------------------------------------------
# 1. Overview
# ---------------------------------------------------------------------------
with tabs[0]:
    disp = rate_top[rate_top["dispositioned"]]
    k = st.columns(6)
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
        help="Average of approved filing-level changes, CA and TX (FL does not publish % changes). "
        "See Appendix: mean vs median.",
    )
    k[5].metric(
        "Median approved change",
        num(rate_top["approved_pct"].median(), "{:+.1f}%"),
        help="Middle approved filing: half of approved changes were larger, half smaller.",
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
# 4. News cross-check and market pullbacks
# ---------------------------------------------------------------------------
ACTION_LABELS = {
    "pause_new": "Paused new business",
    "cap_new": "Capped new business",
    "restrict_new": "Restricted new business",
    "nonrenew": "Non-renewals",
    "exit": "Exit / withdrawal",
    "resume": "Resumed / lifted cap",
}
ACTION_COLORS = dict(zip(ACTION_LABELS.values(), SLOTS[:6]))

with tabs[3]:
    news = D["news"]
    st.subheader("Do the filings match what the news reported?")
    k = st.columns(3)
    k[0].metric("News reports checked", len(news))
    k[1].metric(
        "Exact match in regulator data", int((news["match_status"] == "Exact match").sum())
    )
    k[2].metric("Differences (explained)", int((news["match_status"] != "Exact match").sum()))

    nn = news.assign(
        label=news["state"]
        + " · "
        + news["company_pattern"].str.title()
        + " · "
        + news["news_date"].str[:7]
    )
    fig = go.Figure()
    for _, r in nn.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[r["news_approved_pct"], r["filing_approved_pct"]],
                y=[r["label"], r["label"]],
                mode="lines",
                line={"color": "#c3c2b7", "width": 2},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    fig.add_trace(
        go.Scatter(
            x=nn["news_approved_pct"],
            y=nn["label"],
            mode="markers",
            name="Reported in news",
            marker={"size": 13, "color": "rgba(0,0,0,0)", "line": {"color": SLOTS[1], "width": 2}},
            customdata=nn[["source"]],
            hovertemplate="%{y}<br>News: %{x:.1f}%<br>%{customdata[0]}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=nn["filing_approved_pct"],
            y=nn["label"],
            mode="markers",
            name="Approved in filing data",
            marker={"size": 8, "color": SLOTS[0]},
            customdata=nn[["filing_id"]],
            hovertemplate="%{y}<br>Filing %{customdata[0]}: %{x:.1f}%<extra></extra>",
        )
    )
    fig.update_xaxes(title="Approved rate change (%)", showgrid=True, gridcolor=GRID)
    st.plotly_chart(style(fig, 460), use_container_width=True)
    st.caption(
        "Open ring = figure in the news report; filled dot = approved change in the regulator's record. Overlap = match."
    )
    st.dataframe(
        news[
            [
                "state",
                "headline",
                "news_requested_pct",
                "news_approved_pct",
                "filing_id",
                "filing_requested_pct",
                "filing_approved_pct",
                "filing_closed",
                "match_status",
                "note",
                "url",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "headline": st.column_config.TextColumn("News report", width="large"),
            "news_requested_pct": st.column_config.NumberColumn(
                "News: requested %", format="%.1f"
            ),
            "news_approved_pct": st.column_config.NumberColumn("News: approved %", format="%.1f"),
            "filing_id": "Filing",
            "filing_requested_pct": st.column_config.NumberColumn(
                "Filing: requested %", format="%.1f"
            ),
            "filing_approved_pct": st.column_config.NumberColumn(
                "Filing: approved %", format="%.1f"
            ),
            "filing_closed": st.column_config.DateColumn("Filing closed"),
            "match_status": "Result",
            "note": st.column_config.TextColumn("Note", width="medium"),
            "url": st.column_config.LinkColumn("Source", display_text="link"),
        },
    )
    st.markdown("**Market-wide reports (context; not matchable to single filings)**")
    for _, r in D["market_news"].iterrows():
        st.markdown(
            f"- {r['state']} · {r['news_date'][:7]} — {r['headline']} ([{r['source']}]({r['url']}))"
        )

    st.subheader("Companies pulling back from writing homeowners insurance")
    act = D["actions"].copy()
    today = pd.Timestamp.today().normalize()
    act["Action"] = act["action"].map(ACTION_LABELS)
    act["start_dt"] = pd.to_datetime(act["start"])
    # Ongoing actions run to today; one-off events (resume) get a short marker.
    act["end_dt"] = pd.to_datetime(act["end"]).fillna(today)
    act.loc[act["action"] == "resume", "end_dt"] = act["start_dt"] + pd.Timedelta(days=45)
    # A non-renewal wave with no reported end is drawn over the following 12 months.
    wave = (act["action"] == "nonrenew") & act["end"].isna()
    act.loc[wave, "end_dt"] = act.loc[wave, "start_dt"] + pd.Timedelta(days=365)
    act["row"] = act["company"] + " · " + act["state"]
    act["policies"] = act["policies_affected"].map(
        lambda v: "" if pd.isna(v) else f"{int(v):,} policies"
    )
    show_other = st.toggle("Include insurers outside the top 10", value=True)
    if not show_other:
        act = act[act["top10"]]
    order = act.sort_values("start_dt").drop_duplicates("row")["row"].tolist()
    fig = px.timeline(
        act,
        x_start="start_dt",
        x_end="end_dt",
        y="row",
        color="Action",
        color_discrete_map=ACTION_COLORS,
        category_orders={"row": order, "Action": list(ACTION_LABELS.values())},
        hover_data={
            "detail": True,
            "policies": True,
            "source": True,
            "row": False,
            "start_dt": "|%b %Y",
            "end_dt": False,
        },
    )
    fig.update_traces(marker_line_color="white", marker_line_width=2)
    # Overlay the same groups' approved California rate changes (decision dates).
    ca_rate = filings[
        (filings["state"] == "CA")
        & filings["is_rate"].fillna(False)
        & filings["approved_pct"].gt(0)
        & filings["closed_date"].ge("2020-01-01")
    ]
    for row, grp in (
        act[act["state"] == "CA"].drop_duplicates("row")[["row", "group"]].itertuples(index=False)
    ):
        g = ca_rate[ca_rate["group"] == grp]
        if g.empty or grp == "Other":
            continue
        fig.add_trace(
            go.Scatter(
                x=g["closed_date"],
                y=[row] * len(g),
                mode="markers",
                marker={
                    "symbol": "diamond",
                    "size": 6 + g["approved_pct"].clip(0, 40) / 2,
                    "color": "#0b0b0b",
                    "line": {"color": "white", "width": 1},
                },
                name="Approved CA rate increase",
                legendgroup="rate",
                showlegend=bool(row == act[act["state"] == "CA"]["row"].iloc[0]),
                customdata=g[["company", "approved_pct"]],
                hovertemplate="%{customdata[0]}<br>Approved %{customdata[1]:.1f}% on %{x|%b %d, %Y}<extra></extra>",
            )
        )
    fig.add_vline(x=today, line_dash="dot", line_color=MUTED)
    fig.update_yaxes(autorange="reversed", title=None)
    st.plotly_chart(style(fig, 520), use_container_width=True)
    st.caption(
        "Bars run from announcement to end (or to today if still in force; non-renewal waves without a "
        "reported end span 12 months). Diamonds = approved California "
        "homeowners rate increases for the same group since 2020 (size ~ % approved). Hover for details and sources."
    )

    st.markdown(
        "**Rate approvals around each top-10 pullback (same state, 2 years before vs after)**"
    )
    pb = D["pullback"].assign(action=lambda d: d["action"].map(ACTION_LABELS))
    st.dataframe(
        pb,
        use_container_width=True,
        hide_index=True,
        column_config={
            "start": "Date",
            "filings_2y_before": "Rate filings decided, 2y before",
            "filings_2y_after": "Rate filings decided, 2y after",
            "mean_approved_pct_before": st.column_config.NumberColumn(
                "Mean approved %, before", format="%.1f"
            ),
            "mean_approved_pct_after": st.column_config.NumberColumn(
                "Mean approved %, after", format="%.1f"
            ),
            "max_approved_pct_after": st.column_config.NumberColumn(
                "Largest approved %, after", format="%.1f"
            ),
        },
    )

    st.subheader("Non-renewal rates by state (FIO, 2018–2022)")
    nr = panel[panel["fio_nonrenewal"].notna()][["state", "year", "fio_nonrenewal"]]
    focus = ["CA", "FL", "TX", "LA", "NC"]
    nat = nr.groupby("year", as_index=False)["fio_nonrenewal"].median().assign(state="US median")
    nr = pd.concat([nr[nr["state"].isin(focus)], nat])
    nr["fio_nonrenewal"] *= 100
    fig = px.line(
        nr,
        x="year",
        y="fio_nonrenewal",
        color="state",
        markers=True,
        color_discrete_map={**dict(zip(focus, SLOTS[:5])), "US median": MUTED},
        labels={"fio_nonrenewal": "Non-renewal rate (%)"},
    )
    fig.update_xaxes(dtick=1)
    st.plotly_chart(style(fig, 340, "Median ZIP non-renewal rate (%)"), use_container_width=True)
    st.caption(
        "Insurer-initiated non-renewals as a share of policies, median across ZIP codes (Federal Insurance "
        "Office). FIO data end in 2022; NAIC data reported in the news show non-renewals rose ~61% in 2024."
    )

# ---------------------------------------------------------------------------
# 5. Pre vs post COVID
# ---------------------------------------------------------------------------
with tabs[4]:
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
                ("Median approved change (%)", "median_approved_pct"),
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
# 6. Disasters & housing
# ---------------------------------------------------------------------------
with tabs[5]:
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
# 7. Data & methods
# ---------------------------------------------------------------------------
with tabs[6]:
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
| News reports & pullbacks | Hand-curated news coverage (source link per row) | CA, TX, FL, NC | Matched to filings: same company, approved % within 1 pt, within 15 months |
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

# ---------------------------------------------------------------------------
# 8. Appendix
# ---------------------------------------------------------------------------
with tabs[7]:
    st.subheader("Mean vs median approved rate change — explore")
    c1, c2, c3 = st.columns([1, 2, 1])
    ex_state = c1.selectbox("State", ["CA", "TX"], key="ex_state")
    ex_years = c2.slider("Received", START_YEAR, max_year, (2023, 2023), key="ex_years")
    ex_top = c3.toggle("Top-10 groups only", value=True, key="ex_top")
    ex = filings[
        (filings["state"] == ex_state)
        & filings["is_rate"].fillna(False)
        & (filings["outcome"] == "approved")
        & filings["approved_pct"].notna()
        & filings["year"].between(*ex_years)
    ]
    if ex_top:
        ex = ex[ex["top10"]]
    if ex.empty:
        st.info("No approved rate filings with a published % for this selection.")
    else:
        mean_v, median_v = ex["approved_pct"].mean(), ex["approved_pct"].median()
        k = st.columns(3)
        k[0].metric("Approved rate filings", len(ex))
        k[1].metric(
            "Mean approved change", f"{mean_v:+.1f}%", help="Sum of approved % ÷ number of filings"
        )
        k[2].metric(
            "Median approved change",
            f"{median_v:+.1f}%",
            help="Middle value of the sorted approved %",
        )
        rng = np.random.default_rng(0)
        fig = go.Figure(
            go.Scatter(
                x=ex["approved_pct"],
                y=rng.uniform(-0.3, 0.3, len(ex)),
                mode="markers",
                marker={
                    "size": 9,
                    "color": SLOTS[0],
                    "opacity": 0.75,
                    "line": {"color": "white", "width": 1},
                },
                customdata=ex[["company", "filing_id", "requested_pct"]],
                hovertemplate="%{customdata[0]}<br>Filing %{customdata[1]}<br>Requested %{customdata[2]:.1f}% · approved %{x:.1f}%<extra></extra>",
                showlegend=False,
            )
        )
        # Label each line on its outer side so close values do not collide.
        mean_side = "left" if mean_v >= median_v else "right"
        median_side = "right" if mean_side == "left" else "left"
        for value, label, color, side in [
            (mean_v, "Mean", SLOTS[1], mean_side),
            (median_v, "Median", "#0b0b0b", median_side),
        ]:
            fig.add_vline(
                x=value,
                line_color=color,
                line_width=2,
                line_dash="dash" if label == "Mean" else "solid",
            )
            fig.add_annotation(
                x=value,
                y=0.45,
                text=f" {label} {value:.1f}% ",
                showarrow=False,
                yshift=8,
                xanchor=side,
                font={"color": "#52514e"},
            )
        fig.update_yaxes(visible=False, range=[-0.5, 0.6])
        fig.update_xaxes(
            title="Approved rate change (%) — one dot per company filing",
            showgrid=True,
            gridcolor=GRID,
        )
        st.plotly_chart(style(fig, 260), use_container_width=True)
        st.caption(
            "Each dot is one approved company filing (affiliates sharing a file number count separately; "
            "unweighted by premium). The mean is pulled toward large increases; the median is the middle filing."
        )
    st.divider()
    st.markdown((ROOT / "docs" / "docs" / "appendix.md").read_text())
