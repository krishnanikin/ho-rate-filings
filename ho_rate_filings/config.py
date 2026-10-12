from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Load environment variables from .env file if it exists
load_dotenv()

# Paths
PROJ_ROOT = Path(__file__).resolve().parents[1]
logger.info(f"PROJ_ROOT path is: {PROJ_ROOT}")

DATA_DIR = PROJ_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EXTERNAL_DATA_DIR = DATA_DIR / "external"

MODELS_DIR = PROJ_ROOT / "models"

REPORTS_DIR = PROJ_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

# If tqdm is installed, configure loguru with tqdm.write
# https://github.com/Delgan/loguru/issues/135
try:
    from tqdm import tqdm

    logger.remove(0)
    logger.add(lambda msg: tqdm.write(msg, end=""), colorize=True)
except ModuleNotFoundError:
    pass

# ---------------------------------------------------------------------------
# Analysis settings
# ---------------------------------------------------------------------------

# Study window: filings received 2016 onward. External drivers start two years earlier so
# lagged disaster/housing variables exist for the first filing years.
START_YEAR = 2016
DRIVER_START_YEAR = 2014
# Pre-COVID = 2016-2019, post-COVID = 2020 onward.
COVID_BREAK = 2020

# Polite delay between requests to state regulator search pages (seconds).
REQUEST_DELAY = 2.0
HEADERS = {"User-Agent": "ho-rate-filings research pipeline (python-requests)"}
# FRED's CDN stalls on browser- and python-style agents but serves plain CLI agents.
FRED_HEADERS = {"User-Agent": "curl/8.7.1"}

# ---------------------------------------------------------------------------
# Companies: NAIC top-10 homeowners groups (by direct written premium)
# ---------------------------------------------------------------------------
# `naic_group` is the NAIC group code; `patterns` match affiliate company names (upper case)
# in sources that do not carry group codes (Texas). `exclude` drops look-alike names.
COMPANIES: dict[str, dict] = {
    "State Farm": {"naic_group": "0176", "patterns": ["STATE FARM"]},
    "Allstate": {
        "naic_group": "0008",
        "patterns": ["ALLSTATE", "ENCOMPASS", "CASTLE KEY", "NORTH LIGHT", "ESURANCE"],
    },
    "USAA": {
        "naic_group": "0200",
        "patterns": ["USAA", "UNITED SERVICES AUTOMOBILE", "GARRISON PROPERTY"],
    },
    "Liberty Mutual": {
        "naic_group": "0111",
        "patterns": [
            "LIBERTY MUTUAL",
            "LIBERTY INSURANCE CORP",
            "LIBERTY COUNTY MUTUAL",
            "LIBERTY LLOYDS",
            "SAFECO",
            "LM INSURANCE",
            "LM GENERAL",
            "FIRST NATIONAL INSURANCE COMPANY OF AMERICA",
            "GENERAL INSURANCE COMPANY OF AMERICA",
            "AMERICA FIRST INSURANCE",
            "AMERICAN ECONOMY INSURANCE",
            "AMERICAN STATES INSURANCE",
            "PEERLESS INDEMNITY",
            "PEERLESS INSURANCE",
        ],
    },
    "Farmers": {
        "naic_group": "0069",
        "patterns": [
            "FARMERS INSURANCE",
            "TEXAS FARMERS",
            "FARMERS LLOYDS",
            "ECONOMY PREFERRED",
            "ECONOMY FIRE",
            "METROPOLITAN LLOYDS",
            "METROPOLITAN PROPERTY",
            "FARMERS GROUP",
            "FARMERS SPECIALTY",
            "FIRE INSURANCE EXCHANGE",
            "MID-CENTURY",
            "FOREMOST",
            "21ST CENTURY",
            "TRUCK INSURANCE EXCHANGE",
        ],
        "exclude": ["FARMERS MUTUAL", "FARM BUREAU", "FARMERS ALLIANCE", "FARMERS UNION"],
    },
    "Travelers": {
        "naic_group": "3548",
        "patterns": [
            "TRAVELERS",
            "STANDARD FIRE INSURANCE",
            "AUTOMOBILE INSURANCE COMPANY OF HARTFORD",
            "CHARTER OAK FIRE",
            "PHOENIX INSURANCE",
        ],
    },
    "American Family": {
        "naic_group": "0473",
        "patterns": ["AMERICAN FAMILY", "HOMESITE", "MIDVALE", "AMFAM"],
    },
    "Nationwide": {
        "naic_group": "0140",
        "patterns": [
            "NATIONWIDE",
            "ALLIED PROPERTY",
            "AMCO INSURANCE",
            "DEPOSITORS INSURANCE",
            "CRESTBROOK",
            "HARLEYSVILLE",
        ],
    },
    "Chubb": {
        "naic_group": "0626",
        "patterns": [
            "CHUBB",
            "FEDERAL INSURANCE COMPANY",
            "PACIFIC INDEMNITY",
            "VIGILANT INSURANCE",
            "GREAT NORTHERN INSURANCE",
            "EXECUTIVE RISK",
        ],
    },
    "Erie": {"naic_group": "0213", "patterns": ["ERIE INSURANCE", "ERIE INDEMNITY"]},
}

