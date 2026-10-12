"""Shared helpers for the state filing sources.

Every source returns a DataFrame with the same filing-level columns (FILING_COLUMNS) so the
features step can stack them.
"""

from functools import cache
from pathlib import Path
import re
import time

from loguru import logger
import pandas as pd
import requests

from ho_rate_filings.config import COMPANIES, HEADERS

FILING_COLUMNS = [
    "state",  # two-letter code
    "filing_id",  # state file number (FL file log #, CA file #) or SERFF tracking #
    "serff_id",
    "company",  # filing company name as published
    "group",  # one of COMPANIES, or "Other"
    "naic_group",
    "line",  # source line/sub-line label
    "filing_type",  # Rate, Rate/Rule, Rule, Form, ...
    "is_rate",  # filing can change premium (rate or rate+rule/form)
    "received_date",
    "closed_date",
    "effective_date",
    "status",  # source disposition label
    "outcome",  # approved | disapproved | withdrawn | other | open
    "requested_pct",
    "approved_pct",
    "source",
]

OUTCOMES = ["approved", "disapproved", "withdrawn", "other", "open"]


@cache
def _group_regexes() -> list[tuple[str, re.Pattern, re.Pattern | None]]:
    out = []
    for group, spec in COMPANIES.items():
        inc = re.compile("|".join(re.escape(p) for p in spec["patterns"]))
        exc = spec.get("exclude")
        out.append((group, inc, re.compile("|".join(map(re.escape, exc))) if exc else None))
    return out


def match_group(name: str | float | None) -> str:
    """Map a filing company name to one of the top-10 groups (or "Other")."""
    if not isinstance(name, str):
        return "Other"
    upper = name.upper()
    for group, inc, exc in _group_regexes():
        if inc.search(upper) and not (exc and exc.search(upper)):
            return group
    return "Other"


def group_from_code(code: str | float | None) -> str:
    """Map an NAIC group code (any zero padding) to one of the top-10 groups (or "Other")."""
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return "Other"
    try:
        num = int(float(str(code).strip()))
    except ValueError:
        return "Other"
    for group, spec in COMPANIES.items():
        if int(spec["naic_group"]) == num:
            return group
    return "Other"


def get_cached(
    url: str,
    out: Path,
    force: bool = False,
    params: dict | None = None,
    headers: dict | None = None,
    delay: float = 0.0,
    timeout: int = 300,
) -> Path:
    """GET a URL into `out` unless it is already cached; retries transient errors."""
    if out.exists() and out.stat().st_size > 0 and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
            resp.raise_for_status()
            out.write_bytes(resp.content)
            logger.info(f"downloaded {out.name} ({len(resp.content) / 1e6:.2f} MB)")
            break
        except requests.RequestException as err:
            if attempt == 3:
                raise
            logger.warning(f"{url}: {err}; retrying")
            time.sleep(5 * (attempt + 1))
    if delay:
        time.sleep(delay)
    return out


def to_pct(series: pd.Series) -> pd.Series:
    """Parse percent strings such as '  9.9%' or '-0.3' into floats (percent units)."""
    cleaned = series.astype("string").str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(cleaned.replace({"": pd.NA, "-": pd.NA}), errors="coerce")


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Order columns, coerce dtypes, and add any missing standard columns as NA."""
    for col in FILING_COLUMNS:
        if col not in df:
            df[col] = pd.NA
    df = df[FILING_COLUMNS].copy()
    for col in ["received_date", "closed_date", "effective_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ["requested_pct", "approved_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["is_rate"] = df["is_rate"].astype("boolean")
    code = pd.to_numeric(df["naic_group"], errors="coerce")
    df["naic_group"] = code.map(lambda c: f"{int(c):04d}", na_action="ignore").astype("string")
    for col in ["state", "filing_id", "serff_id", "company", "group", "line", "filing_type"]:
        df[col] = df[col].astype("string")
    for col in ["status", "outcome", "source"]:
        df[col] = df[col].astype("string")
    return df.reset_index(drop=True)
