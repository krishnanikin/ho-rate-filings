"""State homeowners rate-filing regimes (hand-curated reference table).

python -m ho_rate_filings.reference.states   # writes data/external/state_regimes.csv

Source: Federal Insurance Office, *Analyses of U.S. Homeowners Insurance Markets, 2018-2022*
(Jan 2025), Appendix A.4 "State Insurance Rate Regulatory Regimes by Region", which is built
from the NAIC chart *Rate Filing Methods for Property/Casualty Insurance* (PA-10, Fall 2022).
GAO-26-107867 (Feb 2026) uses the same classification and counts (23 + DC file-and-use,
15 prior approval, 10 use-and-file, Alaska and Wyoming in neither).

The FIO classification covers 2018-2022. We apply it to the whole 2016-2026 window; the
notes column flags known nuances (size-of-change thresholds, insurer choice of method).
"""

from loguru import logger
import pandas as pd
import typer

from ho_rate_filings.config import EXTERNAL_DATA_DIR, STATES

app = typer.Typer()

SOURCE_URL = (
    "https://home.treasury.gov/system/files/311/Analyses_of_US_Homeowners_Insurance_Markets_"
    "2018-2022_Climate-Related_Risks_and_Other_Factors_0.pdf"
)

# The three regimes in scope, with the definitions shown on the dashboard.
REGIMES = {
    "PA": (
        "Prior Approval",
        "The insurer must submit the rate and wait for formal DOI approval before charging it.",
    ),
    "FU": (
        "File and Use",
        (
            "The insurer files rates before using them and can start charging immediately "
            "or shortly after submission while the state reviews them."
        ),
    ),
    "UF": (
        "Use and File",
        (
            "The insurer can implement new rates right away, provided it submits the filing "
            "to the DOI within a specified timeframe."
        ),
    ),
    "Other": ("Other", "Open rating or flex band; see notes for the closest of the three."),
}

# FIO/NAIC raw classification by state.
FIO_CLASS = {
    "Open Rating": ["WY"],
    "Use-and-File": ["KY", "VT", "IL", "IA", "MO", "WI", "OK", "AZ", "UT", "ID"],
    "File-and-Use": [
        "AR",
        "FL",
        "GA",
        "VA",
        "CT",
        "DE",
        "DC",
        "ME",
        "MA",
        "NH",
        "RI",
        "IN",
        "MI",
        "MN",
        "OH",
        "MT",
        "NE",
        "SD",
        "KS",
        "TX",
        "CO",
        "NV",
        "NM",
        "OR",
    ],
    "Flex Band": ["AK"],
    "Prior Approval": [
        "AL",
        "LA",
        "MS",
        "NC",
        "SC",
        "TN",
        "MD",
        "NJ",
        "NY",
        "PA",
        "WV",
        "ND",
        "CA",
        "HI",
        "WA",
    ],
}
RAW_TO_CODE = {
    "Prior Approval": "PA",
    "File-and-Use": "FU",
    "Use-and-File": "UF",
    "Open Rating": "Other",
    "Flex Band": "Other",
}

# Nuances worth showing next to the headline regime.
NOTES = {
    "WY": "Open rating: no filing review (GAO marks approval time 'not applicable'). "
    "Closest of the three: Use and File.",
    "AK": "Flex band: changes within the band are file-and-use, larger ones need prior "
    "approval. Closest of the three: File and Use.",
    "FL": "Insurer may choose file-and-use or use-and-file; under use-and-file, premiums from "
    "a later-disallowed rate must be refunded (Fla. Stat. 627.062).",
    "SC": "Prior approval, but changes within +/-7% may be filed and used.",
    "ND": "Prior approval, but homeowners changes under 5% may be use-and-file once per "
    "calendar year per company.",
    "NC": "Prior approval with a rating bureau (NC Rate Bureau files base rates for the "
    "market); insurers may also use 'consent to rate' above bureau rates.",
    "CA": "Prior approval under Proposition 103; intervenors can request a public hearing "
    "for increases above 7%.",
    "TX": "File-and-use since 2003 (SB 14); TDI may disapprove after review.",
}

# Closest of the three in-scope regimes, used when a chart needs exactly PA / FU / UF.
CLOSEST = {"WY": "UF", "AK": "FU"}


def build() -> pd.DataFrame:
    rows = []
    for raw, states in FIO_CLASS.items():
        for st in states:
            code = RAW_TO_CODE[raw]
            rows.append(
                {
                    "state": st,
                    "state_name": STATES[st],
                    "regime": code,
                    "regime_name": REGIMES[code][0],
                    "regime_3way": CLOSEST.get(st, code),
                    "raw_regime": raw,
                    "effective_from": "2016-01-01",
                    "effective_to": "",
                    "notes": NOTES.get(st, ""),
                    "source": "FIO (Jan 2025) App. A.4 / NAIC PA-10 (Fall 2022)",
                    "source_url": SOURCE_URL,
                }
            )
    df = pd.DataFrame(rows).sort_values("state").reset_index(drop=True)
    missing = set(STATES) - set(df["state"])
    dupes = df["state"][df["state"].duplicated()].tolist()
    if missing or dupes:
        raise ValueError(f"regime table incomplete: missing={missing} duplicated={dupes}")
    return df


@app.command()
def main():
    df = build()
    EXTERNAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = EXTERNAL_DATA_DIR / "state_regimes.csv"
    df.to_csv(out, index=False)
    counts = df["raw_regime"].value_counts().to_dict()
    logger.success(f"wrote {out.name}: {len(df)} jurisdictions {counts}")


if __name__ == "__main__":
    app()