# ---------------------------------------------------------------------------
# Source endpoints
# ---------------------------------------------------------------------------

# Texas Department of Insurance: Property & Casualty Rate Filings (Texas Open Data Portal).
TX_FILINGS_URL = "https://data.texas.gov/resource/ittv-5xew.csv"

# Florida OIR IRFS Forms & Rates Filing Search (public JSON endpoints behind the search page).
FL_IRFS_BASE = "https://irfssearch.floir.gov"

# California Department of Insurance: monthly/annual "Rate Filing Approvals" lists.
CA_APPROVALS_BASE = (
    "https://www.insurance.ca.gov/0250-insurers/0800-rate-filings/0100-rate-filing-lists/"
    "rate-filing-approvals/upload/"
)
# Annual year-to-date workbooks currently posted (closed filings by closing year).
CA_APPROVAL_FILES = {
    2019: "Approval-List-YTD-12-31-19.xls",
    2020: "Approval-Closed-List-YTD-12-31-20.xls",
    2021: "Approval-Closed-List-YTD-12-31-21.xls",
    2022: "Approval-Closed-List-YTD-12-31-22.xlsx",
    2023: "Approval-Closed-List-YTD-12-31-23.xlsx",
    2024: "Approval-Closed-List-YTD-12-31-24.xlsx",
    2025: "Approval-Closed-List-YTD-12-31-25.xlsx",
    2026: "Approval-Closed-List-YTD-9-30-26.xlsx",
}
# 2016-2018 lists are no longer on the CDI site; we read the copies kept by the Internet
# Archive's Wayback Machine.
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
# CDI Web Access to Rate Filing Forms (WARFF) search: gives each filing's public-notice date,
# which we use as the received date when computing time to approval in California.
CA_WARFF_SEARCH = "https://interactive.web.insurance.ca.gov/apex_extprd/f"

# External drivers
OPENFEMA = "https://www.fema.gov/api/open"
NOAA_STORM_EVENTS = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
FHFA_HPI_STATE = "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_state.csv"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
# National FRED series: mortgage rate, construction input prices, CPI shelter and CPI
# tenants' & household insurance.
FRED_NATIONAL = {
    "MORTGAGE30US": "30-year fixed mortgage rate (%)",
    "WPUIP2311001": "PPI: inputs to residential construction, goods",
    "CUSR0000SAH1": "CPI: shelter",
    "CUUR0000SEHD": "CPI: tenants' and household insurance",
    "CPIAUCSL": "CPI: all items",
}
# Per-state FRED series templates ({st} = two-letter code): resident population (thousands)
# and homeownership rate (%).
FRED_STATE = {"population": "{st}POP", "homeownership": "{st}HOWN"}
# Federal Insurance Office ZIP-level homeowners metrics, 2018-2022 (Jan 2025 report). The
# Treasury removed the file from its site; the Consumer Federation of America re-hosts it.
FIO_METRICS_URL = (
    "https://consumerfed.org/media/legacy/post_31852/Supporting_Underlying_Metrics_and_"
    "Disclaimer_for_Analyses_of_US_Homeowners_Insurance_Markets_2018-2022-2.xlsx"
)
# HUD ZIP -> state crosswalk is not needed: the first three ZIP digits identify the state.

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

STATES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
STATE_ABBR = {name.upper(): code for code, name in STATES.items()}

# States with filing-level public data in this project.
FILING_STATES = ["CA", "FL", "TX"]
