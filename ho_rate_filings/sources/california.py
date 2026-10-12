"""California: CDI rate filing approvals lists + WARFF public-notice dates.

1. "Rate Filing Approvals" lists (insurance.ca.gov): one workbook per closing year with
   file number, company, NAIC group, line, filing type, % rate change requested and
   approved, status (Approved, Withdrawn, Closed, Disapproved, ...) and the action/closed
   date. 2019 onward is posted on the CDI site; the 2016-2018 lists are read from Internet
   Archive copies.
2. WARFF (Web Access to Rate Filing Forms) search, filtered by Line Code = Homeowners
   Multi-Peril and public-notice date window. Under Proposition 103 the CDI posts a public
   notice for each filing shortly after it is received, so the notice date is our received
   date for time-to-approval. Each window is one GET of the public results page; windows
   with more than one page of results are split in half until they fit.
"""

from datetime import date, timedelta
from pathlib import Path
import re
import time

from bs4 import BeautifulSoup
from loguru import logger
import pandas as pd
import requests
from tqdm import tqdm

from ho_rate_filings.config import (
    CA_APPROVAL_FILES,
    CA_APPROVALS_BASE,
    CA_WARFF_SEARCH,
    HEADERS,
    REQUEST_DELAY,
    START_YEAR,
)
from ho_rate_filings.sources.common import finalize, get_cached, group_from_code, match_group

HO_LINE = "HOMEOWNERS MULTI-PERIL"
ARCHIVE_ROOT = (
    "http://www.insurance.ca.gov/0250-insurers/0800-rate-filings/0100-rate-filing-lists/"
    "rate-filing-approvals/upload/"
)
# Internet Archive snapshots of the annual lists no longer on the CDI site.
ARCHIVED_FILES = {
    2016: ("20171220004729", "APPROVAL-LIST-FOR-THE-YEAR-2016.xls"),
    2017: ("20190830202801", "Approval-List-2017.xls"),
    2018: ("20190830202803", "Approval-List-2018.xls"),
}
RATE_TYPES = ("RATE", "VARIANCE", "CLASS PLAN", "NEW PROGRAM")
OUTCOME = {
    "APPROVED": "approved",
    "DISAPPROVED": "disapproved",
    "DENIED": "disapproved",
    "WITHDRAWN": "withdrawn",
    "CLOSED": "other",
}
WARFF_PAGE_SIZE = 50
# CDI file numbers: "23-536", with "-A", "-B", ... for affiliates sharing one filing.
FILE_NUM = re.compile(r"\d{2}-\d+(?:-[A-Z0-9]+)?")


# ---------------------------------------------------------------------------
# Approval lists
# ---------------------------------------------------------------------------


def download_approvals(raw_dir: Path, force: bool = False) -> list[Path]:
    paths = []
    for year, (stamp, name) in ARCHIVED_FILES.items():
        url = f"https://web.archive.org/web/{stamp}id_/{ARCHIVE_ROOT}{name}"
        paths.append(get_cached(url, raw_dir / f"ca_approvals_{year}.xls", force=force))
    current_year = max(CA_APPROVAL_FILES)
    for year, name in CA_APPROVAL_FILES.items():
        out = raw_dir / f"ca_approvals_{year}{Path(name).suffix}"
        headers = {"User-Agent": "Mozilla/5.0"}  # the CDI site rejects non-browser agents
        paths.append(
            get_cached(
                CA_APPROVALS_BASE + name,
                out,
                force=force or year == current_year,
                headers=headers,
            )
        )
    return paths


def _find_col(columns: list[str], *keys: str) -> str | None:
    for col in columns:
        if all(k in col for k in keys):
            return col
    return None


def _excel_dates(values: pd.Series) -> pd.Series:
    """Parse a column mixing datetimes, date strings and Excel serial day numbers."""
    serial = pd.to_numeric(values, errors="coerce")
    from_serial = pd.to_datetime(serial, unit="D", origin="1899-12-30", errors="coerce")
    parsed = pd.to_datetime(values.where(serial.isna()), errors="coerce")
    return parsed.fillna(from_serial)


def read_approval_list(path: Path) -> pd.DataFrame:
    """Read one approvals workbook into standard columns (homeowners rows only)."""
    df = pd.read_excel(path, dtype=object)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip().upper() for c in df.columns]
    cols = list(df.columns)
    # The line description sits in "LINE CODE" (most years) or "SUBLINE" (2019).
    text = df.astype(str).apply(lambda col: col.str.strip().str.upper())
    is_ho = text.eq(HO_LINE).any(axis=1)
    df = df[is_ho].copy()
    req = _find_col(cols, "REQ")
    appr = _find_col(cols, "APPVD")
    when = (
        _find_col(cols, "ACTION DATE")
        or _find_col(cols, "CLOSED DATE")
        or _find_col(cols, "END DATE")
    )
    status = df[_find_col(cols, "STATUS")].astype(str).str.strip().str.upper()
    ftype = df[_find_col(cols, "FILING TYPE")].astype(str).str.strip().str.upper()
    grp_col = _find_col(cols, "GRP")
    serff_col = _find_col(cols, "SERFF")
    return pd.DataFrame(
        {
            "filing_id": df[_find_col(cols, "FILE")].astype(str).str.strip(),
            "company": df[_find_col(cols, "NAME")].astype(str).str.strip(),
            "naic_group": df[grp_col] if grp_col else pd.NA,
            "serff_id": df[serff_col].astype(str).str.strip() if serff_col else pd.NA,
            "filing_type": ftype,
            "status": status,
            "closed_date": _excel_dates(df[when]),
            "requested_pct": pd.to_numeric(df[req], errors="coerce"),
            "approved_pct": pd.to_numeric(df[appr], errors="coerce"),
            "list_file": path.name,
        }
    )


