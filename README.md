# Google Jobs Scraper: Job Listings, Salaries, Descriptions & Apply Links

[![Run on Apify](https://img.shields.io/badge/Run%20on-Apify-1f6feb?logo=apify)](https://apify.com/manageable_gully/google-jobs-scraper) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Run it in the cloud with no setup:** [Google Jobs Scraper: Job Listings, Salaries & Apply Links on the Apify Store](https://apify.com/manageable_gully/google-jobs-scraper).  
> Pay only per result, export to JSON/CSV/Excel, schedule runs and call it from the API.
<!-- AFFILIATE_LINK_PLACEHOLDER: replace the Apify links above with the affiliate link when available -->

Scrape **Google for Jobs** (the "Jobs" tab of Google Search) by keyword and location. Every row comes with the **job title, company, location, parsed salary (min/max/currency/period), employment type, posting age, full description, job highlights and every apply link** (LinkedIn, Indeed, company careers pages, and others). Price: **$3 per 1,000 jobs**.

## What you can use it for
- Job boards and aggregators: fresh listings with apply links.
- Recruitment agencies: see who is hiring for which roles, where.
- Salary benchmarking: parsed salary ranges by role, city and country.
- Labour-market research: demand by title, location and employment type.
- Job alerts to Slack, Telegram or email: schedule daily with **Only new jobs** turned on.

## How to use it
1. Type your searches under **Search queries**, e.g. `data engineer`, and an optional **Location**.
2. Pick the Google **country** and filters (date posted, job type, remote).
3. Click **Start**. Each query returns up to your `maxJobsPerQuery`.
4. Export to CSV/Excel, or schedule daily with **Only new jobs** for alerts.

## What it does
- Searches Google Jobs for each of your queries, optionally in a location ("data engineer" + "London, UK").
- Returns structured JSON, CSV or Excel rows: one row per job.
- Includes the job **description and highlights** (Qualifications / Responsibilities / Benefits) and **all apply options** with direct URLs. Google ships them with the listing, so they cost nothing extra.
- **Salary parsing**: "$120K–$150K a year", "£18.50 an hour", "42.300 € bis 75.000 € pro Jahr", "₹12L–18L a year" become `salaryMin`, `salaryMax`, `salaryCurrency` and `salaryPeriod`.
- **Only new jobs since last run**: daily job alerts that never send the same job twice, and you don't pay for repeats.
- 20 Google countries, plus filters for date posted, employment type and remote.

## Why this one
- Low per-job price with no per-page or per-query surprises: you pay for job rows, not for searches.
- Built for reliability. It uses Apify's Google SERP proxy, retries and validates every response, and fails loudly (instead of charging you for empty rows) if Google ever changes its page.
- Filters are enforced, not just suggested. If you ask for internships or remote jobs, rows that don't match are dropped for free.
- Clean, flat output that is ready for spreadsheets, databases, n8n, Make or Zapier.

## Input examples
One search:
```json
{ "queries": ["software engineer"], "location": "New York, NY", "maxJobsPerQuery": 50 }
```
Many roles × cities (one query per combination):
```json
{ "queries": ["nurse Chicago, IL", "nurse Houston, TX", "data analyst Chicago, IL", "data analyst Houston, TX"], "maxJobsPerQuery": 30 }
```
Daily alert, only jobs you haven't seen yet:
```json
{ "queries": ["react developer"], "location": "Remote", "datePosted": "today", "onlyNewSinceLastRun": true, "dedupeKey": "react-alert" }
```
Germany, in German:
```json
{ "queries": ["Softwareentwickler"], "location": "Berlin", "countryCode": "de", "languageCode": "de" }
```

## Output
| Field | Description |
|---|---|
| `jobId` | Google's job id (stable across runs) |
| `query`, `searchLocation`, `countryCode`, `position` | Your search and the job's rank in it |
| `title`, `companyName`, `location`, `via` | As shown by Google (`via` = the source board, e.g. LinkedIn) |
| `isRemote` | Remote / work from home |
| `postedAtText`, `postedAt` | "3 days ago", plus an approximate ISO date |
| `employmentType`, `employmentTypeText` | Normalized (Full-time / Part-time / Contractor / Internship) and Google's own label |
| `salaryText`, `salaryMin`, `salaryMax`, `salaryCurrency`, `salaryPeriod` | Raw and parsed salary |
| `qualificationsSummary`, `benefitsSummary` | Short chips such as "No degree mentioned" or "Health insurance" |
| `description` | Job description text (in some countries Google only provides a preview) |
| `highlights` | `[{title, items[]}]`: Qualifications, Responsibilities, Benefits |
| `applyOptions` | `[{publisher, url}]`: every apply link, tracking parameters removed |
| `shareUrl` | Google Jobs link to this job |
| `scrapedAt`, `fetchPath` | Timestamp and diagnostics |

```json
{
  "jobId": "22jWL_JNHtSxAieXAAAAAA==",
  "query": "software engineer", "searchLocation": "New York, NY", "countryCode": "us", "position": 7,
  "title": "Software Engineer, Full Stack", "companyName": "Plaid", "location": "New York, NY", "via": "Plaid",
  "isRemote": false, "postedAtText": null, "postedAt": null,
  "employmentType": "Full-time", "employmentTypeText": "Full-time",
  "salaryText": "176K–227K a year", "salaryMin": 176000, "salaryMax": 227000, "salaryCurrency": "USD", "salaryPeriod": "YEAR",
  "qualificationsSummary": ["No degree mentioned"], "benefitsSummary": ["Health insurance", "Dental insurance"],
  "description": "We believe that the way people interact with their finances will drastically improve ...",
  "highlights": [{"title": "Qualifications", "items": ["2-4 years of experience in full-stack development", "..."]}],
  "applyOptions": [{"publisher": "Plaid", "url": "https://plaid.com/careers/openings/engineering/new-york-city-office/software-engineer-full-stack/"},
                   {"publisher": "LinkedIn", "url": "https://www.linkedin.com/jobs/view/..."}],
  "shareUrl": "https://www.google.com/search?ibp=htl;jobs&q=software+engineer+New+York&htidocid=...",
  "scrapedAt": "2026-10-17T07:47:10Z", "fetchPath": "serp-proxy"
}
```

## How deep does it go?
Google shows 10 jobs per search. To go further, the Actor runs refined versions of your search, the same refinements Google offers as filter chips (posted since yesterday / last 3 days / last week, full time, part time, internship, remote, seniority), and removes duplicates. Broad searches typically reach **50–150 unique jobs per query**. Narrow searches return fewer. Use more specific queries, or several cities, for bigger datasets.

## Changelog
- 1.0 (2026-10): first release. Google SERP proxy path with refined-search depth, salary/date parsing, enforced filters, only-new mode, layout-drift guard.

## Pricing
Pay per event, no monthly rent: **$0.003 per job** (**$3.00 per 1,000**), plus $0.005 per run start.

| Example | Cost |
|---|---|
| 100 jobs | $0.305 |
| 1,000 jobs | $3.00 |
| 10,000 jobs | $30.00 |
| Daily job alert, about 30 new jobs a day, for 30 days | $2.85 |

You can set a **maximum cost per run** in the run options; the Actor stops cleanly when it is reached. New to Apify? The free plan includes $5 of platform credit every month, so you can try this Actor at no cost.

## API, integrations and AI agents (MCP)
Run it from your own code with the [Apify API](https://docs.apify.com/api/v2) and get the results in one call:
```bash
curl -X POST "https://api.apify.com/v2/acts/manageable_gully~google-jobs-scraper/run-sync-get-dataset-items?token=<YOUR_APIFY_TOKEN>" \
  -H "Content-Type: application/json" -d @input.json
```
```python
from apify_client import ApifyClient
run = ApifyClient("<YOUR_APIFY_TOKEN>").actor("manageable_gully/google-jobs-scraper").call(run_input={...})
```
- **No-code:** use the Apify app in **n8n, Make or Zapier** ("Run Actor", then "Get dataset items"), or send results to Google Sheets, Slack or a webhook.
- **AI agents (MCP):** add `https://mcp.apify.com?tools=manageable_gully/google-jobs-scraper` to Claude, Cursor, VS Code or any MCP client and the agent can call this Actor as a tool.
- **Schedules:** run it hourly, daily or weekly from Apify Console.

## FAQ
**Does it cover LinkedIn and Indeed jobs?** Google for Jobs aggregates listings from LinkedIn, Indeed, Glassdoor, ZipRecruiter, company career pages and many job boards. You get those listings and their apply links through Google, without scraping LinkedIn or Indeed directly.

**Is it legal?** The Actor reads publicly visible Google Jobs listings without logging in and returns factual job data. Google's Terms of Service restrict automated access, and job descriptions are written by employers and job boards, who may hold copyright. Use the data in line with those terms and the original publishers' rights, and check with a lawyer for your use case. Listings can occasionally mention a recruiter's name. If you store personal data, you are responsible for having a lawful basis (e.g. under GDPR). This is not legal advice.

**Does it scrape LinkedIn or Indeed?** No. It only reads Google's Jobs results and returns the apply links that Google lists.

**Why is the location sometimes broader than my search?** Google mixes in remote ("Anywhere") and nearby jobs. Filter on `location` or `isRemote` if you need strict matching.

**How far back do postings go?** Google Jobs mostly shows postings from the last ~30 days.

**Why did a query return fewer jobs than my maximum?** Google had no more distinct jobs for that search and its refinements. The run log says when results were exhausted.

**Logos?** Company logos are not downloaded or redistributed.

**Can AI agents use it?** Yes. It is available as a tool through the Apify MCP server (`https://mcp.apify.com?tools=manageable_gully/google-jobs-scraper`) and the Apify API, and it returns structured JSON that agents can read directly.

## More tools from WebIntel Tools
- [Product Hunt Scraper](https://apify.com/manageable_gully/product-hunt-scraper): daily, weekly and monthly Product Hunt launches with websites
- [Website Tech Stack Detector](https://apify.com/manageable_gully/website-tech-detector): BuiltWith/Wappalyzer-style tech stack lookup in bulk
- [RSS Feed Reader & Monitor](https://apify.com/manageable_gully/rss-feed-reader): read and monitor RSS, Atom and JSON feeds, only new items

See [all WebIntel Tools Actors](https://apify.com/manageable_gully).

*Made by WebIntel Tools. This Actor was built and is maintained with AI assistance. Report issues on the Issues tab; they are monitored daily.*

## Run from source
This repository is the full source of the [Google Jobs Scraper: Job Listings, Salaries & Apply Links](https://apify.com/manageable_gully/google-jobs-scraper) Actor.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest
# run locally with the Apify CLI (https://docs.apify.com/cli):
apify run --input '{...}'
```

Deploy your own copy with `apify push`. The easiest way to use it is the hosted version on the [Apify Store](https://apify.com/manageable_gully/google-jobs-scraper).

<!-- AFFILIATE_LINK_PLACEHOLDER: "New to Apify? Sign up here" link goes here -->

## License
MIT, see [LICENSE](LICENSE).
