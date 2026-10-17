"""Google Jobs Scraper: Google for Jobs listings (Search 'Jobs' tab) by query + location.

Path A (default): plain HTTP through Apify's GOOGLE_SERP proxy. Google returns 10 jobs per search with full details
inline; deeper results come from refined searches (date windows, job types, seniority) that are de-duplicated.
Path B (fallback / deep mode): headless Chromium on RESIDENTIAL proxy, scrolling the infinite job list.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import random
import time

import httpx
from apify import Actor

from .google import base_terms, search_url, variants
from .parser import has_jobs_ui, is_blocked, no_results, parse_jobs

JOB_EVENT = 'job'
DEDUPE_STORE = 'google-jobs-scraper-dedupe'
MAX_SEEN = 100_000
COUNTRIES = {'us', 'gb', 'ca', 'au', 'de', 'fr', 'es', 'it', 'nl', 'pt', 'ie', 'in', 'sg', 'ae', 'il', 'br', 'mx', 'pl', 'se', 'ch'}
EMPLOYMENT = {'FULLTIME', 'PARTTIME', 'CONTRACTOR', 'INTERN'}
SERP_COST, RESI_COST_GB = 0.0025, 8.0
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/140.0.0.0 Safari/537.36')


class InputError(ValueError):
    pass


def parse_input(inp: dict) -> dict:
    qs, seen = [], set()
    for q in inp.get('queries') or []:
        q = ' '.join(str(q or '').split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            qs.append(q[:200])
    if not qs:
        raise InputError('Add at least one search query in "queries", e.g. "software engineer".')
    cc = str(inp.get('countryCode') or 'us').lower()
    if cc not in COUNTRIES:
        raise InputError(f'Unsupported countryCode "{cc}".')
    lang = str(inp.get('languageCode') or 'en')
    if not (len(lang) == 2 or (len(lang) == 5 and lang[2] == '-')) or not lang[:2].isalpha():
        raise InputError('languageCode must look like "en" or "en-GB".')
    emp = [e for e in (inp.get('employmentType') or []) if e in EMPLOYMENT]
    date = inp.get('datePosted') or 'any'
    if date not in ('any', 'today', '3days', 'week', 'month'):
        raise InputError('datePosted must be one of any, today, 3days, week, month.')
    path = str(inp.get('_fetchPath') or os.environ.get('FETCH_PATH') or 'auto').lower()
    return {
        'queries': qs, 'location': ' '.join(str(inp.get('location') or '').split())[:120], 'country': cc, 'lang': lang,
        'date': date, 'employment': emp, 'remote': bool(inp.get('remoteOnly', False)),
        'maxPerQuery': int(min(max(int(inp.get('maxJobsPerQuery') or 50), 1), 500)),
        'maxTotal': int(min(max(int(inp.get('maxJobsTotal') or 0), 0), 100_000)),
        'details': bool(inp.get('includeFullDescription', True)),
        'onlyNew': bool(inp.get('onlyNewSinceLastRun', False)),
        'dedupeKey': str(inp.get('dedupeKey') or 'default')[:40],
        'concurrency': int(min(max(int(inp.get('maxConcurrency') or 10), 1), 20)),
        'path': path if path in ('auto', 'serp', 'browser') else 'auto',
        'debug': bool(inp.get('_debugSamples', False)),
    }


def short_id(job_id: str) -> str:
    return hashlib.sha1(job_id.encode()).hexdigest()[:16]


class Run:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.stop = asyncio.Event()
        self.sem = asyncio.Semaphore(cfg['concurrency'])
        self.stats = {'serpRequests': 0, 'serpBlocked': 0, 'serpErrors': 0, 'browserPages': 0, 'browserBlocked': 0,
                      'pagesWithJobs': 0, 'pagesEmpty': 0, 'pagesNoResults': 0, 'pagesDrift': 0, 'jobs': 0,
                      'skippedSeen': 0, 'filteredOut': 0, 'pagesNoJobsUiRetried': 0, 'queriesWithJobs': 0, 'queriesFailed': 0, 'pathSwitch': None}
        self.seen: set[str] = set()
        self.new_seen: list[str] = []
        self.consecutive_blocked = 0
        self.browser = None
        self.browser_lock = asyncio.Lock()
        self.browser_sem = asyncio.Semaphore(max(1, int(os.environ.get('ACTOR_MEMORY_MBYTES', '1024')) // 1024))
        self.path = 'browser' if cfg['path'] == 'browser' else 'serp'
        self.browser_ok = 0
        self.t0 = time.time()

    # ---------- fetching ----------
    async def serp_fetch(self, url: str) -> tuple[str, str | None]:
        """Return (kind, html). kind: ok | noresults | blocked | error."""
        pc = await Actor.create_proxy_configuration(groups=['GOOGLE_SERP'], country_code=self.cfg['country'].upper())
        last = 'error'
        no_ui_retried = False
        for attempt in range(5):
            if self.stop.is_set():
                return 'error', None
            async with self.sem:
                self.stats['serpRequests'] += 1
                try:
                    async with httpx.AsyncClient(proxy=await pc.new_url(), timeout=90, follow_redirects=False, headers={
                            'User-Agent': UA, 'Accept-Language': f"{self.cfg['lang']},en;q=0.8",
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}) as c:
                        r = await c.get(url)
                    html = r.text
                    if is_blocked(html, r.status_code):
                        self.stats['serpBlocked'] += 1
                        last = 'blocked'
                    elif r.status_code != 200:
                        self.stats['serpErrors'] += 1
                        last = 'error'
                    elif has_jobs_ui(html):
                        return 'ok', html
                    elif no_results(html):
                        if self.cfg.get('debug') and not self.stats['pagesNoResults']:
                            await Actor.set_value('DEBUG-noresults', html, content_type='text/html')
                        if not no_ui_retried:
                            # A normal Google page without the Jobs UI is usually a transient degraded answer: retry once.
                            no_ui_retried = True
                            self.stats['pagesNoJobsUiRetried'] += 1
                            continue
                        return 'noresults', html
                    else:
                        last = 'blocked'
                        self.stats['serpBlocked'] += 1
                except (httpx.HTTPError, OSError) as e:
                    self.stats['serpErrors'] += 1
                    last = 'error'
                    Actor.log.debug(f'SERP request error ({type(e).__name__}), retrying')
            await asyncio.sleep(min(2 ** attempt, 20) * random.uniform(0.5, 1.5))
        return last, None

    async def browser_fetch(self, url: str, want: int) -> tuple[str, str | None]:
        async with self.browser_lock:
            if self.browser is None:
                from .browser import BrowserPath
                self.browser = BrowserPath(self.cfg['country'], self.cfg['lang'])
                await self.browser.start()
        for attempt in range(3):
            async with self.browser_sem:
                try:
                    status, final, html = await self.browser.search(url, want, session=f's{random.randint(0, 10**9)}')
                    self.stats['browserPages'] += 1
                    if '/sorry/' in final or is_blocked(html, status) or not has_jobs_ui(html):
                        Actor.log.info(f'Browser page not usable: status={status} url={final[:120]} len={len(html)}')
                    if '/sorry/' in final or is_blocked(html, status):
                        self.stats['browserBlocked'] += 1
                    elif has_jobs_ui(html):
                        self.browser_ok += 1
                        return 'ok', html
                    elif no_results(html):
                        self.browser_ok += 1
                        return 'noresults', html
                    else:
                        self.stats['browserBlocked'] += 1
                except Exception as e:  # noqa: BLE001
                    Actor.log.warning(f'Browser attempt failed: {type(e).__name__}: {str(e)[:200]}')
            await asyncio.sleep(2 + attempt * 3)
        if not self.browser_ok and self.stats['browserBlocked'] >= 3 and self.cfg['path'] == 'auto':
            self.path = 'serp'  # residential browser is CAPTCHA-walled too: stop wasting time on it this run
            self.stats['pathSwitch'] = (self.stats['pathSwitch'] or '') + '; browser blocked as well -> back to serp-proxy'
        return 'blocked', None

    # ---------- per query ----------
    async def run_query(self, q: str, out: asyncio.Queue) -> None:
        cfg = self.cfg
        want = cfg['maxPerQuery']
        got: dict[str, dict] = {}
        rejected: set[str] = set()
        any_ok = False
        blocked = 0
        now = dt.datetime.now(dt.timezone.utc)

        emp_names = {'FULLTIME': 'Full-time', 'PARTTIME': 'Part-time', 'CONTRACTOR': 'Contractor', 'INTERN': 'Internship'}
        want_types = {emp_names[e] for e in cfg['employment']}
        min_date = None
        if cfg['date'] != 'any':
            days = {'today': 1, '3days': 3, 'week': 7, 'month': 31}[cfg['date']]
            min_date = (now - dt.timedelta(days=days + 1)).date().isoformat()

        def matches(r: dict) -> bool:
            # Google treats the refinements as hints; enforce them so users only pay for what they asked for.
            if want_types and r['employmentType'] not in want_types:
                return False
            if cfg['remote'] and not r['isRemote']:
                return False
            if min_date and r['postedAt'] and r['postedAt'] < min_date:
                return False
            return True

        def accept(rows: list[dict], path: str) -> int:
            added = 0
            for r in rows:
                if len(got) >= want:
                    break
                if r['jobId'] in got or r['jobId'] in rejected:
                    continue
                if not matches(r):
                    rejected.add(r['jobId'])
                    self.stats['filteredOut'] += 1
                    continue
                r['fetchPath'] = path
                got[r['jobId']] = r
                added += 1
            return added

        if self.path == 'browser':
            url = search_url(base_terms(q, cfg['location'], cfg['date'], cfg['employment'], cfg['remote'], cfg['lang']), cfg['country'], cfg['lang'], 'https')
            kind, html = await self.browser_fetch(url, want)
            if kind == 'ok':
                any_ok = True
                rows = parse_jobs(html, query=q, search_location=cfg['location'], country=cfg['country'], scraped_at=now, fetch_path='browser')
                self._page_stats(html, rows)
                accept(rows, 'browser')
            elif kind == 'noresults':
                any_ok = True
                self.stats['pagesNoResults'] += 1
        if len(got) < want and not self.stop.is_set():
            vs = variants(q, cfg['location'], cfg['date'], cfg['employment'], cfg['remote'], cfg['lang'])
            if got:
                vs = vs[1:]  # base search already covered by the browser pass
            i, dry = 0, 0
            while i < len(vs) and len(got) < want and not self.stop.is_set():
                remaining = want - len(got)
                wave = min(len(vs) - i, 6, max(1, -(-remaining // 10)) if i == 0 else max(1, -(-remaining // 5)))
                batch = vs[i:i + wave]
                i += wave
                results = await asyncio.gather(*(self.serp_fetch(search_url(v, cfg['country'], cfg['lang'])) for v in batch))
                added_wave = 0
                for kind, html in results:
                    if kind == 'ok':
                        any_ok = True
                        rows = parse_jobs(html, query=q, search_location=cfg['location'], country=cfg['country'], scraped_at=now)
                        self._page_stats(html, rows)
                        added_wave += accept(rows, 'serp-proxy')
                    elif kind == 'noresults':
                        any_ok = True
                        self.stats['pagesNoResults'] += 1
                    else:
                        blocked += 1
                if i == wave and not got and not rejected:
                    break  # the first, most diverse wave found no jobs at all: refinements won't help
                dry = dry + 1 if added_wave == 0 else 0
                if dry >= 2:
                    break
            if len(got) < want and i >= len(vs):
                Actor.log.info(f'"{q}": Google exhausted results at {len(got)} jobs')
        if got:
            self.stats['queriesWithJobs'] += 1
            self.consecutive_blocked = 0
        elif not any_ok and blocked:
            self.stats['queriesFailed'] += 1
            self.consecutive_blocked += 1
            if self.cfg['path'] == 'auto' and self.path == 'serp' and self.consecutive_blocked >= 3:
                self.path = 'browser'
                self.stats['pathSwitch'] = f'serp-proxy -> browser after {self.consecutive_blocked} blocked queries'
                Actor.log.warning(self.stats['pathSwitch'])
        for pos, r in enumerate(got.values(), 1):
            r['position'] = pos
            if not cfg['details']:
                r['description'] = None
                r['highlights'] = []
            await out.put(r)

    def _page_stats(self, html: str, rows: list[dict]) -> None:
        if rows:
            self.stats['pagesWithJobs'] += 1
        elif 'data-share-url' in html:
            self.stats['pagesDrift'] += 1  # job cards present but the parser found nothing -> layout drift
        else:
            self.stats['pagesEmpty'] += 1

    def est_cost(self) -> float:
        resi = (self.browser.bytes_in / 1e9 * RESI_COST_GB) if self.browser else 0.0
        return round(self.stats['serpRequests'] * SERP_COST + resi, 4)


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        try:
            cfg = parse_input(inp)
        except InputError as e:
            await Actor.fail(status_message=str(e))
            return
        run = Run(cfg)
        store = await Actor.open_key_value_store(name=DEDUPE_STORE) if cfg['onlyNew'] else None
        seen_key = f'seen-{cfg["dedupeKey"]}'
        prior: list[str] = (await store.get_value(seen_key) or []) if store else []
        run.seen = set(prior)
        out: asyncio.Queue = asyncio.Queue()
        Actor.log.info(f'{len(cfg["queries"])} quer(y/ies), up to {cfg["maxPerQuery"]} jobs each, country={cfg["country"]}, path={run.path}')

        async def producer():
            qsem = asyncio.Semaphore(max(1, cfg['concurrency'] // 2))

            async def one(q):
                async with qsem:
                    if not run.stop.is_set():
                        await run.run_query(q, out)
            await asyncio.gather(*(one(q) for q in cfg['queries']))
            await out.put(None)

        async def consumer():
            while True:
                r = await out.get()
                if r is None:
                    return
                if run.stop.is_set():
                    continue
                sid = short_id(r['jobId'])
                if cfg['onlyNew'] and sid in run.seen:
                    run.stats['skippedSeen'] += 1
                    continue
                res = await Actor.push_data(r, charged_event_name=JOB_EVENT)
                if res is not None and getattr(res, 'charged_count', 1) == 0 and getattr(res, 'event_charge_limit_reached', False):
                    run.stop.set()
                    continue
                run.stats['jobs'] += 1
                run.seen.add(sid)
                run.new_seen.append(sid)
                if res is not None and getattr(res, 'event_charge_limit_reached', False):
                    run.stop.set()
                if cfg['maxTotal'] and run.stats['jobs'] >= cfg['maxTotal']:
                    run.stop.set()
                if run.stats['jobs'] % 50 == 0:
                    await Actor.set_status_message(f"{run.stats['jobs']} jobs so far")
        try:
            await asyncio.gather(producer(), consumer())
        finally:
            if run.browser:
                await run.browser.close()

        if store and run.new_seen:
            await store.set_value(seen_key, (prior + run.new_seen)[-MAX_SEEN:])
        s = run.stats
        s['estimatedPlatformCostUsd'] = run.est_cost()
        s['runSeconds'] = round(time.time() - run.t0, 1)
        if run.browser:
            s['residentialBytes'] = run.browser.bytes_in
        await Actor.set_value('OUTPUT', {'stats': s, 'input': {k: v for k, v in cfg.items()}})
        Actor.log.info(f'Stats: {s}')

        pages_ok = s['pagesWithJobs'] + s['pagesDrift']
        if pages_ok >= 3 and s['pagesDrift'] / pages_ok >= 0.3:
            await Actor.fail(status_message='Google changed its Jobs page layout; the parser needs an update. '
                                            'You were only charged for jobs actually returned.')
            return
        if s['jobs'] == 0 and s['queriesFailed'] and s['queriesFailed'] == len(cfg['queries']):
            await Actor.fail(status_message='Google blocked every search in this run. Nothing was charged except the run start. Please retry later.')
            return
        msg = f"Done: {s['jobs']} jobs from {len(cfg['queries'])} quer{'y' if len(cfg['queries']) == 1 else 'ies'}"
        if s['skippedSeen']:
            msg += f", {s['skippedSeen']} already seen skipped"
        if s['jobs'] == 0 and not s['skippedSeen']:
            msg += ' (Google has no matching jobs)'
        if run.stop.is_set() and not cfg['maxTotal']:
            msg += ' (stopped: max charge reached)'
        await Actor.set_status_message(msg, is_terminal=True)
