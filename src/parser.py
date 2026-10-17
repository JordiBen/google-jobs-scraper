"""Parse the Google Search "Jobs" tab (udm=8) HTML into job rows.

Anchors on stable hooks (data-share-url / htidocid, role/aria attributes, <template> detail pane, data-maindata JSON)
rather than obfuscated class names wherever possible. Works on server HTML (SERP proxy) and on browser page.content().
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit, urlencode, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from .posted import looks_like_posted, posted_at
from .salary import parse_salary

BLOCK_MARKERS = ('/sorry/index', 'unusual traffic from your computer', 'detected unusual traffic')
EMPLOYMENT_WORDS = {
    'Full-time': r'full[-–‑ ]?time|vollzeit|temps plein|tiempo completo|tempo pieno|voltijd|tempo integral|pełny',
    'Part-time': r'part[-–‑ ]?time|teilzeit|temps partiel|medio tiempo|tiempo parcial|part time|deeltijd|meio período',
    'Contractor': r'contractor|contract\b|auftragnehmer|freiberuf|befristet|freelance|contrat|contratista|autonomo|aannemer|prestador',
    'Internship': r'intern|praktikum|stage\b|prácticas|pasant|tirocinio|stage|estágio',
}
REMOTE_RE = re.compile(r'work from home|remote|homeoffice|home office|télétravail|teletrabajo|remoto|thuiswerk|anywhere|zdaln', re.I)
VIA_RE = re.compile(r'^(via|über|vía|par|tramite|via|by|von|bij|de)\s+', re.I)
APPLY_PREFIX_RE = re.compile(r'^(apply directly on|apply on|bewerben (direkt )?(über|bei|auf)|postuler (directement )?sur|'
                             r'solicitar (directamente )?en|postúlate en|candidati (direttamente )?su|solliciteren via|'
                             r'candidatar-se (diretamente )?(em|no|na))\s*', re.I)
SALARY_HINT = re.compile(r'[$€£₹¥₪]|\b(USD|EUR|GBP|CHF|INR|AED|SEK|PLN|CAD|AUD)\b|\d\s*[kK]\b|(a|an|per|pro|par|por|al) (year|hour|month|jahr|stunde|monat|an|heure|mois|año|hora|mes)', re.I)


def norm(s) -> str:
    if isinstance(s, Tag):
        s = text(s)
    return re.sub(r'\s+', ' ', s or '').strip()


def text(el: Tag) -> str:
    """Like get_text(), but also returns strings inside <template> (bs4 hides TemplateString by default)."""
    return ''.join(str(n) for n in el.descendants if isinstance(n, NavigableString)
                   and type(n).__name__ not in ('Comment', 'Script', 'Stylesheet', 'Declaration', 'Doctype'))


def is_blocked(html: str, status: int = 200) -> bool:
    if status in (302, 403, 429, 503):
        return True
    low = html[:400_000].lower()
    if len(html) < 100_000 and any(m in low for m in BLOCK_MARKERS) and 'data-share-url' not in low:
        return True
    # SearchGuard JS challenge: small page that only meta-refreshes to /httpservice/retry/enablejs
    if len(html) < 150_000 and 'enablejs' in low and 'data-share-url' not in low:
        return True
    return False


def has_jobs_ui(html: str) -> bool:
    return 'jobs-detail-viewer' in html or 'data-share-url' in html


def strip_utm(url: str) -> str:
    try:
        p = urlsplit(url)
        q = [(k, v) for k, vs in parse_qs(p.query, keep_blank_values=True).items() for v in vs if not k.startswith('utm_')]
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q, doseq=True), p.fragment))
    except Exception:  # noqa: BLE001
        return url


def _maindata_urls(tpl: Tag) -> list[tuple[str, str]]:
    """[(url, domain)] from the detail pane's data-maindata JSON (jobs_posting_urls_N / jobs_posting_domain_N)."""
    for el in tpl.select('[data-maindata]'):
        raw = el.get('data-maindata') or ''
        if 'jobs_posting_urls' not in raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        pairs: dict[str, str] = {}

        def walk(x):
            if isinstance(x, list):
                if len(x) == 2 and isinstance(x[0], str) and isinstance(x[1], str) and x[0].startswith('jobs_posting_'):
                    pairs[x[0]] = x[1]
                else:
                    for y in x:
                        walk(y)
        walk(data)
        out, i = [], 1
        while f'jobs_posting_urls_{i}' in pairs:
            out.append((pairs[f'jobs_posting_urls_{i}'], pairs.get(f'jobs_posting_domain_{i}', '')))
            i += 1
        return out
    return []


