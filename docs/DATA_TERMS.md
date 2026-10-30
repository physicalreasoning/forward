# Data terms

Last reviewed: 2026-10-12

This is a research summary, not legal advice.

Scope: the third-party data sources used by Physical Reasoning projects (forward, isotherm, causal-jepa, and the site at physicalreasoning.ai). Every quote below was read from the live page or the published PDF on 2026-10-12 unless marked otherwise. Where a page could not be fetched, this document says so.

## Summary

| Source | What we use it for | Licence / terms | Can publish derived results | Aggregate scores | Raw data | Attribution required |
|---|---|---|---|---|---|---|
| Kalshi | Market prices, candlesticks, order-book snapshots and settlements for weather and other event contracts (isotherm backtests, benchmarks, world-model training) | Proprietary. Developer Agreement v1.1, KalshiEX Rulebook v1.29 Rule 11.1, Kalshi Data Terms of Use, Member Agreement. No open licence. | Unclear (contract language reaches "derivative works" and requires prior approval for public disclosures relating to Kalshi; get written permission) | Unclear (same reasoning; lower risk than raw, still not expressly permitted) | No: candles/price histories. No: order-book recordings. Not without prior written authorization. | None granted; Kalshi Marks may not be used without authorization |
| Open-Meteo | Weather forecasts and historical weather (where used) | Data: CC BY 4.0. Free API: non-commercial only, rate limited. Code: AGPLv3. | Yes | Yes | Yes, under CC BY 4.0 (check upstream model licences, e.g. UK Met Office is CC BY-SA) | Yes: link "Weather data by Open-Meteo.com" next to any display, plus licence link and change note |
| Iowa Environmental Mesonet (IEM) | Archived NWS MOS forecasts, ASOS observations, NWS Daily Climate Reports (CLI, Kalshi's settlement source) | Public domain per IEM disclaimer | Yes | Yes | Yes | Not required; "would be appreciated" |
| NOAA / NWS | Underlying source of MOS, CLI, ASOS data (via IEM) | Public domain unless noted | Yes | Yes | Yes | Not required; must not imply endorsement; 17 U.S.C. 403 notice if a copyrighted work consists predominantly of NWS material |
| NOAA NODD (MRMS, GOES) | MRMS radar rain rate and GOES-19 imagery from the AWS Open Data Registry, for the WM-2 prototype (docs/WM2_DRAFT.md) | "Open to the public and can be used as desired" (registry entries, read 2026-10-30) | Yes | Yes | Yes, marked as modified when modified | Requested; must not imply endorsement; modified data must not be presented as original NOAA data |
| Yahoo Finance | Hourly/daily prices for financial, commodity and crypto series (e.g. RB=F gasoline futures) via query1.finance.yahoo.com | Yahoo Terms of Service; Yahoo Finance data disclaimer: "You must not redistribute" | Unclear, likely acceptable for findings that do not reproduce the data, but ToS bars derivative works without permission | Unclear | No | Not applicable (no redistribution right); do not use Yahoo branding |
| ECMWF open data | IFS/AIFS forecasts (directly or via Open-Meteo) | CC BY 4.0 plus ECMWF Terms of Use | Yes | Yes | Yes | Yes: specific ECMWF copyright, source, licence and disclaimer wording (see below) |

## Kalshi

Documents read:

- Kalshi Developer Agreement v1.1: https://kalshi-public-docs.s3.amazonaws.com/Kalshi-Developer-Agreement.pdf (S3 last-modified 2023-11-09)
- Kalshi Data Terms of Use: https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf (S3 last-modified 2024-09-11; identical copy at https://kalshi-public-docs.s3.amazonaws.com/kalshiEX-data-terms-of-service.pdf)
- KalshiEX LLC Rulebook v1.29: https://kalshi-public-docs.s3.amazonaws.com/regulatory/rulebook/Kalshi%20DCM%20Rulebook%20v.1.29.pdf (S3 last-modified 2026-08-17)
- Kalshi Member Agreement: https://kalshi-public-docs.s3.amazonaws.com/regulatory/agreement/kalshi_member_agreement.pdf (S3 last-modified 2026-10-01)
- API docs home: https://docs.kalshi.com

Could not fetch: https://kalshi.com/developer-agreement, https://kalshi.com/legal, https://kalshi.com/terms and other kalshi.com pages returned HTTP 429 (Vercel Security Checkpoint) to both curl and WebFetch, and the Wayback Machine has no snapshot. So we could not confirm that the S3 Developer Agreement v1.1 is the exact version currently linked from docs.kalshi.com, and we could not read any separate kalshi.com website Terms of Service. A search result claiming to show Kalshi "Terms of Service ... last updated May 5, 2026" came from kalhsi.it.com, a look-alike domain, and was ignored.

### Which terms apply

The API docs bind every API user to the Developer Agreement, including unauthenticated market-data use (https://docs.kalshi.com):

> By continuing to use or access Kalshi's API, you are agreeing to be bound to our Developer Agreement

The Member Agreement incorporates the Rulebook (Section II, Services):

> Your access to and use of the Services is fully and exclusively subject to your acceptance of and compliance with this Agreement, the Kalshi Klear Self-Clearing Member Agreement, the KalshiEX Rulebook, the Kalshi Klear Rulebook, and any other terms and agreements duly posted by on https://kalshi.com/regulatory or otherwise (together the "Terms").

### Developer Agreement v1.1

Section 3, Prohibitions:

> Use of Kalshi APIs is expressly limited to facilitating a members own trading on the Exchange; all other usages are disallowed and may result in account suspension.

> 3.1. Collecting, caching, aggregating, or storing data or content accessed via the API except for purposes of facilitating your own trading on Kalshi. You may not share such data or content with third parties in any manner without prior written authorization from Kalshi.

> 3.5. Accessing the API for purposes of monitoring the availability, performance, or functionality of any of Kalshi's services or for any other benchmarking or competitive purposes.

Section 6.4, Public Statements:

> You must obtain prior written approval from Kalshi prior to releasing any statements, written media releases, public announcements and public disclosures, including promotional or marketing materials, relating to Kalshi, the Kalshi Marks, Kalshi Services, Kalshi API, or this Agreement.

Section 6.1:

> You may use the Kalshi Marks only as expressly authorized in this Agreement.

### Rulebook v1.29, Rule 11.1 (Property Rights)

> (b) Subject to the provisions of this Rule 11.1, each Participant hereby acknowledges and agrees that Kalshi is the owner of all rights, title and interest in and to all intellectual property and other proprietary rights (including all copyright, patent, trademark or trade secret rights) in market data, and all derivative works based thereon, and further agree not to distribute, create derivative works based on, or otherwise use or commercially exploit market data and any such derivative works, provided that Participants may use market data for their own internal business purposes. Without limiting the generality of the foregoing, Participants may not distribute, sell or retransmit market data exchange to any third party.

Rule 11.1(a) also lists "market data" inside "Proprietary Information" and says each Participant "shall not ... reproduce, republish, broadcast, create derivative works based on ... the Proprietary Information" and agrees "to keep the Proprietary Information confidential and not to transfer, rent, lease, copy, loan, sell or distribute" it.

Rule 11.1(d) ("Transaction data shall not be disclosed publicly other than on an aggregated or anonymous basis ...") is an obligation on Kalshi about participant transaction data. It is not a permission for us to publish aggregates.

Rule 2.17(b) says what Kalshi itself publishes:

> Kalshi shall make public on a daily basis information on settlement prices, volume, open interest, and opening and closing ranges for actively traded Contracts.

### Kalshi Data Terms of Use (website data)

These cover "Kalshi Data" made available on kalshi.com, defined as "volume, bid-ask prices, opening and closing range prices, high-low prices, settlement prices, indexes, open interest and related information, market descriptions, materials, and other content on the Website".

Section I, Permitted Uses:

> You may access content only for your personal use for non-commercial purposes. Non-commercial use does not include the use of Kalshi Data without prior written consent from Kalshi in connection with: (1) the development of any software program, including, but not limited to, training a machine learning or artificial intelligence system; or (2) providing archived or cached data sets containing Kalshi Data to another person or entity.

Section II, Prohibited Uses:

> unless Kalshi, its applicable affiliate, and/or an applicable third party provider give you prior written authorization, you are strictly prohibited from selling, licensing, renting, modifying, changing, manipulating, altering, printing, collecting, copying, reproducing, downloading (other than to view only where a link is provided), uploading, transmitting, disclosing, distributing, disseminating, publicly displaying, publishing, editing, adapting, creating derivative works, electronically extracting or scrubbing, scraping, compiling (including, without limitation, through framing or systematic retrieval to create collections, compilations, databases or directories) or conducting 'text and data mining' (as those terms are defined in EU Directive 2019/790) in relation to any Kalshi Data

> For the avoidance of doubt and to the fullest extent permitted by law, use of any Kalshi Data (including associated metadata) in any manner for any machine learning and/or artificial intelligence, including without limitation for the purposes of training, coding, or development of artificial intelligence technologies, tools, or solutions or machine learning language models, or otherwise for the purposes of using or in connection with the use of such technologies, tools, or models to generate any information, material, data, derived works, content, or output is expressly prohibited.

Note on scope: the Data Terms are framed around the Website; API access is framed by the Developer Agreement and Rulebook. It is unclear whether the ML prohibition reaches data pulled from the API, but the API terms are at least as restrictive on storage and sharing.

### Member Agreement, Section XI (Data Use Consent)

This runs the other way (our orders and trades licensed to Kalshi), but confirms Kalshi treats price and order data as its asset:

> You hereby grant Kalshi a worldwide, perpetual, irrevocable, royalty-free, full sublicensable and freely assignable license to store, use, copy, display, disseminate and create derivative works from: (i) the price and quantity data for each transaction entered into by You that is executed via the Services and (ii) each bid, offer and/or order provided via the Services by You.

### Answers

| Question | Answer | Basis |
|---|---|---|
| (a) Publish derived results (model scores, research findings) | Unclear | No clause permits it. Rulebook 11.1(b) claims "all derivative works based thereon" and limits use to "internal business purposes"; Developer Agreement 6.4 requires prior written approval for "public disclosures ... relating to Kalshi ... Kalshi API"; the Data Terms bar "creating derivative works" and ML use. Findings that state conclusions without reproducing prices are the lowest-risk form, and facts are not copyrightable, but the contract terms are broader than copyright. |
| (b) Publish aggregate scores/statistics | Unclear | Same as (a). Nothing in the terms carves out aggregates for third parties; Rule 11.1(d) applies to Kalshi, not to us. |
| (c) Publish raw candles / price histories | No | Developer Agreement 3.1 ("may not share such data or content with third parties in any manner without prior written authorization"); Rulebook 11.1(b) ("may not distribute, sell or retransmit market data"); Data Terms I(2) and II. |
| (d) Publish raw order-book recordings | No | Same clauses as (c). Order-book snapshots are market data obtained via the API. |

Related risk: the research use itself (collecting and storing API data for non-trading research, training models on it) sits outside Developer Agreement Section 3 ("expressly limited to facilitating a members own trading") and, for website data, inside the Data Terms ML prohibition. Kalshi announced an in-house "Kalshi Research" unit on 2025-12-22 that "will give researchers access to Kalshi's platform data" (reported at https://crypto.news/kalshi-prediction-market-in-house-research-wing-2025/; the kalshi.com/research page could not be fetched, and no contact address was verified from a primary source). That is the obvious route for written permission.

## Open-Meteo

Pages read: https://open-meteo.com/en/terms and https://open-meteo.com/en/licence

Free API terms (https://open-meteo.com/en/terms):

> By using the Free API for non-commercial use you agree to following terms:
> Less than 10'000 API calls per day, 5'000 per hour and 600 per minute.
> You may only use the free API services for non-commercial purposes.
> You accept to the CC-BY 4.0 licence, as specified in the licence conditions.

The terms table also lists a free-tier monthly limit of "300.000 calls / month".

Non-commercial examples:

> Using our service for private or non-profit websites or apps that do not have subscriptions or advertising.
> Utilizing our service for personal home automation purposes.
> Using our service for public research conducted at public institutions.
> Incorporating our service into educational content.

Commercial examples:

> Operating websites or apps that have subscriptions or display advertisements.
> Integrating our service into commercial products or promotional activities.
> Conducting undisclosed research at commercial entities.

Paid tier:

> The data obtained through the API is provided under the terms of the CC-BY 4.0 licence, as specified in the licence conditions.

Licence (https://open-meteo.com/en/licence):

> API data are offered under Attribution 4.0 International (CC BY 4.0)

> You are free to share: copy and redistribute the material in any medium or format and adapt: remix, transform, and build upon the material.

> Attribution: You must give appropriate credit, provide a link to the licence, and indicate if changes were made. You may do so in any reasonable manner, but not in any way that suggests the licensor endorses you or your use.

> You must include a link next to any location Open-Meteo data are displayed, for example:
> `<a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a>`

Code:

> Source code is available on GitHub under the GNU Affero General Public Licence Version 3 AGPLv3 or any later version.

Citation suggested for research:

> Zippenfenig, P. (2023). Open-Meteo.com Weather API [Computer software]. Zenodo. https://doi.org/10.5281/ZENODO.7970649

Upstream sources listed on the licence page carry their own licences: ECMWF, DWD, Met Norway, CMA, BOM, KNMI, DMI, ItaliaMeteo-ARPAE, MeteoSwiss and GeoNames are "CC-BY Licence"; UK Met Office is "CC-BY-SA Licence"; NOAA NCEP links to https://www.weather.gov/disclaimer; CMC, Météo-France, JMA, Copernicus Marine, Copernicus C3S and GloFAS link to their own licences.

Assessment: an open, non-profit research collective with no ads or subscriptions fits the non-commercial examples. Using free-tier forecasts to drive real-money trading for profit is not listed either way; under the Creative Commons non-commercial definition the terms point to, it likely counts as commercial. Treat it as unclear and use a paid plan for any live trading use.

## Iowa Environmental Mesonet (IEM)

Page read: https://mesonet.agron.iastate.edu/disclaimer.php

> While we use care to provide accurate weather/climatic information, errors may occur because of equipment or other failure. We therefore provide this information without any warranty of accuracy. Users of this weather/climate data do so at their own risk, and are advised to use independent judgement as to whether to verify the data presented.

> Usage of IEM Products
> The materials found on this website are in the public domain and may be used freely by anyone for any lawful purpose. Attributing the Iowa Environmental Mesonet of Iowa State University would be appreciated.

The ASOS download page (https://mesonet.agron.iastate.edu/request/download.phtml) names its upstream sources ("Unidata IDD, NCEI ISD, and MADIS One Minute ASOS") and notes "This archive simply provides the as-is collection of historical observations, very little quality control is done." No separate citation requirement was found; the site lists publications that cite IEM data.

## NOAA / National Weather Service

Page read: https://www.weather.gov/disclaimer. Relevant because NWS Daily Climate Reports (CLI) settle Kalshi weather markets and MOS forecasts are NWS products (both fetched through IEM).

> The information on National Weather Service (NWS) Web pages are in the public domain, unless specifically noted otherwise, and may be used without charge for any lawful purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for NWS information -- see below), 2) use it in a manner that implies an endorsement or affiliation with NOAA/NWS, or 3) modify its content and then present it as official government material.

> As required by 17 U.S.C. § 403, third parties producing copyrighted works consisting predominantly of the material appearing in NWS Web pages must provide notice with such work(s) identifying the NWS material incorporated and stating that such material is not subject to copyright protection.

> Use of the NWS name ("National Weather Service") and/or visual identifier are protected under trademark law and may not be used without permission from the NWS.

## NOAA Open Data Dissemination (MRMS, GOES)

Pages read on 2026-10-30: the AWS Open Data Registry entries for NOAA MRMS (https://registry.opendata.aws/noaa-mrms-pds/, source https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-mrms-pds.yaml) and NOAA GOES (noaa-goes.yaml in the same repository). Both carry the same licence text:

> NOAA data disseminated through NODD are open to the public and can be used as desired. NOAA makes data openly available to ensure maximum use of our data, and to spur and encourage exploration and innovation throughout the industry. NOAA requests attribution for the use or dissemination of unaltered NOAA data. However, it is not permissible to state or imply endorsement by or affiliation with NOAA. If you modify NOAA data, you may not state or imply that it is original, unaltered NOAA data.

The buckets (`s3://noaa-mrms-pds`, `s3://noaa-goes19`) are read anonymously over HTTPS; no account or key is involved. The MRMS registry entry also notes that the University of Oklahoma retains the right to commercially license the MRMS software; that concerns running the system, not using its published fields. What forward publishes from MRMS (aggregate scores; tiles if ever released) is averaged and cut, so it is labelled as modified and credited to NOAA MRMS without implying endorsement.

## Yahoo Finance

Pages read: Yahoo Terms of Service https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html (last updated 4 August 2026), Yahoo Finance data providers page https://help.yahoo.com/kb/SLN2310.html, Yahoo Developer Network API terms https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html, yfinance README https://github.com/ranaroussi/yfinance

Yahoo Finance data page (https://help.yahoo.com/kb/SLN2310.html):

> Do not redistribute information - Yahoo Finance provides all information as is. You must not redistribute information displayed on or provided by Yahoo Finance.
> All data provided on Yahoo Finance is provided for informational purposes only, and is not intended for trading or investing purposes.

The same page lists third-party providers, e.g. "US equities and global index historical data and daily updates provided by Commodity Systems, Inc." and "International historical chart data and daily updates provided by Morningstar".

Yahoo Terms of Service, Section 2 (Using the Services), Member conduct:

> access or collect data, or attempt to access or collect data, from our Services using any automated means, devices, programs, algorithms or methodologies, including but not limited to robots, spiders, scrapers, data mining tools, or data gathering or extraction tools, for any purpose without our express, prior permission.

> use any material or content from, including without limitation any data, (a) to create any database, archive, mobile application, data feed, widget or any other aggregated data source that competes with or constitutes a material substitute for the Services, in whole or in part, offered on any of our Services or the services offered by our data providers

Section 2, Ownership and Reuse:

> Unless you have explicit written permission, you must not reproduce, modify, rent, lease, sell, trade, distribute, transmit, broadcast, publicly perform, create derivative works based on, or exploit for any commercial purposes, any portion or use of, or access to, the Services (including content, advertisements, APIs, and software).

yfinance README:

> You should refer to Yahoo!'s terms of use ... for details on your rights to use the actual data downloaded.
> Remember - the Yahoo! finance API is intended for personal use only.

Assessment: raw Yahoo prices cannot be redistributed. Our scripts call query1.finance.yahoo.com directly with a script, which is itself "automated means" without permission. Publishing conclusions (e.g. a benchmark score that used a Yahoo-derived baseline) does not redistribute the data, but the ToS "create derivative works" language makes this unclear rather than clearly allowed.

## ECMWF open data

Pages read: https://www.ecmwf.int/en/forecasts/datasets/open-data and https://apps.ecmwf.int/datasets/licences/general/ (linked from the open data page as "ECMWF Terms of Use" and "appropriate attribution")

Open data page:

> A subset of ECMWF real-time forecast data from the IFS and AIFS models is made available to the public free of charge. Their use is governed by the Creative Commons CC-BY-4.0 licence and the ECMWF Terms of Use. This means that the data may be redistributed and used commercially, subject to appropriate attribution.

Terms of Use (https://apps.ecmwf.int/datasets/licences/general/):

> ECMWF retains all Intellectual Property Rights and copyright over its data.

> ECMWF must be acknowledged (attributed) as the source. Attribution must be displayed prominently and include 'this document/data/output/Results is/are based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)'. Users must remove attribution if requested by ECMWF.

> The following wording shall be attached to the use of this ECMWF data product:
> Copyright statement: Copyright "© [year] European Centre for Medium-Range Weather Forecasts (ECMWF)".
> Source www.ecmwf.int
> Licence Statement: This data is published under a Creative Commons Attribution 4.0 International (CC BY 4.0). https://creativecommons.org/licenses/by/4.0/
> Disclaimer: ECMWF does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use.
> Where applicable, an indication of whether the material has been modified and an indication of previous modifications.

> The following wording shall be attached to the services created with this ECMWF data product:
> Copyright statement: Copyright "This service is based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)".
> Source www.ecmwf.int
> Licence Statement: This ECMWF data is published under a Creative Commons Attribution 4.0 International (CC BY 4.0). https://creativecommons.org/licenses/by/4.0/
> Disclaimer: ECMWF does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use.

The open data page also notes the portal "is currently limited to 500 simultaneous connections" and keeps "the most recent 12 forecast runs" on a rolling basis.

## What our public repos publish today (audit, 2026-10-12)

| Where | What is public | Source and terms | Status |
|---|---|---|---|
| `forward` README, "Data comes from free sources" paragraph | Lists IEM, Open-Meteo, Kalshi and Yahoo with no attribution or licence links | Open-Meteo and ECMWF require attribution | Needs the attribution lines below |
| `forward` branch `ledger` (`ledger/*.json`) | Raw forecast values per station and day for ECMWF AIFS and IFS, GFS, ICON and NBM, fetched from Open-Meteo | Open-Meteo CC BY 4.0; ECMWF CC BY 4.0; DWD (ICON) CC BY; NOAA (GFS, NBM) public domain | Allowed; needs the Open-Meteo and ECMWF attribution in the branch README |
| `forward` `results/*.json`, `results/LEADERBOARD.md`, site results page | Scores and aggregate metrics, including skill against the market at its bid | Kalshi (derived/aggregate: unclear); Yahoo (derived: unclear) | Keep to aggregates; no raw prices |
| `isotherm` branch `shadow-ledger` (`predictions.csv`, `trades.csv`) | Per-market `bid`, `ask`, `p_market`, trade `price` and `volume_at_read` at each decision time | Kalshi raw market data | Resolved 2026-10-12 (isotherm #62): the market columns are now kept only in an encrypted state file (`state.enc`), and the branch history was rewritten without them |
| `isotherm` `results/*.json`, `results/dashboard.html`, physicalreasoning.ai/isotherm | Benchmark metrics, backtests, survey statistics | Kalshi derived/aggregate: unclear | Audit for per-market price series (required change 6) |
| `isotherm` README | Credits "Kalshi public market data; Iowa Environmental Mesonet, Iowa State University" and states "nothing is redistributed" | IEM public domain | Fine for IEM; "nothing is redistributed" is accurate again since isotherm #62 |
| `causal-jepa` | Corpus not committed; results are aggregate | Kalshi derived/aggregate: unclear | No change needed beyond required change 7 |

## Required attribution lines

Use these exactly. Replace [year] with the year the data was retrieved.

Open-Meteo (READMEs, site footer, and next to every chart or table that shows Open-Meteo data):

```markdown
[Weather data by Open-Meteo.com](https://open-meteo.com/), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Values were processed (aggregated, interpolated or modelled) by Physical Reasoning.
```

```html
<a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a> (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>); processed by Physical Reasoning.
```

Open-Meteo citation for papers:

```text
Zippenfenig, P. (2023). Open-Meteo.com Weather API [Computer software]. Zenodo. https://doi.org/10.5281/ZENODO.7970649
```

ECMWF, for published data, figures or results:

```text
This data/output is based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF).
Copyright © [year] European Centre for Medium-Range Weather Forecasts (ECMWF). Source: www.ecmwf.int
Licence: This data is published under a Creative Commons Attribution 4.0 International (CC BY 4.0). https://creativecommons.org/licenses/by/4.0/
Disclaimer: ECMWF does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use.
Modifications: [describe, e.g. "regridded to station locations and calibrated with EMOS"].
```

ECMWF, for a service (site, dashboard, API):

```text
This service is based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF). Source: www.ecmwf.int
Licence: This ECMWF data is published under a Creative Commons Attribution 4.0 International (CC BY 4.0). https://creativecommons.org/licenses/by/4.0/
Disclaimer: ECMWF does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use.
```

Iowa Environmental Mesonet (appreciated, not required):

```text
Weather observations, NWS MOS forecasts and NWS climate reports courtesy of the Iowa Environmental Mesonet of Iowa State University (https://mesonet.agron.iastate.edu/).
```

NOAA / NWS (recommended; required notice only for a copyrighted work consisting predominantly of NWS material):

```text
Contains public-domain data from the NOAA National Weather Service, which is not subject to copyright protection. Not endorsed by or affiliated with NOAA/NWS.
```

Kalshi: no attribution licence exists. A plain factual source statement ("Market data: Kalshi") is not a grant of rights; do not use Kalshi logos or marks.

Yahoo Finance: no attribution licence exists; do not use Yahoo branding or logos.

## Required changes

1. In `forward`: add a "Data and licences" section to README.md (replacing the bare source list) with the Open-Meteo, ECMWF, IEM and NWS lines, and add the Open-Meteo and ECMWF lines to the README on the `ledger` branch. Minimum line: "Weather data by Open-Meteo.com (CC BY 4.0)", linked to https://open-meteo.com/.
2. Add the Open-Meteo attribution (with CC BY 4.0 link and a "processed by" note) to the README of every repo that uses Open-Meteo data and to the physicalreasoning.ai site footer, plus next to any chart or table that displays Open-Meteo-derived values.
3. Add the ECMWF wording above wherever ECMWF forecasts are used, including ECMWF data obtained through Open-Meteo (the CC BY chain carries through). Use the "service" wording on the site and dashboards and the "data/output" wording in READMEs and papers.
4. Add the IEM and NWS lines to READMEs and the site footer. Never present modified NWS values as official NWS products.
5. Do not commit raw Kalshi candles, price histories, trade prints or order-book recordings to any public repo, Hugging Face dataset or Space, Zenodo record, or the website. Keep them in gitignored caches (isotherm already ignores data/ and data_cache/; also check book/, kalshi_survey/ and any results/*.json, results/*.parquet and dashboard HTML that embed per-market price series).
6. Audit what is already public: any committed results, dashboards, blog charts or HF Space files that contain per-market Kalshi prices or order-book data should be reduced to aggregate metrics or removed until permission is obtained. Concretely: isotherm's `shadow-ledger` branch publishes per-market bid, ask, trade price and volume (`predictions.csv`, `trades.csv`); either get Kalshi's written permission or drop the raw quote columns from the public ledger and keep them in a private store, and fix the README's "nothing is redistributed" sentence. Removing data already in git history needs a history rewrite and a force-push, which is the owner's call. Done 2026-10-12: isotherm #62 moved the quotes into encrypted state, and the `shadow-ledger` history was rewritten and force-pushed with the owner's approval.
7. Request written permission from Kalshi (Kalshi Research is the likely contact) covering: storing API data for research, training models on it, publishing derived and aggregate results, and making public statements about Kalshi (Developer Agreement 6.4). Until then, treat publication of Kalshi-derived scores as an accepted risk, keep it to conclusions and aggregate metrics, and never reproduce prices.
8. Open-Meteo free tier is non-commercial and capped (600/min, 5,000/hour, 10,000/day, 300,000/month). Any live trading or commercial use (including real-money Kalshi trading driven by Open-Meteo forecasts) needs a paid Open-Meteo API plan. Add a request budget or caching so research jobs stay under the free limits.
9. Do not redistribute Yahoo Finance prices in repos, datasets or dashboards. Prefer a source with a redistribution licence (e.g. a US government source such as EIA for gasoline, after checking its terms, or a licensed vendor) for anything that must be published, and note in code that Yahoo access is for personal research only.
10. Add a DATA_SOURCES or "Data and licences" section to each repo README listing every source, its licence and these restrictions, and link this file.
11. Re-review these terms at least every six months; the Kalshi Developer Agreement on kalshi.com could not be fetched on 2026-10-12, so confirm its current text manually in a browser.
