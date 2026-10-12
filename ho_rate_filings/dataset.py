"""Download raw source data (data/raw) and clean it into tidy tables (data/interim).

python -m ho_rate_filings.dataset download   # fetch everything into data/raw
python -m ho_rate_filings.dataset process    # tidy raw files into data/interim

Filing-level data come from state regulators that publish it for public use (Texas open
data, Florida IRFS search, California CDI lists and WARFF search). SERFF Filing Access is
not used: its terms prohibit automated downloads.
"""

import gzip
import io
from pathlib import Path
import re
import time

from loguru import logger
import pandas as pd
import requests
from tqdm import tqdm
import typer

from ho_rate_filings.config import (
    DRIVER_START_YEAR,
    EXTERNAL_DATA_DIR,
    FHFA_HPI_STATE,
    FIO_METRICS_URL,
    FRED_CSV,
    FRED_HEADERS,
    FRED_NATIONAL,
    FRED_STATE,
    INTERIM_DATA_DIR,
    NOAA_STORM_EVENTS,
    OPENFEMA,
    RAW_DATA_DIR,
    STATE_ABBR,
    STATES,
)
from ho_rate_filings.reference import states as regimes
from ho_rate_filings.sources import california, florida, texas
from ho_rate_filings.sources.common import get_cached

app = typer.Typer()

# ---------------------------------------------------------------------------
# GAO benchmark: median days from submission to approval, 2020-2024 (GAO-26-107867, fig. 4)
# ---------------------------------------------------------------------------
# GAO publishes the map in bins; exact values are given in the text only for CO and CA.
GAO_APPROVAL_DAYS = {"CO": 331, "CA": 305}
GAO_APPROVAL_BIN = {"CO": ">300", "CA": ">300", "HI": "101-200", "FL": "101-200", "NJ": "101-200"}
GAO_URL = "https://files.gao.gov/reports/GAO-26-107867/index.html"