def _text_with_breaks(el: Tag) -> str:
    parts = []
    for node in el.descendants:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif node.name == 'br':
            parts.append('\n')
    txt = ''.join(parts)
    txt = re.sub(r'[ \t\u00a0]+', ' ', txt)
    return re.sub(r'\n\s*\n\s*\n+', '\n\n', '\n'.join(line.strip() for line in txt.split('\n'))).strip()


def _description(tpl: Tag) -> str | None:
    for h in tpl.find_all(['h2', 'h3']):
        box = h.parent
        spans = [s for s in box.find_all('span', recursive=False)
                 if s.get('jsname') != 'pqRzIf' and not s.get('role')]
        if h.name == 'h2' and spans:
            desc = ''.join(_text_with_breaks(s) if s.find('br') else text(s) for s in spans).strip()
            if len(desc) > 30:
                return desc
    return None


def _highlights(tpl: Tag) -> list[dict]:
    out = []
    for h4 in tpl.find_all('h4'):
        ul = h4.find_next_sibling('ul')
        if not ul:
            continue
        items = [norm(li) for li in ul.find_all('li') if 'PsOuW' not in (li.get('class') or [])]
        items = [i for i in items if i]
        if items:
            out.append({'title': norm(h4), 'items': items})
    return out


def _apply_options(tpl: Tag) -> list[dict]:
    anchors = [a for a in tpl.select('[role=list] a[href]') if a.get('title') or text(a).strip()]
    names = [norm(a.get('title') or text(a)) for a in anchors]
    urls = _maindata_urls(tpl)
    out = []
    if urls:
        for i, (u, dom) in enumerate(urls):
            label = names[i] if i < len(names) and len(names) == len(urls) else ''
            pub = APPLY_PREFIX_RE.sub('', label).strip() or dom or urlsplit(u).netloc.removeprefix('www.')
            out.append({'publisher': pub, 'url': strip_utm(u)})
    else:
        for a, n in zip(anchors, names):
            href = a['href']
            if href.startswith('/'):
                href = 'https://www.google.com' + href
            out.append({'publisher': APPLY_PREFIX_RE.sub('', n).strip() or n, 'url': href})
    return out


def _chips(card: Tag) -> tuple[list[tuple[str, str]], list[str]]:
    """Return ([(aria-label or '', text)], benefits) from the summary row under the card title."""
    chips, benefits = [], []
    for span in card.select('span[aria-label]'):
        if span.find_parent(attrs={'role': 'button'}):
            continue
        chips.append((span['aria-label'], norm(span)))
    labelled = {t for _, t in chips}
    # Unlabelled chips (often posted age / benefits) sit as sibling divs with an icon + span.
    row = None
    if chips:
        first = card.select_one('span[aria-label]')
        row = first.find_parent('div').find_parent('div') if first and first.find_parent('div') else None
    if row is not None:
        for d in row.find_all('div', recursive=False):
            t = norm(d)
            if t and t not in labelled:
                chips.append(('', t))
    else:
        for d in card.select('div > span + span'):
            t = norm(d)
            if t and t not in labelled:
                chips.append(('', t))
    return chips, benefits


