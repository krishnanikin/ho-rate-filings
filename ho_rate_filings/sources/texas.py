"""Texas: TDI Property & Casualty Rate Filings (Texas Open Data Portal, dataset ittv-5xew).

One row per filing with company, received date, estimated % change for existing
policyholders, SERFF id, effective dates, and status/closed type
(Reviewed | Withdrawn | Rejected). TDI does not publish the closing date, so Texas
contributes to rejection/withdrawal rates and rate changes but not to time to approval.
Texas is file-and-use: a filed rate can be used while TDI reviews it, so "Reviewed" means
the review closed without rejection, which we count as approved.
"""

from pathlib import Path

import pandas as pd

from ho_rate_filings.config import START_YEAR, TX_FILINGS_URL
from ho_rate_filings.sources.common import finalize, get_cached, match_group, to_pct

HO_TYPE = "Homeowners"
HO_SUBTYPES = ["Homeowners", "HOMEOWNERS/UMB"]
OUTCOME = {"Reviewed": "approved", "Rejected": "disapproved", "Withdrawn": "withdrawn"}


def download(raw_dir: Path, force: bool = False) -> Path:
    where = f"state_type_of_insurance = '{HO_TYPE}' AND received_date >= '{START_YEAR}-01-01'"
    return get_cached(
        TX_FILINGS_URL,
        raw_dir / "tx_tdi_rate_filings.csv",
        force=force,
        params={"$where": where, "$limit": 1_000_000},
    )


def clean(raw: Path) -> pd.DataFrame:
    df = pd.read_csv(raw, dtype=str)
    df = df[df["state_subtype_of_insurance"].isin(HO_SUBTYPES)].copy()
    pct = to_pct(df["percent_change"])
    status = df["status"].str.strip()
    closed = df["closed_type"].str.strip()
    outcome = closed.map(OUTCOME).fillna("other").where(status != "Pending", "open")
    # Blank or 0% means only rules/other non-premium items changed (TDI definition), but
    # some companies flag a rate filing in the product name and leave the % blank.
    is_rate = pct.fillna(0).ne(0) | df["product_name"].str.contains(
        r"\(RATE", case=False, na=False
    )
    eff = pd.to_datetime(df["effective_date_renewal"], errors="coerce").fillna(
        pd.to_datetime(df["effective_date_new_business"], errors="coerce")
    )
    out = pd.DataFrame(
        {
            "state": "TX",
            "filing_id": df["serff_id"],
            "serff_id": df["serff_id"],
            "company": df["company_name"].str.strip(),
            "line": df["state_subtype_of_insurance"],
            "filing_type": is_rate.map({True: "Rate", False: "Rule/Other"}),
            "is_rate": is_rate,
            "received_date": df["received_date"],
            "effective_date": eff,
            "status": closed.fillna(status),
            "outcome": outcome,
            # Texas publishes the filed change; under file-and-use it is the change put into
            # effect unless TDI rejects the filing.
            "requested_pct": pct,
            "approved_pct": pct.where(outcome == "approved"),
            "source": "TDI open data (ittv-5xew)",
        }
    )
    out["group"] = out["company"].map(match_group)
    return finalize(out)
