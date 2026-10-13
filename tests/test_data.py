import pandas as pd
import pytest

from ho_rate_filings.config import COMPANIES, STATES
from ho_rate_filings.dataset import parse_damage, zip_to_state
from ho_rate_filings.features import company_state_year
from ho_rate_filings.reference import states as regimes
from ho_rate_filings.sources import texas
from ho_rate_filings.sources.california import FILE_NUM, _excel_dates
from ho_rate_filings.sources.common import group_from_code, match_group, to_pct


def test_regime_table_covers_every_jurisdiction_once():
    df = regimes.build()
    assert len(df) == 51
    assert set(df["state"]) == set(STATES)
    assert df["state"].is_unique
    # Counts reported by FIO/GAO for 2018-2022.
    counts = df["raw_regime"].value_counts()
    assert counts["File-and-Use"] == 24  # 23 states + DC
    assert counts["Prior Approval"] == 15
    assert counts["Use-and-File"] == 10
    assert set(df.loc[df["regime"] == "Other", "state"]) == {"AK", "WY"}
    assert set(df["regime_3way"]) == {"PA", "FU", "UF"}


@pytest.mark.parametrize(
    "name, group",
    [
        ("STATE FARM LLOYDS", "State Farm"),
        ("FARMERS LLOYDS INSURANCE COMPANY OF TEXAS", "Farmers"),
        ("TEXAS FARM BUREAU MUTUAL INSURANCE COMPANY", "Other"),
        ("SAFECO INSURANCE COMPANY OF INDIANA", "Liberty Mutual"),
        ("ALLIED PROPERTY AND CASUALTY INSURANCE COMPANY", "Nationwide"),
        ("PACIFIC INDEMNITY COMPANY", "Chubb"),
        ("ERIE INSURANCE EXCHANGE", "Erie"),
        (None, "Other"),
    ],
)
def test_match_group(name, group):
    assert match_group(name) == group


def test_group_from_code_ignores_padding():
    assert group_from_code("0176") == "State Farm"
    assert group_from_code(176) == "State Farm"
    assert group_from_code("0069") == "Farmers"
    assert group_from_code(None) == "Other"
    assert group_from_code("9999") == "Other"


def test_to_pct():
    out = to_pct(pd.Series(["   9.9%", "  -0.3%", "", None, "-"]))
    assert out.iloc[0] == pytest.approx(9.9)
    assert out.iloc[1] == pytest.approx(-0.3)
    assert out.iloc[2:].isna().all()


def test_texas_clean(tmp_path):
    raw = tmp_path / "tx.csv"
    pd.DataFrame(
        {
            "company_name": ["STATE FARM LLOYDS", "ACME INS CO", "ALLSTATE TEXAS LLOYDS", "X"],
            "received_date": ["2020-01-01T00:00:00.000"] * 4,
            "state_type_of_insurance": ["Homeowners"] * 4,
            "state_subtype_of_insurance": ["Homeowners", "Homeowners", "Homeowners", "Dwelling"],
            "product_name": ["HO-1 (Rate)", "HO", "HO", "DP"],
            "percent_change": [None, "   0.0%", "  12.5%", "  3.0%"],
            "serff_id": ["A", "B", "C", "D"],
            "effective_date_new_business": [None] * 4,
            "effective_date_renewal": [None] * 4,
            "status": ["Closed", "Closed", "Closed", "Closed"],
            "closed_type": ["Reviewed", "Withdrawn", "Rejected", "Reviewed"],
        }
    ).to_csv(raw, index=False)
    df = texas.clean(raw).set_index("filing_id")
    assert list(df.index) == ["A", "B", "C"]  # dwelling dropped
    assert bool(df.loc["A", "is_rate"])  # flagged "(Rate)" despite blank %
    assert not bool(df.loc["B", "is_rate"])  # 0% = rule-only
    assert df.loc["C", "outcome"] == "disapproved"
    assert pd.isna(df.loc["C", "approved_pct"])  # rejected filings have no approved change
    assert df.loc["A", "group"] == "State Farm"


