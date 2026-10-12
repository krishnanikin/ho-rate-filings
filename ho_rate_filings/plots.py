"""Render static figures to reports/figures (for the README).

python -m ho_rate_filings.plots
"""

from loguru import logger
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import typer

from ho_rate_filings.config import COVID_BREAK, FIGURES_DIR, PROCESSED_DATA_DIR

app = typer.Typer()

SLOTS = ["#2a78d6", "#eb6834", "#1baf7a"]
MUTED = "#898781"


def _save(fig: plt.Figure, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / f"{name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"saved {name}.png")


def _axes(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(MUTED)
    ax.grid(axis="y", color=MUTED, alpha=0.25)


def approved_change_figure(filings: pd.DataFrame) -> None:
    df = filings[filings["is_rate"].fillna(False) & filings["approved_pct"].notna()]
    yearly = df.groupby(["state", "year"])["approved_pct"].mean().unstack("state")
    fig, ax = plt.subplots(figsize=(8, 4))
    for color, state in zip(SLOTS, ["CA", "TX"]):
        if state in yearly:
            ax.plot(yearly.index, yearly[state], marker="o", lw=2, color=color, label=state)
            ax.annotate(state, (yearly.index[-1], yearly[state].iloc[-1]), xytext=(6, 0),
                        textcoords="offset points", va="center", color="#52514e")  # fmt: skip
    ax.axvline(COVID_BREAK - 0.5, color=MUTED, ls=":")
    ax.set_title("Mean approved homeowners rate change, all insurers (%)", loc="left")
    _axes(ax)
    ax.legend(frameon=False)
    _save(fig, "approved_change_by_year")


def approval_days_figure(filings: pd.DataFrame) -> None:
    df = filings[filings["days_to_approval"].notna() & filings["top10"]]
    med = df.groupby(["group", "state"], observed=True)["days_to_approval"].median().unstack()
    med = med.dropna(how="all").sort_values(med.columns[0])
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.38
    for i, (state, color) in enumerate(zip(med.columns, SLOTS)):
        ax.barh([y + i * width for y in range(len(med))], med[state], height=width - 0.04,
                color=color, label=state)  # fmt: skip
    ax.set_yticks([y + width / 2 for y in range(len(med))], med.index)
    ax.set_title("Median days from filing to approval, top-10 groups", loc="left")
    _axes(ax)
    ax.grid(axis="x", color=MUTED, alpha=0.25)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False)
    _save(fig, "approval_days_by_group")


@app.command()
def main():
    filings = pd.read_parquet(PROCESSED_DATA_DIR / "filings.parquet")
    filings["group"] = filings["group"].astype(str)
    approved_change_figure(filings)
    approval_days_figure(filings)


if __name__ == "__main__":
    app()
