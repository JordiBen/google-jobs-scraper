"""Path B: headless Chromium + Apify RESIDENTIAL proxy. Loads the Jobs tab and scrolls the infinite list for depth."""
from __future__ import annotations

import asyncio
import os
import random
from urllib.parse import urlsplit

from apify import Actor

BLOCK_TYPES = {'image', 'media', 'font'}
THIRD_PARTY_OK = ('google.', 'gstatic.com', 'googleapis.com')


class BrowserPath:
    def __init__(self, country: str, lang: str):
        self.country, self.lang = country, lang
        self._pw = self._browser = None
        self.bytes_in = 0
        self.pages = 0

    async def start(self):
        from playwright.async_api import async_playwright  # imported lazily: only the browser path needs it
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=os.environ.get('BROWSER_HEADLESS', '0') == '1', proxy={'server': 'per-context'},
                                                        args=['--disable-blink-features=AutomationControlled'])

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def search(self, url: str, max_jobs: int, session: str) -> tuple[int, str, str]:
        """Return (status, final_url, html) after scrolling until max_jobs cards or the list stops growing."""
        pc = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'], country_code=self.country.upper())
        p = urlsplit(await pc.new_url(session_id=session))
        ctx = await self._browser.new_context(
            proxy={'server': f'http://{p.hostname}:{p.port}', 'username': p.username, 'password': p.password},
            locale=self.lang if '-' in self.lang else f'{self.lang}-{self.country.upper()}',
            viewport={'width': 1366, 'height': 900},
            user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/140.0.0.0 Safari/537.36'))
        page = await ctx.new_page()

        async def route(r):
            req = r.request
            host = urlsplit(req.url).hostname or ''
            if req.resource_type in BLOCK_TYPES or not any(h in host for h in THIRD_PARTY_OK):
                await r.abort()
            else:
                await r.continue_()

        def on_response(resp):
            try:
                self.bytes_in += int(resp.headers.get('content-length') or 0)
            except ValueError:
                pass
        await page.route('**/*', route)
        page.on('response', on_response)
        try:
            resp = await page.goto(url.replace('http://', 'https://', 1), wait_until='domcontentloaded', timeout=60_000)
            status = resp.status if resp else 0
            self.pages += 1
            if 'consent.google' in page.url:
                for sel in ('button:has-text("Reject all")', 'form[action*="consent"] button', 'button[aria-label*="Reject"]'):
                    try:
                        await page.locator(sel).first.click(timeout=4000)
                        await page.wait_for_load_state('domcontentloaded')
                        break
                    except Exception:  # noqa: BLE001
                        continue
            if '/sorry/' in page.url:
                return 429, page.url, await page.content()
            try:
                await page.wait_for_selector('div[data-share-url]', timeout=15_000)
            except Exception:  # noqa: BLE001
                return status, page.url, await page.content()
            cards, stale = 0, 0
            while True:
                cards = await page.locator('div[data-share-url]').count()
                if cards >= max_jobs or stale >= 3:
                    break
                await page.locator('div[data-share-url]').last.scroll_into_view_if_needed()
                await page.mouse.wheel(0, 2500)
                try:
                    await page.wait_for_function(f"document.querySelectorAll('div[data-share-url]').length > {cards}",
                                                 timeout=6000)
                    stale = 0
                except Exception:  # noqa: BLE001
                    stale += 1
                await asyncio.sleep(random.uniform(0.3, 0.8))
            return status, page.url, await page.content()
        finally:
            await ctx.close()