def test_company_state_year_rejection_rates():
    rows = []
    for outcome in ["approved", "approved", "withdrawn", "disapproved", "open"]:
        rows.append(
            {
                "state": "FL",
                "group": "Allstate",
                "year": 2021,
                "filing_id": f"f{len(rows)}",
                "is_rate": True,
                "outcome": outcome,
                "dispositioned": outcome != "open",
                "is_disapproved": int(outcome == "disapproved"),
                "is_withdrawn": int(outcome == "withdrawn"),
                "days_to_approval": 100.0 if outcome == "approved" else None,
                "requested_pct": None,
                "approved_pct": None,
                "haircut": None,
            }
        )
    out = company_state_year(pd.DataFrame(rows)).iloc[0]
    assert out["rate_filings"] == 5
    assert out["dispositioned"] == 4
    assert out["strict_rejection_rate"] == pytest.approx(0.25)
    assert out["broad_rejection_rate"] == pytest.approx(0.5)
    assert out["median_days_to_approval"] == 100


def test_ca_file_numbers_include_affiliate_suffixes():
    assert FILE_NUM.fullmatch("23-536")
    assert FILE_NUM.fullmatch("23-536-A")
    assert not FILE_NUM.fullmatch("FILE #")


def test_excel_dates_mixed():
    out = _excel_dates(pd.Series([pd.Timestamp("2020-05-01"), 44000, "2021-01-02"], dtype=object))
    assert out.iloc[0] == pd.Timestamp("2020-05-01")
    assert out.iloc[1] == pd.Timestamp("2020-06-18")
    assert out.iloc[2] == pd.Timestamp("2021-01-02")


def test_parse_damage_and_zip_to_state():
    dmg = parse_damage(pd.Series(["10.00K", "1.5M", "2B", "0", None]))
    assert list(dmg) == [1e4, 1.5e6, 2e9, 0, 0]
    st = zip_to_state(pd.Series([1001, 33101, 90210, 75001, 20001, 99501]))
    assert list(st) == ["MA", "FL", "CA", "TX", "DC", "AK"]


def test_curated_news_tables_are_valid():
    from ho_rate_filings.reference import news

    reports = news.news_rate_reports()
    actions = news.market_actions()
    assert reports["url"].str.startswith("https://").all()
    assert actions["url"].str.startswith("https://").all()
    assert pd.to_datetime(reports["news_date"]).notna().all()
    assert pd.to_datetime(actions["start"]).notna().all()
    assert set(actions["action"]) <= {
        "pause_new", "cap_new", "restrict_new", "nonrenew", "exit", "resume"
    }  # fmt: skip
    groups = {"Other", *COMPANIES}
    assert set(reports["group"]) <= groups
    assert set(actions["group"]) <= groups


def test_news_crosscheck_matches_interim_and_flags_differences():
    from ho_rate_filings.features import news_crosscheck

    filings = pd.DataFrame(
        {
            "state": ["CA", "CA", "CA"],
            "filing_id": ["24-1271", "24-1330", "23-613"],
            "company": ["STATE FARM GENERAL INSURANCE COMPANY"] * 3,
            "received_date": pd.to_datetime(["2024-07-08", "2024-07-15", "2023-03-20"]),
            "closed_date": pd.to_datetime(["2026-09-03", "2026-08-07", "2023-12-22"]),
            "requested_pct": [30.0, 38.0, 28.1],
            "approved_pct": [17.0, 32.8, 20.0],
        }
    )
    reports = pd.DataFrame(
        {
            "state": ["CA", "CA", "TX"],
            "group": ["State Farm"] * 3,
            "company_pattern": ["STATE FARM GENERAL", "STATE FARM GENERAL", "STATE FARM LLOYDS"],
            "news_date": ["2025-05-13", "2025-05-13", "2023-06-30"],
            "news_requested_pct": [21.8, None, None],
            "news_approved_pct": [17.0, 38.0, 7.6],
            "headline": ["x", "State Farm rental-dwelling emergency increase of 38%", "y"],
            "source": ["s"] * 3,
            "url": ["https://a"] * 3,
        }
    )
    out = news_crosscheck(filings, reports)
    # Interim approval: closed > 15 months after the report, but received within the window.
    assert out.loc[0, "filing_id"] == "24-1271"
    assert out.loc[0, "match_status"] == "Exact match"
    assert out.loc[1, "match_status"] == "Different value"
    assert out.loc[1, "note"]
    assert out.loc[2, "match_status"] == "No filing found"
