# Appendix: definitions, data sources and calculations

This appendix explains every number in the dashboard: what each term means, where the data come
from, and exactly how each figure is calculated. Figures quoted as examples are from the data pull
of **12 October 2026**; re-running `make pipeline` refreshes them.

---

## A. Scope

| Item | Definition |
|---|---|
| Line of business | Homeowners multi-peril insurance (NAIC type of insurance 04.0), owner-occupied homes. Texas also includes its "HOMEOWNERS/UMB" sub-type. Dwelling fire, renters/condo-only, mobile-home and flood filings are excluded unless an insurer files them under the homeowners line. |
| Time window | Filings **received from 1 January 2016** to the data pull date. Disaster and housing drivers start in 2014 so that one- and two-year lags exist for 2016. |
| Companies | The 10 largest homeowners insurance groups by direct written premium (NAIC): State Farm, Allstate, USAA, Liberty Mutual, Farmers, Travelers, American Family, Nationwide, Chubb, Erie. Each group includes all of its affiliated companies (section B.3). All other insurers are kept as "Other" for comparison. |
| States with filing-level data | **California, Florida, Texas.** These regulators publish filing lists for public use. Other states publish through SERFF Filing Access, whose terms prohibit automated downloads. |
| States with state-level data | All 50 states and DC: regulatory regime, GAO approval-time band, FIO premium/loss/non-renewal data, disasters, house prices and population. |

---

## B. Definitions

### B.1 Rate-filing regimes

| Regime | Meaning | Jurisdictions |
|---|---|---|
| **Prior Approval (PA)** | The insurer must submit the rate and wait for formal approval by the Department of Insurance (DOI) before charging it. Some states have a "deemer": a filing counts as approved if the DOI does not act within a set number of days. | 15 |
| **File and Use (FU)** | The insurer files rates before using them. It can start charging immediately or shortly after filing while the state reviews them. | 23 states + DC |
| **Use and File (UF)** | The insurer can charge new rates right away, provided it files them with the DOI within a set period. | 10 |
| **Other** | Wyoming uses open rating, with no filing review. Alaska uses a flex band: changes within the band are file-and-use, larger ones need prior approval. For charts that need exactly three groups, they are mapped to the closest regime (WY → UF, AK → FU). | 2 |

Source: Federal Insurance Office (FIO), *Analyses of U.S. Homeowners Insurance Markets 2018-2022*,
Appendix A.4, built from the NAIC chart *Rate Filing Methods for Property/Casualty Insurance* (PA-10,
2022). The 2018-22 classification is applied to the whole 2016-26 window. Known nuances are kept in the
notes column, for example Florida, where the insurer may choose FU or UF, and South Carolina, where
changes within ±7% are file-and-use. Regime definitions follow Guidewire, *US rate filings 101*.

### B.2 Filing types

| Term | Meaning | How it is identified |
|---|---|---|
| **Rate filing** | A filing that can change the premium policyholders pay. | **CA:** the CDI filing type contains RATE, VARIANCE, CLASS PLAN or NEW PROGRAM. **FL:** the search is restricted to "Rates" and "Rates & Forms" filings. **TX:** the % change is not zero, or the product name is flagged "(Rate)". |
| Rule / form filing | Changes underwriting rules or policy wording without a stated premium change. | Everything else. These are counted in filing totals but excluded from rejection, approval-time and rate-change metrics. |

### B.3 Insurance groups

A filing is assigned to a group by its **NAIC group code** where the source publishes one (Florida,
California). Otherwise, and in Texas, it is assigned by **affiliate company name**: for example "STATE
FARM LLOYDS" → State Farm, "SAFECO" → Liberty Mutual, "FIRE INSURANCE EXCHANGE" → Farmers. The full
list is `COMPANIES` in `ho_rate_filings/config.py`. Exclusions stop false matches, such as "FARM BUREAU"
being matched to Farmers.

### B.4 Dates

