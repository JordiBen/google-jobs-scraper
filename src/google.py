"""Google domains, query building and search-refinement variants for the Jobs tab."""
from __future__ import annotations

from urllib.parse import urlencode

DOMAINS = {'us': 'google.com', 'gb': 'google.co.uk', 'ca': 'google.ca', 'au': 'google.com.au', 'de': 'google.de',
           'fr': 'google.fr', 'es': 'google.es', 'it': 'google.it', 'nl': 'google.nl', 'pt': 'google.pt', 'ie': 'google.ie',
           'in': 'google.co.in', 'sg': 'google.com.sg', 'ae': 'google.ae', 'il': 'google.co.il', 'br': 'google.com.br',
           'mx': 'google.com.mx', 'pl': 'google.pl', 'se': 'google.se', 'ch': 'google.ch'}

# Natural-language refinements Google itself uses for the Jobs filter chips ("Add Yesterday" -> "... since yesterday").
WORDS = {
    'en': {'today': 'since yesterday', '3days': 'in the last 3 days', 'week': 'in the last week', 'month': 'in the last month',
           'FULLTIME': 'full time', 'PARTTIME': 'part time', 'CONTRACTOR': 'contractor', 'INTERN': 'internship',
           'remote': 'remote', 'extra': ['entry level', 'senior', 'no degree', 'hybrid', 'junior', 'lead', 'with benefits', 'immediate start']},
    'de': {'today': 'seit gestern', '3days': 'in den letzten 3 Tagen', 'week': 'in der letzten Woche', 'month': 'im letzten Monat',
           'FULLTIME': 'Vollzeit', 'PARTTIME': 'Teilzeit', 'CONTRACTOR': 'freiberuflich', 'INTERN': 'Praktikum',
           'remote': 'Homeoffice', 'extra': ['Junior', 'Senior', 'Quereinsteiger', 'hybrid']},
    'fr': {'today': "depuis hier", '3days': 'au cours des 3 derniers jours', 'week': 'la semaine dernière', 'month': 'le mois dernier',
           'FULLTIME': 'temps plein', 'PARTTIME': 'temps partiel', 'CONTRACTOR': 'freelance', 'INTERN': 'stage',
           'remote': 'télétravail', 'extra': ['junior', 'senior', 'CDI', 'hybride']},
    'es': {'today': 'desde ayer', '3days': 'en los últimos 3 días', 'week': 'en la última semana', 'month': 'en el último mes',
           'FULLTIME': 'jornada completa', 'PARTTIME': 'media jornada', 'CONTRACTOR': 'autónomo', 'INTERN': 'prácticas',
           'remote': 'teletrabajo', 'extra': ['junior', 'senior', 'sin experiencia', 'híbrido']},
}


def words(lang: str) -> dict:
    return WORDS.get((lang or 'en')[:2].lower(), WORDS['en'])


def base_terms(query: str, location: str, date_posted: str, employment: list[str], remote: bool, lang: str) -> str:
    w = words(lang)
    parts = [query.strip()]
    if location:
        parts.append(location.strip())
    if remote:
        parts.append(w['remote'])
    if len(employment) == 1:
        parts.append(w[employment[0]])
    if date_posted and date_posted != 'any':
        parts.append(w[date_posted])
    return ' '.join(p for p in parts if p)


def variants(query: str, location: str, date_posted: str, employment: list[str], remote: bool, lang: str) -> list[str]:
    """Distinct searches whose union approximates deeper pagination. The first one is the user's exact search."""
    w = words(lang)
    base = base_terms(query, location, date_posted, employment, remote, lang)
    out = [base]
    emp_options = employment if len(employment) > 1 else ([] if employment else ['FULLTIME', 'PARTTIME', 'CONTRACTOR', 'INTERN'])
    date_options = [] if date_posted and date_posted != 'any' else ['today', '3days', 'week', 'month']
    # Interleave so that early variants differ most (date windows first, then job types, then seniority words).
    for d in date_options[:3]:
        out.append(f'{base} {w[d]}')
    for e in emp_options:
        out.append(f'{base} {w[e]}')
    if not remote:
        out.append(f'{base} {w["remote"]}')
    for x in w['extra']:
        out.append(f'{base} {x}')
    for d in date_options[3:]:
        out.append(f'{base} {w[d]}')
    seen, uniq = set(), []
    for v in out:
        if v.lower() not in seen:
            seen.add(v.lower())
            uniq.append(v)
    return uniq


def search_url(terms: str, country: str, lang: str, scheme: str = 'http') -> str:
    gl = 'uk' if country == 'gb' else country
    return f'{scheme}://www.{DOMAINS.get(country, "google.com")}/search?' + urlencode({'q': terms, 'udm': '8', 'hl': lang, 'gl': gl})