def gao_benchmark() -> pd.DataFrame:
    rows = []
    for st in STATES:
        rows.append(
            {
                "state": st,
                "gao_bin": "n/a (no review)" if st == "WY" else GAO_APPROVAL_BIN.get(st, "<=100"),
                "gao_median_days": GAO_APPROVAL_DAYS.get(st),
                "source_url": GAO_URL,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def fred(series: str, out_dir: Path, force: bool = False) -> Path:
    return get_cached(
        FRED_CSV.format(series=series), out_dir / f"{series}.csv", force, headers=FRED_HEADERS
    )


def openfema(entity: str, version: str, out: Path, params: dict, force: bool = False) -> Path:
    """Page through an OpenFEMA entity into one CSV."""
    if out.exists() and not force:
        return out
    frames, skip, top = [], 0, 10_000
    while True:
        resp = requests.get(
            f"{OPENFEMA}/{version}/{entity}",
            params={**params, "$top": top, "$skip": skip, "$format": "json"},
            timeout=300,
        )
        resp.raise_for_status()
        batch = resp.json()[entity]
        frames.append(pd.DataFrame(batch))
        if len(batch) < top:
            break
        skip += top
    df = pd.concat(frames, ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    logger.info(f"downloaded {out.name} ({len(df):,} rows)")
    return out


def storm_events(out_dir: Path, force: bool = False) -> list[Path]:
    """NOAA Storm Events 'details' files, one gzip CSV per year."""
    listing = requests.get(NOAA_STORM_EVENTS, timeout=60).text
    names = sorted(
        set(re.findall(r"StormEvents_details-ftp_v1\.0_d(\d{4})_c\d+\.csv\.gz", listing))
    )
    paths = []
    for year in names:
        if int(year) < DRIVER_START_YEAR:
            continue
        fname = re.search(rf"StormEvents_details-ftp_v1\.0_d{year}_c\d+\.csv\.gz", listing).group(
            0
        )
        paths.append(
            get_cached(NOAA_STORM_EVENTS + fname, out_dir / f"storm_details_{year}.csv.gz", force)
        )
    return paths


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def download(
    force: bool = typer.Option(False, help="Re-download even if cached"),
    skip_notices: bool = typer.Option(False, help="Skip the slow CA public-notice crawl"),
):
    """Fetch every raw source into data/raw."""
    raw = RAW_DATA_DIR
    logger.info("Texas TDI open data")
    texas.download(raw / "tx", force)
    logger.info("Florida IRFS search")
    florida.download(raw / "fl", force)
    logger.info("California CDI approval lists")
    california.download_approvals(raw / "ca", force)
    if not skip_notices:
        logger.info("California WARFF public-notice dates (weekly; resumable)")
        california.download_notices(raw / "ca", force)

    logger.info("OpenFEMA disaster declarations and per-disaster assistance totals")
    openfema(
        "DisasterDeclarationsSummaries",
        "v2",
        raw / "fema" / "declarations.csv",
        {
            "$filter": f"fyDeclared ge {DRIVER_START_YEAR}",
            "$select": "disasterNumber,state,declarationType,declarationDate,fyDeclared,"
            "incidentType,declarationTitle,incidentBeginDate,designatedArea",
        },
        force,
    )
    openfema("FemaWebDisasterSummaries", "v1", raw / "fema" / "disaster_summaries.csv", {}, force)

    logger.info("NOAA Storm Events")
    storm_events(raw / "noaa", force)

    logger.info("FHFA house price index (state, quarterly)")
    get_cached(FHFA_HPI_STATE, raw / "fhfa" / "hpi_at_state.csv", force, headers=FRED_HEADERS)

    logger.info("FRED national and state series")
    for series in FRED_NATIONAL:
        fred(series, raw / "fred", force)
    for st in tqdm(STATES, desc="FRED states"):
        for template in FRED_STATE.values():
            try:
                fred(template.format(st=st), raw / "fred", force)
            except requests.HTTPError as err:
                logger.warning(f"FRED {template.format(st=st)}: {err}")
            time.sleep(0.2)

    logger.info("FIO ZIP-level homeowners metrics 2018-2022 (~15 MB)")
    get_cached(FIO_METRICS_URL, raw / "fio" / "fio_zip_metrics.xlsx", force, headers=FRED_HEADERS)
    logger.success("download complete")


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

# ZIP3 prefix ranges -> state (USPS sectional centers; territories and military omitted).
ZIP3_RANGES = [
    (5, 5, "NY"), (10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"), (39, 49, "ME"),
    (50, 59, "VT"), (60, 69, "CT"), (70, 89, "NJ"), (100, 149, "NY"), (150, 196, "PA"),
    (197, 199, "DE"), (200, 200, "DC"), (201, 201, "VA"), (202, 205, "DC"), (206, 219, "MD"),
    (220, 246, "VA"), (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"),
    (320, 349, "FL"), (350, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"),
    (400, 427, "KY"), (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"), (500, 528, "IA"),
    (530, 549, "WI"), (550, 567, "MN"), (569, 569, "DC"), (570, 577, "SD"), (580, 588, "ND"),
    (590, 599, "MT"), (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"),
    (700, 714, "LA"), (716, 729, "AR"), (730, 749, "OK"), (750, 799, "TX"), (800, 816, "CO"),
    (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"), (850, 865, "AZ"), (870, 884, "NM"),
    (885, 885, "TX"), (889, 898, "NV"), (900, 961, "CA"), (967, 968, "HI"), (970, 979, "OR"),
    (980, 994, "WA"), (995, 999, "AK"),
]  # fmt: skip


def zip_to_state(zips: pd.Series) -> pd.Series:
    z3 = pd.to_numeric(zips, errors="coerce") // 100
    out = pd.Series(pd.NA, index=zips.index, dtype="string")
    for lo, hi, st in ZIP3_RANGES:
        out[(z3 >= lo) & (z3 <= hi)] = st
    return out


def clean_fio(path: Path) -> pd.DataFrame:
    """FIO ZIP metrics -> state-year medians across ZIP codes."""
    df = pd.read_excel(path, sheet_name="Supporting Underlying Metrics")
    df.columns = [c.strip() for c in df.columns]
    df["state"] = zip_to_state(df["ZIP Code"])
    metrics = {
        "Premiums Per Policy": "fio_premium",
        "Loss Ratio": "fio_loss_ratio",
        "Claim Frequency": "fio_claim_freq",
        "Claim Severity": "fio_claim_severity",
        "Nonrenewal Rate": "fio_nonrenewal",
    }
    out = (
        df.dropna(subset=["state"])
        .groupby(["state", "Year"])[list(metrics)]
        .median()
        .rename(columns=metrics)
        .reset_index()
        .rename(columns={"Year": "year"})
    )
    out["fio_zips"] = df.dropna(subset=["state"]).groupby(["state", "Year"]).size().values
    return out


DAMAGE_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "H": 1e2}
# NOAA event types grouped into the perils that drive homeowners losses.
PERIL = {
    "Hurricane (Typhoon)": "hurricane", "Hurricane": "hurricane", "Tropical Storm": "hurricane",
    "Storm Surge/Tide": "hurricane", "Tropical Depression": "hurricane",
    "Wildfire": "wildfire", "Hail": "hail", "Thunderstorm Wind": "wind",
    "High Wind": "wind", "Strong Wind": "wind", "Tornado": "tornado",
    "Flash Flood": "flood", "Flood": "flood", "Coastal Flood": "flood",
    "Winter Storm": "winter", "Ice Storm": "winter", "Blizzard": "winter",
    "Heavy Snow": "winter", "Extreme Cold/Wind Chill": "winter", "Frost/Freeze": "winter",
}  # fmt: skip


def parse_damage(values: pd.Series) -> pd.Series:
    s = values.astype("string").str.strip().str.upper()
    num = pd.to_numeric(s.str.extract(r"^([\d.]+)")[0], errors="coerce").fillna(0)
    mult = s.str.extract(r"([KMBH])$")[0].map(DAMAGE_MULT).fillna(1)
    return (num * mult).where(s.notna(), 0)


def clean_storms(paths: list[Path]) -> pd.DataFrame:
    """Storm Events -> state-year property damage ($) by peril."""
    frames = []
    for p in paths:
        with gzip.open(p, "rb") as fh:
            df = pd.read_csv(
                io.BytesIO(fh.read()),
                usecols=["STATE", "YEAR", "EVENT_TYPE", "DAMAGE_PROPERTY"],
                dtype=str,
            )
        df["state"] = df["STATE"].str.upper().map(STATE_ABBR)
        df["year"] = df["YEAR"].astype(int)
        df["peril"] = df["EVENT_TYPE"].map(PERIL).fillna("other")
        df["damage"] = parse_damage(df["DAMAGE_PROPERTY"])
        frames.append(df.dropna(subset=["state"]))
    df = pd.concat(frames)
    wide = df.pivot_table(
        index=["state", "year"], columns="peril", values="damage", aggfunc="sum", fill_value=0
    )
    wide.columns = [f"storm_damage_{c}" for c in wide.columns]
    wide["storm_damage_total"] = wide.sum(axis=1)
    return wide.reset_index()


def clean_fema(declarations: Path, summaries: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Major-disaster declarations and federal assistance ($) per state-year."""
    dec = pd.read_csv(declarations)
    dec = dec[dec["declarationType"] == "DR"]  # major disasters
    dec["year"] = pd.to_datetime(dec["incidentBeginDate"]).dt.year
    per_disaster = dec.drop_duplicates("disasterNumber")[
        ["disasterNumber", "state", "year", "incidentType", "declarationTitle"]
    ]
    amounts = pd.read_csv(summaries)
    amt_cols = ["totalAmountIhpApproved", "totalObligatedAmountPa", "totalObligatedAmountHmgp"]
    amounts = amounts[["disasterNumber", *amt_cols]].fillna(0)
    merged = per_disaster.merge(amounts, on="disasterNumber", how="left").fillna(
        dict.fromkeys(amt_cols, 0)
    )
    merged["fema_assistance"] = merged[amt_cols].sum(axis=1)
    out = merged.groupby(["state", "year"]).agg(
        fema_major_disasters=("disasterNumber", "nunique"),
        fema_assistance=("fema_assistance", "sum"),
        fema_ihp=("totalAmountIhpApproved", "sum"),
    )
    return out.reset_index(), merged


def clean_fhfa(path: Path) -> pd.DataFrame:
    """FHFA all-transactions HPI -> annual average and year-over-year growth by state."""
    df = pd.read_csv(path, header=None, names=["state", "year", "quarter", "hpi"])
    df["hpi"] = pd.to_numeric(df["hpi"], errors="coerce")
    annual = df.groupby(["state", "year"], as_index=False)["hpi"].mean()
    annual["hpi_growth"] = annual.groupby("state")["hpi"].pct_change() * 100
    return annual


def _read_fred(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index(pd.to_datetime(df["date"]))["value"]


def clean_fred(fred_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    national = pd.DataFrame(
        {s: _read_fred(fred_dir / f"{s}.csv").resample("YS").mean() for s in FRED_NATIONAL}
    )
    national.index = national.index.year
    national.index.name = "year"
    national = national.rename(
        columns={
            "MORTGAGE30US": "mortgage_rate",
            "WPUIP2311001": "ppi_res_construction",
            "CUSR0000SAH1": "cpi_shelter",
            "CUUR0000SEHD": "cpi_home_insurance",
            "CPIAUCSL": "cpi_all",
        }
    )
    for col in ["ppi_res_construction", "cpi_shelter", "cpi_home_insurance", "cpi_all"]:
        national[f"{col}_growth"] = national[col].pct_change() * 100
    rows = []
    for st in STATES:
        rec = {}
        for name, template in FRED_STATE.items():
            path = fred_dir / f"{template.format(st=st)}.csv"
            if path.exists():
                rec[name] = _read_fred(path).resample("YS").mean()
        if rec:
            df = pd.DataFrame(rec)
            df["state"] = st
            df["year"] = df.index.year
            rows.append(df.reset_index(drop=True))
    state = pd.concat(rows, ignore_index=True)
    state["population"] = state["population"] * 1000  # FRED reports thousands
    return national.reset_index(), state


@app.command()
def process():
    """Tidy raw files into data/interim (parquet)."""
    raw, out = RAW_DATA_DIR, INTERIM_DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    EXTERNAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

    regimes.build().to_csv(EXTERNAL_DATA_DIR / "state_regimes.csv", index=False)
    gao_benchmark().to_csv(EXTERNAL_DATA_DIR / "gao_approval_days.csv", index=False)

    tx = texas.clean(raw / "tx" / "tx_tdi_rate_filings.csv")
    fl = florida.clean(sorted((raw / "fl").glob("fl_irfs_homeowners_rates_*.json")))
    notices = raw / "ca" / "ca_warff_public_notices.csv"
    ca = california.clean(sorted((raw / "ca").glob("ca_approvals_*")), notices)
    filings = pd.concat([tx, fl, ca], ignore_index=True)
    filings.to_parquet(out / "filings.parquet", index=False)
    logger.info(f"filings: {filings.groupby('state').size().to_dict()}")

    fema, disasters = clean_fema(
        raw / "fema" / "declarations.csv", raw / "fema" / "disaster_summaries.csv"
    )
    fema.to_parquet(out / "fema_state_year.parquet", index=False)
    disasters.to_parquet(out / "fema_disasters.parquet", index=False)
    clean_storms(sorted((raw / "noaa").glob("storm_details_*.csv.gz"))).to_parquet(
        out / "storms_state_year.parquet", index=False
    )
    clean_fhfa(raw / "fhfa" / "hpi_at_state.csv").to_parquet(
        out / "hpi_state_year.parquet", index=False
    )
    national, state = clean_fred(raw / "fred")
    national.to_parquet(out / "macro_national.parquet", index=False)
    state.to_parquet(out / "macro_state.parquet", index=False)
    fio = raw / "fio" / "fio_zip_metrics.xlsx"
    if fio.exists():
        clean_fio(fio).to_parquet(out / "fio_state_year.parquet", index=False)
    logger.success("process complete")


if __name__ == "__main__":
    app()