# ---------------------------------------------------------------------------
# WARFF public-notice dates
# ---------------------------------------------------------------------------


def _warff_window(start: date, end: date) -> tuple[int, list[list[str]]]:
    """Return (records found, result rows) for one public-notice date window."""
    fmt = "%m/%d/%Y"
    items = "P2_LINE_CODE,P2_PN_FROM_DATE,P2_PN_TO_DATE"
    values = f"{HO_LINE},{start.strftime(fmt)},{end.strftime(fmt)}"
    # A fresh session per query: the APEX app remembers earlier search items per session.
    with requests.Session() as session:
        session.headers.update(HEADERS)
        resp = session.get(f"{CA_WARFF_SEARCH}?p=186:2:0::::{items}:{values}", timeout=120)
    resp.raise_for_status()
    found = re.search(r"Record\(s\) found :\D*(\d+)", resp.text)
    soup = BeautifulSoup(resp.text, "lxml")
    rows = [[td.get_text(" ", strip=True) for td in tr.find_all("td")] for tr in soup("tr")]
    rows = [r for r in rows if len(r) >= 10 and FILE_NUM.fullmatch(r[0])]
    return (int(found.group(1)) if found else 0), rows


def download_notices(raw_dir: Path, force: bool = False, end: date | None = None) -> Path:
    """Collect public-notice dates for homeowners filings, one week at a time.

    Progress is saved after every week, so an interrupted run resumes where it stopped.
    The last eight weeks are always re-queried because notices are still being posted.
    """
    out = raw_dir / "ca_warff_public_notices.csv"
    cached = pd.read_csv(out, dtype=str) if out.exists() and not force else None
    end = end or date.today()
    done = set(cached["window"]) if cached is not None else set()
    records = [] if cached is None else cached.to_dict("records")
    refresh_from = end - timedelta(weeks=8)

    def collect(a: date, b: date, key: str) -> None:
        found, rows = _warff_window(a, b)
        time.sleep(REQUEST_DELAY)
        if found > len(rows) and found >= WARFF_PAGE_SIZE and a < b:
            mid = a + (b - a) // 2
            collect(a, mid, key)
            collect(mid + timedelta(days=1), b, key)
            return
        if found > len(rows):
            logger.warning(f"WARFF {a}..{b}: {found} found, {len(rows)} parsed")
        for r in rows:
            records.append(
                {
                    "window": key,
                    "pn_from": a.isoformat(),
                    "pn_to": b.isoformat(),
                    "filing_id": r[0],
                    "serff_id": r[1],
                    "naic_group": r[2],
                    "company": r[4],
                    "filing_type": r[7],
                    "program": r[8],
                    "requested_pct": r[9],
                }
            )

    week = date(START_YEAR, 1, 1)
    weeks = []
    while week <= end:
        weeks.append(week)
        week += timedelta(days=7)
    for start in tqdm(weeks, desc="WARFF weeks"):
        key = start.isoformat()
        if key in done and start < refresh_from:
            continue
        records = [r for r in records if r["window"] != key]
        collect(start, min(start + timedelta(days=6), end), key)
        # Keep an empty marker row so weeks with no notices are not re-queried.
        if not any(r["window"] == key for r in records):
            records.append({"window": key, "pn_from": key, "pn_to": key, "filing_id": ""})
        pd.DataFrame(records).to_csv(out, index=False)
    return out


def refine_notice_dates(notices: pd.DataFrame) -> pd.Series:
    """Received-date estimate per filing: midpoint of the narrowest window it was found in."""
    a = pd.to_datetime(notices["pn_from"])
    b = pd.to_datetime(notices["pn_to"])
    return a + (b - a) / 2


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------


def clean(approval_paths: list[Path], notices_path: Path | None) -> pd.DataFrame:
    lists = pd.concat([read_approval_list(p) for p in approval_paths], ignore_index=True)
    # A filing can appear in more than one list (e.g. YTD copies); keep the latest action.
    lists = lists.sort_values("closed_date").drop_duplicates("filing_id", keep="last")
    lists = lists[lists["filing_id"].str.fullmatch(FILE_NUM.pattern)]
    yy = lists["filing_id"].str[:2].astype(int)
    lists = lists[yy + 2000 >= START_YEAR]

    out = lists.copy()
    out["state"] = "CA"
    out["line"] = HO_LINE
    out["is_rate"] = out["filing_type"].str.contains("|".join(RATE_TYPES), regex=True)
    out["outcome"] = out["status"].map(OUTCOME).fillna("other")
    out["source"] = "CDI rate filing approvals lists"
    # Received date: WARFF public-notice date where available.
    out["received_date"] = pd.NaT
    if notices_path is not None and notices_path.exists():
        notices = pd.read_csv(notices_path, dtype=str).dropna(subset=["filing_id"])
        notices["pn_date"] = refine_notice_dates(notices)
        first = notices.sort_values("pn_date").drop_duplicates("filing_id")
        out = out.drop(columns="received_date").merge(
            first[["filing_id", "pn_date"]].rename(columns={"pn_date": "received_date"}),
            on="filing_id",
            how="left",
        )
    by_code = out["naic_group"].map(group_from_code)
    out["group"] = by_code.where(by_code != "Other", out["company"].map(match_group))
    return finalize(out)