| Date | CA | FL | TX |
|---|---|---|---|
| **Received** | WARFF public-notice date. CDI posts a notice for each filing shortly after receipt, and it is matched for 96% of filings. | "Date filed" | "Received date" |
| **Closed** | "Action date" / "closed date" in the CDI approvals list | "Date closed" | Not published |
| **Effective** | n/a | Renewal effective date, else new-business effective date | Same rule |

### B.5 Outcomes

| Outcome | CA status | FL final action | TX closed type |
|---|---|---|---|
| approved | APPROVED | APPROVED, INFORMATIONAL/APPROVED | Reviewed (closed without rejection; under file-and-use the filed rate stands) |
| disapproved | DISAPPROVED, DENIED | DISAPPROVED | Rejected |
| withdrawn | WITHDRAWN | WITHDRAWN | Withdrawn |
| other | CLOSED and other | INFORMATIONAL, NO ACTION and others | — |
| open | n/a (lists contain closed filings only) | OPEN | Status "Pending" |

A filing is **dispositioned** if its outcome is approved, disapproved or withdrawn.

### B.6 Rate-change terms

- **Requested rate change (%)**: the overall statewide average premium change the insurer asks for,
  estimated across its existing policyholders in that state for that program. Individual policyholders
  can see much larger or smaller changes depending on location, coverage and discounts.
- **Approved rate change (%)**: the overall average change the regulator allowed.
  - **CA:** the "% rate change approved" column.
  - **TX:** equal to the filed change for filings TDI reviewed without rejecting. Texas is file-and-use, so the filed rate is the one in effect.
  - **FL:** not available in search results.
- **Haircut**: an approved filing whose approved change is more than 0.05 points below the requested
  change. The **haircut share** is the share of approved filings with a haircut. The **haircut size**
  is requested minus approved, in percentage points.

### B.7 Mean vs median rate increase

All rate-change statistics are calculated over **approved rate filings that publish a % change**
(CA and TX). Each filing counts once and is **not weighted by premium**, because premium affected is
not published consistently. One "observation" is one company's filing. When affiliates share a CDI file
number (for example 23-844, 23-844-A and 23-844-B for Farmers Insurance Exchange, Fire Insurance
Exchange and Mid-Century), each affiliate's filing counts separately.

- **Mean approved change** = sum of approved % changes ÷ number of approved filings. It answers "what
  is the average size of an approved change?" and is pulled up by a few very large increases.
- **Median approved change** = the middle value once the approved % changes are sorted (the average of
  the two middle values if the count is even). Half of approved filings were at or above it and half
  at or below it. It answers "what does a typical approved filing look like?" and is not affected by
  a few extreme filings.

**Worked example.** Top-10 groups' approved California rate filings received in 2023 (30 filings):

```
0.0  0.0  0.0  6.68  6.99  6.99  6.99  10.6  10.6  10.6  11.43  12.5  12.5  12.5  12.6
12.8  12.9  13.3  14.1  15.3  16.5  16.8  17.5  20.0  25.5  26.6  26.9  28.5  30.6  34.1
```

Mean = 432.4 ÷ 30 = **14.4%**. Median = average of the 15th and 16th values = (12.6 + 12.8) ÷ 2 =
**12.7%**. The mean is higher because of the 25-34% increases (Allstate 34.1%, USAA General Indemnity
30.6%, Liberty/Safeco 28.5%).

**Why the two can diverge a lot in California.** For 2020 onward, all insurers, the mean approved
change is 12.0% but the median is 7.0%. Many filings sit just below 7% (6.9%, 6.99%), which is
consistent with California's Proposition 103 rule that increases above 7% allow a request for a
public hearing. Use the **median** for "what a typical filing gets" and the **mean** for "the average
size of approved changes including the large ones". Neither is the average change in premiums paid
across all homeowners, which would require premium weights.

### B.8 Rejections and approval time

