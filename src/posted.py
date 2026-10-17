"""Relative posting age ("3 days ago", "vor 20 Stunden", "il y a 2 jours") -> approximate ISO date."""
from __future__ import annotations

import datetime as dt
import re

UNITS = [
    ('minutes', r'min'),
    ('hours', r'hour|hr\b|stunde|heure|hora|\bore?\b|uur|h\b'),
    ('days', r'day|tag|jour|día|dia|giorn|dag'),
    ('weeks', r'week|woche|semaine|semana|settiman'),
    ('months', r'month|monat|mois|mes|mês|maand'),
]
JUST = r'just|today|heute|aujourd|hoy|oggi|vandaag|hoje|gerade'


def posted_at(text: str | None, now: dt.datetime | None = None) -> str | None:
    if not text:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    t = text.lower()
    if re.search(JUST, t):
        return now.date().isoformat()
    m = re.search(r'(\d+)\s*\+?', t)
    if not m:
        return None
    n = int(m.group(1))
    for unit, pat in UNITS:
        if re.search(pat, t):
            if unit == 'months':
                delta = dt.timedelta(days=30 * n)
            elif unit == 'weeks':
                delta = dt.timedelta(weeks=n)
            else:
                delta = dt.timedelta(**{unit: n})
            return (now - delta).date().isoformat()
    return None


def looks_like_posted(text: str) -> bool:
    t = text.lower()
    return bool(re.search(JUST, t) or (re.search(r'\d', t) and re.search(r'ago|vor\b|il y a|hace|fa\b|geleden|há\b|atrás', t)))
