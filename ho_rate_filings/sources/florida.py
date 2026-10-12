"""Florida: OIR IRFS Forms & Rates Filing Search (https://irfssearch.floir.gov).

We run the same Advanced Search a visitor runs on the page (Property & Casualty,
Line of Business 040 Homeowners Multi-Peril, Type of Insurance 04.0 Homeowners, filing type
Rates or Rates & Forms), one request per filing year, and keep the JSON the page renders.
Each filing has dates filed and closed, the final action (Approved, Disapproved, Withdrawn,
...), effective dates, and the NAIC group code.

IRFS does not return requested/approved rate changes for P&C filings in search results
(those live in filing documents, which sit behind a CAPTCHA that we do not automate), so
Florida contributes to approval times and outcomes but not to rate-change size.
"""

import json
from pathlib import Path
import re
import time

import pandas as pd
import requests

from ho_rate_filings.config import FL_IRFS_BASE, HEADERS, REQUEST_DELAY, START_YEAR
from ho_rate_filings.sources.common import finalize, group_from_code, match_group

LOB_HOMEOWNERS = 31  # "Homeowners Multi-Peril - (040)"
TOI_HOMEOWNERS = 5  # "Homeowners (04.0)"
OUTCOME = {
    "APPROVED": "approved",
    "INFORMATIONAL/APPROVED": "approved",
    "DISAPPROVED": "disapproved",
    "WITHDRAWN": "withdrawn",
    "OPEN": "open",
}


def _criteria(year: int) -> dict:
    """Advanced-search criteria for homeowners rate filings filed in `year`."""
    return {
        "IsNewItem": True,
        "area": 1,  # Property & Casualty
        "coNmSh": True,
        "coNm": None,
        "coNmSt": "2",
        "coNaicGrpCdSh": True,  # return the NAIC group code column
        "coNaicGrpCd": None,
        "coNaicGrpCdSt": "2",
        "fileLogNumSh": True,
        "fileTypeSh": True,
        "fileTypeForms": False,
        "fileTypeRates": True,
        "fileTypeBoth": True,
        "selProdType": "1",
        "enableProd": True,
        "selProdCats": [],
        "selLobSh": True,
        "selLob": LOB_HOMEOWNERS,
        "selToiSh": True,
        "selToi": TOI_HOMEOWNERS,
        "fileDtSh": True,
        "fileDtFrom": f"01/01/{year}",
        "fileDtTo": f"12/31/{year}",
        "closeDtSh": True,
        "effDtNewSh": True,
        "effDtRenewSh": True,
        "selFinActSh": True,
        "lhAdv": {"IsNewItem": True, "rtAndOr": "And"},
    }


def download(raw_dir: Path, force: bool = False, last_year: int | None = None) -> list[Path]:
    """Save one JSON file of search results per filing year."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    last_year = last_year or pd.Timestamp.today().year
    session = requests.Session()
    session.headers.update(HEADERS)
    token = None
    paths = []
    for year in range(START_YEAR, last_year + 1):
        out = raw_dir / f"fl_irfs_homeowners_rates_{year}.json"
        paths.append(out)
        # The current year is always refreshed; earlier years are cached.
        if out.exists() and not force and year < last_year:
            continue
        if token is None:
            page = session.get(FL_IRFS_BASE + "/", timeout=60)
            page.raise_for_status()
            token = re.search(
                r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page.text
            ).group(1)
        resp = session.post(
            FL_IRFS_BASE + "/Search/AdvancedSearch",
            data={"criteria": json.dumps(_criteria(year)), "__RequestVerificationToken": token},
            headers={"__RequestVerificationToken": token, "X-Requested-With": "XMLHttpRequest"},
            timeout=300,
        )
        resp.raise_for_status()
        out.write_text(resp.text)
        time.sleep(REQUEST_DELAY)
    return paths


def clean(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        rows.extend(json.loads(path.read_text()).get("Data", []))
    df = pd.DataFrame(rows).drop_duplicates("FileLogNumber")
    action = df["FinalAction"].str.upper().str.strip()

    def date(col: str) -> pd.Series:
        return pd.to_datetime(df[col], format="%m/%d/%Y", errors="coerce")

    out = pd.DataFrame(
        {
            "state": "FL",
            "filing_id": df["FileLogNumber"],
            "company": df["CoNm"].str.strip(),
            "naic_group": df["NaicGrpCd"],
            "line": df["Lob"],
            "filing_type": df["FilingType"],
            "is_rate": True,  # search limited to Rates and Rates & Forms filings
            "received_date": date("FileDt"),
            "closed_date": date("CloseDt"),
            "effective_date": date("EffDtRenew").fillna(date("EffDtNew")),
            "status": df["FinalAction"],
            "outcome": action.map(OUTCOME).fillna("other"),
            "source": "FLOIR IRFS search",
        }
    )
    # Group code first; about a quarter of rows have no code, so fall back to the name.
    by_code = out["naic_group"].map(group_from_code)
    out["group"] = by_code.where(by_code != "Other", out["company"].map(match_group))
    return finalize(out)