- **Strict rejection rate** = disapproved ÷ dispositioned rate filings.
- **Broad rejection rate** = (disapproved + withdrawn) ÷ dispositioned rate filings. Withdrawals are
  often negotiated rejections: the insurer withdraws when the regulator signals it will not approve.
- **Days to approval** = closed date − received date, in calendar days, for **approved** rate filings
  only (CA and FL). Negative values (data errors) are dropped. Approval times are summarised with the
  **median**, because a few filings take years.
- **Days to effective** = effective date − received date. This matters in FU/UF states, where rates can
  take effect before the review closes.

### B.9 Periods

- **Pre-COVID**: filings received 2016-2019. **Post-COVID**: received 2020 onward.
- "Filings per year" divides by the number of calendar years with data in each period.

### B.10 Disaster, housing and insurance-market measures

| Measure | Definition |
|---|---|
| Storm damage per resident | Sum of NOAA Storm Events **property damage** (all events, in the state, in the calendar year) ÷ state resident population. Reported in $ or $100s/$1,000s as labelled. Damage strings such as "1.5M" are converted to dollars (K = 10³, M = 10⁶, B = 10⁹). Hurricane, wildfire, hail, wind, tornado, flood and winter values are sub-totals by event type. |
| FEMA assistance | Individual & Households Program approved + Public Assistance obligated + Hazard Mitigation obligated, for **major disaster** declarations, by state and year of incident start. |
| House-price growth | Year-over-year % change in the annual average of FHFA's all-transactions House Price Index for the state. |
| Construction input-price growth | Year-over-year % change in the BLS PPI "inputs to residential construction, goods" (national, FRED WPUIP2311001). |
| Home-insurance CPI | BLS CPI "tenants' and household insurance" (FRED CUUR0000SEHD), national. |
| FIO premium / loss ratio / claim frequency / severity / non-renewal rate | From FIO's ZIP-code data (2018-2022). Each ZIP is mapped to a state by its first three digits, and the state value is the **median across ZIP codes**: a typical ZIP, not premium-weighted. Non-renewal rate = insurer-initiated non-renewals ÷ policies. |
| GAO approval-time band | GAO-26-107867, figure 4: median days from submission to approval, 2020-2024, in bands (≤100, 101-200, >300). Exact values are published only for Colorado (331) and California (305). |

### B.11 Market pullbacks

| Action | Meaning |
|---|---|
| Paused new business | Stopped accepting new homeowners applications in the state. Renewals continue. |
| Capped new business | Accepts new policies up to a stated monthly limit. |
| Restricted new business | Stops new policies for some areas or risk types, such as high-value homes in wildfire zones. |
| Non-renewals | Declines to renew a stated set of existing policies. Without a reported end date, it is drawn as a 12-month wave. |
| Exit / withdrawal | Stops new business and non-renews its whole book (or a whole brand) in the state. |
| Resumed / lifted cap | Restarts or removes limits on new business. |

---

## C. Data sources

All sources are public. Accessed 12 October 2026.

