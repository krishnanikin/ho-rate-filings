"""News reports used to cross-check the filing data, and insurer market pullbacks.

python -m ho_rate_filings.reference.news   # writes data/external/news_*.csv

Both tables are hand-curated from news coverage (sources in each row). Dates are the
announcement or approval dates reported; "approx" marks month-level dates.

1. NEWS_RATE_REPORTS: rate changes reported in the press for the top-10 groups. The
   features step matches each to a filing in the regulator data (same state, company name
   pattern, approved % within 1 point, closed/received within 15 months of the report).
2. MARKET_ACTIONS: insurers pausing, capping or restricting new homeowners business,
   non-renewing policies, exiting, or resuming, by state.
"""

from loguru import logger
import pandas as pd
import typer

from ho_rate_filings.config import EXTERNAL_DATA_DIR

app = typer.Typer()

NEWS_COLUMNS = [
    "state",
    "group",
    "company_pattern",
    "news_date",
    "news_requested_pct",
    "news_approved_pct",
    "headline",
    "source",
    "url",
]
NEWS_RATE_REPORTS = [
    ("CA", "State Farm", "STATE FARM GENERAL", "2023-12-22", None, 20.0,
     "State Farm General gets ~20% average homeowners increase, effective Mar 15, 2024",
     "Sacramento Bee via InsuranceNewsNet",
     "https://insurancenewsnet.com/oarticle/state-oks-major-insurance-company-to-raise-homeowner-rates-by-20-in-california-the-sacramento-bee-2"),
    ("CA", "State Farm", "STATE FARM GENERAL", "2025-05-13", 21.8, 17.0,
     ("State Farm emergency homeowners increase after LA fires: 17% approved vs 21.8% asked; "
     "interim rate upheld in 2026 settlement"),
     "CBS News",
     "https://www.cbsnews.com/news/california-judge-approves-state-farms-17-insurance-increase"),
    ("CA", "State Farm", "STATE FARM GENERAL", "2025-05-13", None, 38.0,
     "State Farm rental-dwelling emergency increase of 38%",
     "Spectrum News",
     "https://spectrumlocalnews.com/ca/california/wildfires/2025/05/13/state-farm-homeowners-insurance-rate-increase"),
    ("CA", "Allstate", "ALLSTATE INSURANCE COMPANY", "2024-08-08", 34.1, 34.1,
     "Allstate gets 34.1% average increase (filed 39.6%, amended to 34.1%), 354,034 policies",
     "ABC7",
     "https://abc7.com/15248375"),
    ("CA", "USAA", "UNITED SERVICES AUTOMOBILE", "2024-11-15", None, 16.8,
     "USAA (parent company) homeowners +16.8% from mid-February 2025",
     "Insurance Business",
     "https://www.insurancebusinessmag.com/us/news/breaking-news/usaa-hikes-california-home-insurance-rates-515280.aspx"),
    ("CA", "USAA", "USAA CASUALTY", "2024-11-15", None, 25.9,
     "USAA Casualty homeowners +25.9% average from Dec 1, 2024",
     "Insurance Business",
     "https://www.insurancebusinessmag.com/us/news/breaking-news/usaa-hikes-california-home-insurance-rates-515280.aspx"),
    ("CA", "USAA", "USAA GENERAL INDEMNITY", "2024-11-15", None, 30.6,
     "USAA General Indemnity homeowners +30.6% from mid-November 2024",
     "Insurance Business",
     "https://www.insurancebusinessmag.com/us/news/breaking-news/usaa-hikes-california-home-insurance-rates-515280.aspx"),
    ("CA", "USAA", "GARRISON", "2024-11-15", None, 25.5,
     "Garrison Property & Casualty (USAA) homeowners +25.5% from early 2025",
     "Insurance Business",
     "https://www.insurancebusinessmag.com/us/news/breaking-news/usaa-hikes-california-home-insurance-rates-515280.aspx"),
    ("CA", "Farmers", "FARMERS INSURANCE EXCHANGE", "2026-05-15", 6.99, 1.5,
     ("Farmers' first Sustainable Insurance Strategy filing: 1.5% approved vs 6.99% requested, "
     "~915,000 policies"),
     "Newsweek",
     "https://www.newsweek.com/nearly-one-million-californians-face-home-insurance-spike-months-11944733"),
    ("TX", "Allstate", "ALLSTATE VEHICLE AND PROPERTY", "2023-06-30", None, 24.1,
     "Largest Texas homeowners increase of Q2 2023: Allstate Vehicle & Property +24.1%",
     "S&P Global Market Intelligence",
     "https://www.spglobal.com/market-intelligence/en/news-insights/articles/2023/8/texas-greenlit-21-homeowners-rate-hikes-of-more-than-10-in-q2-23-77109504"),
    ("TX", "State Farm", "STATE FARM LLOYDS", "2023-06-30", None, 7.6,
     "State Farm Lloyds' largest Texas homeowners change in Q2 2023: +7.6%",
     "S&P Global Market Intelligence",
     "https://www.spglobal.com/market-intelligence/en/news-insights/articles/2023/8/texas-greenlit-21-homeowners-rate-hikes-of-more-than-10-in-q2-23-77109504"),
]  # fmt: skip

