"""Parse Google Jobs salary strings into min / max / currency / period.

Handles k/M suffixes, Indian lakh (L) and crore (Cr), en/de/fr/es/it/nl/pt wording, ranges with -, –, to, bis, à, a.
"""
from __future__ import annotations

import re

CURRENCY_SYMBOLS = [
    ('US$', 'USD'), ('CA$', 'CAD'), ('C$', 'CAD'), ('A$', 'AUD'), ('AU$', 'AUD'), ('NZ$', 'NZD'), ('S$', 'SGD'), ('HK$', 'HKD'),
    ('R$', 'BRL'), ('MX$', 'MXN'), ('CHF', 'CHF'), ('USD', 'USD'), ('EUR', 'EUR'), ('GBP', 'GBP'), ('INR', 'INR'), ('AED', 'AED'),
    ('SEK', 'SEK'), ('PLN', 'PLN'), ('zł', 'PLN'), ('kr', 'SEK'), ('ILS', 'ILS'), ('₪', 'ILS'), ('£', 'GBP'), ('€', 'EUR'),
    ('₹', 'INR'), ('¥', 'JPY'), ('$', None),  # bare $ -> country default
]
COUNTRY_CURRENCY = {'us': 'USD', 'gb': 'GBP', 'ca': 'CAD', 'au': 'AUD', 'de': 'EUR', 'fr': 'EUR', 'es': 'EUR', 'it': 'EUR',
                    'nl': 'EUR', 'pt': 'EUR', 'ie': 'EUR', 'in': 'INR', 'sg': 'SGD', 'ae': 'AED', 'il': 'ILS', 'br': 'BRL',
                    'mx': 'MXN', 'pl': 'PLN', 'se': 'SEK', 'ch': 'CHF'}
PERIODS = [
    ('HOUR', r'hour|\bhrs?\b|hourly|stunde|std\b|heure|hora|ora\b|uur'),
    ('DAY', r'\bday\b|daily|\btag\b|jour|día|dia\b|giorno|\bdag\b'),
    ('WEEK', r'week|woche|semaine|semana|settimana'),
    ('MONTH', r'month|monat|mois|\bmes\b|mese|maand|mês'),
    ('YEAR', r'year|\byr\b|annual|annum|jahr|\ban\b|année|año|anno|jaar|ano\b'),
]
NUM = r'(\d[\d.,\s\u00a0\u202f]*\d|\d)\s*(k|K|M|m(?![a-z])|L|lakhs?|LPA|Cr|crores?)?'


def _to_number(raw: str, suffix: str | None) -> float:
    s = re.sub(r'[\s\u00a0\u202f]', '', raw)
    # Decide decimal vs thousands separators.
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '') if re.search(r',\d{3}$', s) or s.count(',') > 1 else s.replace(',', '.')
    elif '.' in s:
        if re.search(r'\.\d{3}$', s) or s.count('.') > 1:
            s = s.replace('.', '')
    v = float(s)
    sfx = (suffix or '').lower()
    if sfx == 'k':
        v *= 1_000
    elif sfx == 'm':
        v *= 1_000_000
    elif sfx in ('l', 'lakh', 'lakhs', 'lpa'):
        v *= 100_000
    elif sfx.startswith('cr'):
        v *= 10_000_000
    return round(v, 2)


def detect_currency(text: str, country: str | None = None) -> str | None:
    for sym, code in CURRENCY_SYMBOLS:
        if sym in text:
            return code or COUNTRY_CURRENCY.get((country or '').lower(), 'USD')
    return None


def detect_period(text: str) -> str | None:
    t = text.lower()
    for name, pat in PERIODS:
        if re.search(pat, t):
            return name
    return None


def parse_salary(text: str | None, country: str | None = None) -> dict:
    out = {'salaryMin': None, 'salaryMax': None, 'salaryCurrency': None, 'salaryPeriod': None}
    if not text:
        return out
    t = text.strip()
    nums = [(m.group(1), m.group(2), m.start()) for m in re.finditer(NUM, t)]
    if not nums:
        return out
    has_digit_salary = any(re.search(r'\d', n[0]) for n in nums)
    if not has_digit_salary:
        return out
    # Shared suffix for ranges: "120–150K" -> both K
    vals_raw = nums[:2]
    if len(vals_raw) == 2 and vals_raw[1][1] and not vals_raw[0][1]:
        vals_raw = [(vals_raw[0][0], vals_raw[1][1], 0), vals_raw[1]]
    vals = [_to_number(r, s) for r, s, _ in vals_raw]
    lower = t.lower()
    if len(vals) == 1:
        if re.search(r'\b(up to|bis zu|jusqu|hasta|fino a|tot\b|até)', lower):
            out['salaryMax'] = vals[0]
        elif re.search(r'\b(from|ab\b|à partir|desde|da\b|vanaf|a partir)', lower):
            out['salaryMin'] = vals[0]
        else:
            out['salaryMin'] = out['salaryMax'] = vals[0]
    else:
        out['salaryMin'], out['salaryMax'] = min(vals), max(vals)
    out['salaryCurrency'] = detect_currency(t, country) or COUNTRY_CURRENCY.get((country or '').lower())
    out['salaryPeriod'] = detect_period(t)
    return out