| # | Source | Publisher | Link | Coverage | Fields used | How obtained |
|---|---|---|---|---|---|---|
| 1 | Analyses of U.S. Homeowners Insurance Markets 2018-2022, App. A.4 | Federal Insurance Office (U.S. Treasury) | [report](https://home.treasury.gov/system/files/311/Analyses_of_US_Homeowners_Insurance_Markets_2018-2022_Climate-Related_Risks_and_Other_Factors_0.pdf) | 51 | Regime by state | Transcribed by hand (`reference/states.py`) |
| 2 | Rate Filing Methods for P/C Insurance (PA-10) | NAIC | [chart](https://content.naic.org/sites/default/files/model-law-chart-pa-10-rate-filing-methods-for-property-casualty-insurance-workers-comp-title.pdf) | 51 | Underlying source for #1; state notes | Reference |
| 3 | Property & Casualty Rate Filings (`ittv-5xew`) | Texas Department of Insurance | [data.texas.gov](https://data.texas.gov/dataset/Property-Casualty-Rate-Filings/ittv-5xew) | TX, 1998- | Company, received date, % change, SERFF id, effective dates, status, closed type | Socrata API (CSV) |
| 4 | IRFS Forms & Rates Filing Search | Florida Office of Insurance Regulation | [irfssearch.floir.gov](https://irfssearch.floir.gov/) | FL, 2001- | File log #, company, NAIC group, dates filed/closed, final action, effective dates | The page's own Advanced Search request, one per year. Filing documents (CAPTCHA) not used. |
| 5 | Rate Filing Approvals lists | California Department of Insurance | [insurance.ca.gov](https://www.insurance.ca.gov/0250-insurers/0800-rate-filings/0100-rate-filing-lists/rate-filing-approvals/) | CA, closed 2016- | File #, company, NAIC group, line, filing type, % requested, % approved, status, action date | Annual Excel files; 2016-18 from the Internet Archive |
| 6 | Web Access to Rate Filing Forms (WARFF) | California Department of Insurance | [WARFF](https://interactive.web.insurance.ca.gov/apex_extprd/f?p=186) | CA, 2016- | Public-notice date → received date | Weekly searches, 3 s apart |
| 7 | GAO-26-107867, Homeowners Insurance | U.S. GAO | [report](https://files.gao.gov/reports/GAO-26-107867/index.html) | 51 | Median approval-time band 2020-24 | Transcribed from figure 4 |
| 8 | FIO ZIP-level homeowners metrics 2018-2022 | Federal Insurance Office (re-hosted by Consumer Federation of America) | [CFA](https://consumerfed.org/news/blogs/download-analyses-of-us-homeowners-insurance-markets-2018-2022-climate-related-risks-and-other-factors-report-and-data-from-federal-insurance-office-fio/) | 51 | Premium per policy, loss ratio, claim frequency/severity, non-renewal rate | Excel download |
| 9 | Storm Events Database | NOAA NCEI | [csvfiles](https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/) | 51, 2014- | Event type, property damage | Yearly CSV files |
| 10 | Disaster Declarations Summaries; FEMA Web Disaster Summaries | FEMA (OpenFEMA) | [OpenFEMA](https://www.fema.gov/about/openfema/data-sets) | 51, 2014- | Major-disaster declarations, assistance amounts | API |
| 11 | House Price Index, state, all transactions | FHFA | [FHFA HPI](https://www.fhfa.gov/data/hpi) | 51 | Quarterly HPI | CSV |
| 12 | FRED series | Federal Reserve Bank of St. Louis (BLS, Freddie Mac, Census) | [FRED](https://fred.stlouisfed.org/) | US / 51 | MORTGAGE30US, WPUIP2311001, CUSR0000SAH1, CUUR0000SEHD, CPIAUCSL; {ST}POP, {ST}HOWN | CSV |
| 13 | News reports of rate changes | Various (see `news_rate_reports.csv`) | one link per row | CA, TX | Reported requested/approved % | Hand-curated |
| 14 | News reports of market pullbacks | Various (see `market_actions.csv`) | one link per row | CA, FL, NC | Action, dates, policies affected | Hand-curated |

**Not used, and why:** SERFF Filing Access (its terms prohibit automated downloads); NAIC Market
Share reports (the site blocks automated downloads); AM Best State Rate Filings / RateFilings.com and
S&P Global (paid).

---

## D. Calculations

### D.1 Filing-level fields (`features.enrich_filings`)

```
year              = year(received date); else CA file-number prefix (e.g. "23-613" → 2023); else year(closed)
days_to_close     = closed − received (calendar days; negative → missing)
days_to_approval  = days_to_close if outcome = approved
haircut_pts       = requested % − approved %
haircut           = haircut_pts > 0.05   (approved filings with both % values)
is_rejected_broad = outcome ∈ {disapproved, withdrawn}
lagged drivers    = state-year driver from year − 1 and year − 2, joined on the filing's state
```

### D.2 Company × state × year table (`features.company_state_year`)

```
rate_filings            = count of distinct rate filings
dispositioned           = count with outcome ∈ {approved, disapproved, withdrawn}
strict_rejection_rate   = disapproved / dispositioned
broad_rejection_rate    = (disapproved + withdrawn) / dispositioned
median_days_to_approval = median(days_to_approval) over approved rate filings
mean_requested_pct      = mean(requested %);  mean_approved_pct = mean(approved %)
haircut_share           = mean(haircut)
```

Dashboard heatmaps re-aggregate the filtered filings directly (same formulas) for the selected years
and groups.

### D.3 Pre- vs post-COVID tests (`modeling.train.period_comparison`)

For each state × (top-10 vs other) the dashboard compares, for 2016-19 vs 2020+:

- filings per year
- mean and median approved %
- broad rejection rate
- median days to approval

Differences in approved % use a **Welch t-test**; differences in days use a **Mann-Whitney U test**.
The **structural-break test** fits `approved % = a + b·t + c·post + d·(t × post)` with t = year − 2020,
and F-tests c = d = 0 (a Chow-type test).

### D.4 Driver regressions (`modeling.train`)

1. **Approved rate change (CA + TX, filing level, OLS)**
   `approved % = β1·damage(t−1) + β2·damage(t−2) + β3·HPI growth(t−1) + β4·construction PPI growth(t−1)
   + β5·post + β6·damage(t−1)×post + state FE + group FE`. Damage is in $100s per resident. Standard
   errors are clustered by state-year.
2. **Approval time (CA + FL, filing level, OLS)**: same right-hand side, with log(days to approval) as
   the outcome.
3. **All-states panel (FIO 2018-22, state-year, OLS)**:
   - Premium growth = damage(t−1) + HPI growth + regime + year FE.
   - Loss ratio = damage(t) + regime + year FE.
   - Non-renewal % = damage(t−1) + HPI growth + regime + year FE.

   Damage is in $1,000s per resident and standard errors are clustered by state. File and Use is the
   reference regime.

Coefficients are associations, not causal effects. State-level models are ecological.

### D.5 Event studies

For each catastrophe (state, date), rate filings received in the 8 quarters before and after are
counted. Quarter = floor(days from event ÷ 91). The comparison covers mean filings per quarter and the
filing-weighted mean requested change before vs after. "Complete window" means at least 6 quarters
exist on each side.

### D.6 News cross-check (`features.news_crosscheck`)

For each news report, the candidate filings are those with:

- the same state;
- a company name containing the report's company pattern;
- a published approved %;
- a received **or** closed date within 456 days (about 15 months) of the report date. The received
  date counts as well because interim emergency approvals can come long before a filing formally
  closes.

The best candidate has the smallest |approved % − reported %|, then the smallest date gap. The result
is:

- **Exact match** if the difference is ≤ 0.15 points;
- **Within 1 point** if ≤ 1.0;
- otherwise **Different value**, with an explanatory note where the reason is known (for example,
  interim vs final rates).

### D.7 Pullback context (`features.pullback_context`)

For each top-10 pullback in CA/FL/TX, the dashboard counts the same group's rate filings in the same
state whose decision date (closed, else received) falls in the 2 years before vs the 2 years after
the announcement. It also gives their mean approved % and the largest approved % afterwards.

---

## E. Limitations

- Filing-level coverage is three states (CA, FL, TX). They are the three largest homeowners markets and
  include one prior-approval and two file-and-use states, but other states may behave differently.
- Florida search results carry no % changes, and Texas does not publish closing dates.
- Rate statistics are unweighted averages across filings, not premium-weighted changes in what
  homeowners pay.
- The FIO regime classification covers 2018-22 and is held fixed for 2016-26.
- Two single days in California had more than 50 public notices, and the overflow rows were not
  retrieved.
- News and pullback tables cover events reported in the press. They are not a complete census.
- NOAA property-damage estimates are preliminary and do not include insured-loss adjustments.