# Market-level news that cannot be matched to single filings (shown as context).
MARKET_NEWS = [
    ("FL", "2026-01-12",
     ("Average Florida homeowners rate change fell from +9.6% (2023) to +1.3% (2024) and +0.9% "
     "(2025); 48 insurers filed decreases since Jan 2024 (APCIA)"),
     "Insurance Business",
     "https://www.insurancebusinessmag.com/us/news/property/florida-homeowners-insurance-rates-are-falling-as-reforms-take-hold-apcia-says-591320.aspx"),
    ("FL", "2025-12-19",
     "State Farm Florida files a 10% statewide homeowners decrease for 2026; Citizens -8.7%",
     "Bay News 9",
     "https://baynews9.com/fl/tampa/news/2025/12/19/more-home-insurance-companies-plan-rate-decreases-for-2026"),
    ("US", "2025-06-01",
     "Insurers non-renewed 2.02 million homeowners policies in 2024, up ~61% from 2023 (NAIC data)",
     "Insurify / InsuranceNewsNet",
     "https://insurancenewsnet.com/oarticle/home-insurers-dropped-2-million-policies-as-premiums-and-profits-rose-insurify"),
]  # fmt: skip

ACTION_COLUMNS = [
    "state",
    "group",
    "company",
    "action",
    "start",
    "end",
    "date_precision",
    "policies_affected",
    "detail",
    "source",
    "url",
]
# action: pause_new | cap_new | restrict_new | nonrenew | exit | resume
MARKET_ACTIONS = [
    ("CA", "Chubb", "Chubb", "restrict_new", "2021-10-26", None, "approx", None,
     ("Stops new high-value homes in wildfire-exposed areas and non-renews some; CEO cites "
     "inadequate approved rates. Later reopened with stricter wildfire underwriting."),
     "S&P Global Market Intelligence",
     "https://www.spglobal.com/market-intelligence/en/news-insights/articles/2021/10/chubb-pulling-back-sharply-in-california-ceo-blames-price-inadequacy-67294343"),
    ("CA", "Other", "AIG", "exit", "2022-01-01", None, "approx", None,
     "AIG exits the admitted California homeowners market.",
     "S&P Global Market Intelligence",
     "https://www.spglobal.com/marketintelligence/en/news-insights/latest-news-headlines/state-farm-pullback-intensifies-spotlight-on-california-s-rate-approval-process-76110864"),
    ("CA", "Allstate", "Allstate", "pause_new", "2022-11-01", None, "approx", None,
     "Pauses new homeowners, condo and commercial policies; existing customers renewed.",
     "Scripps News",
     "https://www.news5cleveland.com/allstate-stops-issuing-property-insurance-policies-in-california"),
    ("CA", "USAA", "USAA Casualty Insurance Co.", "pause_new", "2023-04-01", None, "approx", None,
     "USAA Casualty stops writing new California policies, citing rate inadequacy.",
     "Insurify",
     "https://insurify.com/homeowners-insurance/news/USAA-home-insurance-customers-facing-rate-increase"),
    ("CA", "State Farm", "State Farm General", "pause_new", "2023-05-26", None, "day", None,
     ("Stops accepting new homeowners applications (construction costs, catastrophe exposure, "
     "reinsurance). Still paused as of 2026."),
     "California Department of Insurance",
     "https://www.insurance.ca.gov/0400-news/0102-alerts/2023/Consumer-Alert-on-State-Farm's-Decision.cfm"),
    ("CA", "Farmers", "Farmers Insurance", "cap_new", "2023-07-03", "2024-12-14", "day", None,
     "Caps new homeowners policies at 7,000 a month.",
     "Insurance Journal",
     "https://www.insurancejournal.com/news/west/2023/07/07/729194.htm"),
    ("CA", "Farmers", "Farmers Insurance", "cap_new", "2024-12-14", "2025-11-21", "day", None,
     "Raises the monthly cap to 9,500 and reopens condo/renters lines.",
     "Insurance Journal",
     "https://amp.insurancejournal.com/news/west/2024/12/11/804458.htm"),
    ("CA", "Farmers", "Farmers Insurance", "resume", "2025-11-21", None, "day", None,
     "Removes the cap on new homeowners policies, crediting the Sustainable Insurance Strategy.",
     "Coverager",
     "https://coverager.com/farmers-lifts-cap-on-new-homeowners-policies-in-california/"),
    ("CA", "Nationwide", "Crestbrook (Nationwide Private Client)", "exit", "2023-12-01",
     "2025-06-15", "approx", 20275,
     ("Stops new policies in Dec 2023 and non-renews all California homeowners policies by "
     "June 15, 2025."),
     "InsuranceNewsNet",
     "https://insurancenewsnet.com/oarticle/home-insurer-withdraws-from-state"),
    ("CA", "Other", "The Hartford", "pause_new", "2024-02-01", None, "day", None,
     "Stops offering new homeowners policies.",
     "SJV Sun",
     "https://sjvsun.com/?p=89875"),
    ("CA", "State Farm", "State Farm General", "nonrenew", "2024-07-03", None, "day", 30000,
     ("Non-renews ~30,000 homeowners/rental/HOA/business policies (plus ~42,000 commercial "
     "apartment policies from Aug 20, 2024)."),
     "NBC San Diego",
     "https://www.nbcsandiego.com/news/national-international/state-farm-discontinuing-72000-home-policies-in-california/3469116/"),
    ("FL", "Farmers", "Farmers Insurance (Farmers-branded)", "exit", "2023-07-10", None, "approx",
     None,
     ("Stops offering Farmers-branded home, auto and umbrella policies and non-renews them; "
     "Foremost and Bristol West unaffected."),
     "InsuranceNewsNet",
     "https://insurancenewsnet.com/oarticle/farmers-insurance-exiting-florida"),
    ("FL", "Other", "AAA", "nonrenew", "2023-07-01", None, "approx", None,
     "Non-renews a small share of higher-exposure homeowners policies; keeps writing new ones.",
     "CBS News",
     "https://cbsnews.com/texas/news/aaa-insurance-policies-florida-nonrenewal"),
    ("NC", "Nationwide", "Nationwide", "nonrenew", "2023-12-01", "2024-07-31", "approx", 10525,
     ("Non-renews 10,525 personal lines policies (4.4% of its NC book) based on hurricane "
     "hazard, renewals Dec 2023 - Jul 2024."),
     "WTKR",
     "https://wtkr.com/news/10-500-nationwide-homeowners-policies-in-nc-dropped-including-some-in-obx"),
]  # fmt: skip


def news_rate_reports() -> pd.DataFrame:
    return pd.DataFrame(NEWS_RATE_REPORTS, columns=NEWS_COLUMNS)


def market_news() -> pd.DataFrame:
    return pd.DataFrame(MARKET_NEWS, columns=["state", "news_date", "headline", "source", "url"])


def market_actions() -> pd.DataFrame:
    df = pd.DataFrame(MARKET_ACTIONS, columns=ACTION_COLUMNS)
    df["top10"] = df["group"] != "Other"
    return df


@app.command()
def main():
    EXTERNAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    news_rate_reports().to_csv(EXTERNAL_DATA_DIR / "news_rate_reports.csv", index=False)
    market_news().to_csv(EXTERNAL_DATA_DIR / "news_market_context.csv", index=False)
    market_actions().to_csv(EXTERNAL_DATA_DIR / "market_actions.csv", index=False)
    logger.success("wrote news_rate_reports.csv, news_market_context.csv, market_actions.csv")


if __name__ == "__main__":
    app()