def parse_jobs(html: str, *, query: str = '', search_location: str = '', country: str = 'us', scraped_at=None,
               fetch_path: str = 'serp-proxy') -> list[dict]:
    soup = BeautifulSoup(html, 'lxml')
    rows, seen = [], set()
    now_iso = scraped_at.isoformat(timespec='seconds').replace('+00:00', 'Z') if scraped_at else None
    for card in soup.select('div[data-share-url]'):
        share = card['data-share-url']
        m = re.search(r'htidocid=([^&#]+)', share)
        tpl = card.find('template') or card
        head = card.select_one('[role=button] > div') and card.select_one('[role=button]')
        lines = [norm(d) for d in head.find_all('div', recursive=False)] if head else []
        title = lines[0] if lines else ''
        if not title:
            h = tpl.select_one('[role=heading]')
            title = norm(h) if h else ''
        company = lines[1] if len(lines) > 1 else None
        loc_line = lines[2] if len(lines) > 2 else ''
        location, via = loc_line, None
        if '•' in loc_line:
            location, via = [norm(x) for x in loc_line.split('•', 1)]
            via = VIA_RE.sub('', via) or None
        if not title:
            continue
        job_id = unquote(m.group(1)) if m else hashlib.sha1(f'{title}|{company}|{location}'.encode()).hexdigest()
        if job_id in seen:
            continue
        seen.add(job_id)
        chips, _ = _chips(card)
        salary_text = posted_text = emp = None
        qualifications, benefits = [], []
        for label, text in chips:
            lab = label.lower()
            if not text:
                continue
            if not posted_text and (lab.startswith(('posted', 'gepostet', 'publié', 'publicado', 'pubblicato', 'geplaatst')) or looks_like_posted(text)):
                posted_text = text
            elif not salary_text and (lab.startswith(('salary', 'gehalt', 'salaire', 'salario', 'stipendio', 'salaris', 'salário')) or
                                      (re.search(r'\d', text) and SALARY_HINT.search(text))):
                salary_text = text
            elif not emp and (lab.startswith(('employment', 'beschäftigung', 'type de poste', 'tipo de empleo', 'tipo di impiego', 'dienstverband'))
                              or any(re.search(p, text, re.I) for p in EMPLOYMENT_WORDS.values())):
                emp = text
            elif lab.startswith(('qualification', 'qualifikation')):
                qualifications.append(text)
            elif not REMOTE_RE.search(text):
                benefits.append(text)
        emp_norm = None
        if emp:
            for k, p in EMPLOYMENT_WORDS.items():
                if re.search(p, emp, re.I):
                    emp_norm = k
                    break
        if re.search(r'\b(intern|internship|praktikum|praktikant(in)?|stagiaire|becario|tirocinante|stagiair)\b', title, re.I):
            emp_norm = 'Internship'  # Google often labels internships "Full-time"; its own label stays in employmentTypeText
        is_remote = bool(REMOTE_RE.search(' '.join(t for _, t in chips) + ' ' + location)) or bool(REMOTE_RE.search(title))
        row = {
            'jobId': job_id,
            'query': query, 'searchLocation': search_location or None, 'countryCode': country,
            'position': len(rows) + 1,
            'title': title, 'companyName': company, 'companyLogoUrl': None,
            'location': location or None, 'isRemote': is_remote, 'via': via,
            'postedAtText': posted_text, 'postedAt': posted_at(posted_text, scraped_at),
            'employmentType': emp_norm or emp, 'employmentTypeText': emp,
            'salaryText': salary_text, **parse_salary(salary_text, country),
            'qualificationsSummary': qualifications, 'benefitsSummary': benefits,
            'description': _description(tpl) if tpl is not card else None,
            'highlights': _highlights(tpl) if tpl is not card else [],
            'applyOptions': _apply_options(tpl) if tpl is not card else [],
            'shareUrl': share.replace('&amp;', '&'),
            'scrapedAt': now_iso,
            'fetchPath': fetch_path,
        }
        rows.append(row)
    return rows


def no_results(html: str) -> bool:
    """Google answered normally but has no jobs for this search."""
    return not has_jobs_ui(html) and not is_blocked(html) and len(html) > 100_000
