import datetime as dt
import json
import pathlib

import jsonschema
import pytest

from src.google import base_terms, search_url, variants
from src.main import InputError, parse_input
from src.parser import is_blocked, no_results, parse_jobs
from src.posted import posted_at
from src.salary import parse_salary

FIX = pathlib.Path(__file__).parent / 'fixtures'
ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 17, 7, 34, tzinfo=dt.timezone.utc)
needs_fixtures = pytest.mark.skipif(not (FIX / 'us_software_ny.html').exists(),
                                    reason='Google HTML fixtures are not in the public repo (third-party listings); see tests/README')
SCHEMA = json.loads((ROOT / '.actor' / 'dataset_schema.json').read_text())['fields']


def rows(name, country='us'):
    return parse_jobs((FIX / name).read_text(encoding='utf-8'), query='q', search_location='loc', country=country, scraped_at=NOW)


@needs_fixtures
def test_us_fixture_fields_and_schema():
    rs = rows('us_software_ny.html')
    assert len(rs) == 4
    v = jsonschema.Draft7Validator(SCHEMA)
    for r in rs:
        assert not list(v.iter_errors(r)), list(v.iter_errors(r))[:1]
        assert r['title'] and r['companyName'] and r['location'] and r['via']
        assert r['applyOptions'] and all(a['url'].startswith('https://') for a in r['applyOptions'])
        assert all('utm_' not in a['url'] for a in r['applyOptions'])
        assert r['description'] and len(r['description']) > 200
    first = rs[0]
    assert first['jobId'] == 'GrpXVNnt7B67BdI5AAAAAA=='
    assert first['isRemote'] is True and first['employmentType'] == 'Contractor'
    assert first['postedAtText'] == '1 day ago' and first['postedAt'] == '2026-10-16'
    assert [r['position'] for r in rs] == [1, 2, 3, 4]
    assert any(h['title'] == 'Qualifications' for r in rs for h in r['highlights'])


@needs_fixtures
def test_de_fixture_umlauts_and_types():
    rs = rows('de_softwareentwickler_berlin.html', 'de')
    assert len(rs) == 4
    assert all(r['employmentType'] == 'Full-time' for r in rs)
    assert any('ü' in json.dumps(r, ensure_ascii=False) or 'ä' in json.dumps(r, ensure_ascii=False) for r in rs)
    assert rs[0]['postedAtText'] == 'vor 1 Tag' and rs[0]['postedAt'] == '2026-10-16'


SALARY = [
    ('$120K–$150K a year', 'us', 120000, 150000, 'USD', 'YEAR'),
    ('176K–227K a year', 'us', 176000, 227000, 'USD', 'YEAR'),
    ('£18.50 an hour', 'gb', 18.5, 18.5, 'GBP', 'HOUR'),
    ('€4,000 a month', 'ie', 4000, 4000, 'EUR', 'MONTH'),
    ('₹12L–18L a year', 'in', 1200000, 1800000, 'INR', 'YEAR'),
    ('₹2.5L–₹4L a year', 'in', 250000, 400000, 'INR', 'YEAR'),
    ('Up to $90,000', 'us', None, 90000, 'USD', None),
    ('Up to $90,000 a year', 'us', None, 90000, 'USD', 'YEAR'),
    ('From $50K a year', 'us', 50000, None, 'USD', 'YEAR'),
    ('14–20 an hour', 'us', 14, 20, 'USD', 'HOUR'),
    ('15 an hour', 'us', 15, 15, 'USD', 'HOUR'),
    ('£75k a year', 'gb', 75000, 75000, 'GBP', 'YEAR'),
    ('£50k–£60k a year', 'gb', 50000, 60000, 'GBP', 'YEAR'),
    ('42.300 € bis 75.000 € pro Jahr', 'de', 42300, 75000, 'EUR', 'YEAR'),
    ('18–22 € pro Stunde', 'de', 18, 22, 'EUR', 'HOUR'),
    ('3.500 € pro Monat', 'de', 3500, 3500, 'EUR', 'MONTH'),
    ('$1.2M a year', 'us', 1200000, 1200000, 'USD', 'YEAR'),
    ('$25.50–$30 an hour', 'us', 25.5, 30, 'USD', 'HOUR'),
    ('CA$80K–CA$95K a year', 'ca', 80000, 95000, 'CAD', 'YEAR'),
    ('$800 a week', 'us', 800, 800, 'USD', 'WEEK'),
    ('$200 a day', 'us', 200, 200, 'USD', 'DAY'),
]


@pytest.mark.parametrize('text,cc,lo,hi,cur,per', SALARY)
def test_salary(text, cc, lo, hi, cur, per):
    s = parse_salary(text, cc)
    assert (s['salaryMin'], s['salaryMax'], s['salaryCurrency'], s['salaryPeriod']) == (lo, hi, cur, per)


def test_salary_empty():
    assert parse_salary(None)['salaryMin'] is None and parse_salary('Competitive')['salaryMax'] is None


@pytest.mark.parametrize('text,expected', [('20 hours ago', '2026-10-16'), ('3 days ago', '2026-10-14'), ('30+ days ago', '2026-09-17'),
                                           ('vor 20 Stunden', '2026-10-16'), ('vor 4 Tagen', '2026-10-13'), ('Just posted', '2026-10-17'),
                                           ('il y a 2 jours', '2026-10-15'), ('hace 1 semana', '2026-10-10'), ('7 hours ago', '2026-10-17'), (None, None)])
def test_posted(text, expected):
    assert posted_at(text, NOW) == expected


@needs_fixtures
def test_block_detection():
    challenge = ('<html><head><noscript><meta content="0;url=/httpservice/retry/enablejs?sei=x" http-equiv="refresh"></noscript>'
                 '</head><body>' + 'x' * 1000 + '</body></html>')
    sorry = '<html><body>Our systems have detected unusual traffic from your computer network. /sorry/index</body></html>'
    assert is_blocked(challenge) and is_blocked(sorry) and is_blocked('', 429) and is_blocked('', 302)
    assert not is_blocked((FIX / 'us_software_ny.html').read_text(encoding='utf-8'))
    big_empty = '<html><body><div id="search">It looks like there aren\'t many great matches for your search</div>' + ' ' * 150_000 + '</body></html>'
    assert no_results(big_empty) and not is_blocked(big_empty)


@needs_fixtures
def test_drift_fixture_yields_no_rows():
    html = (FIX / 'us_software_ny.html').read_text(encoding='utf-8').replace('role="button"', 'role="x"').replace('data-share-url', 'data-x-url')
    assert parse_jobs(html) == []


def test_variants_and_urls():
    vs = variants('nurse', 'Chicago, IL', 'any', [], False, 'en')
    assert vs[0] == 'nurse Chicago, IL' and len(vs) == len(set(vs)) and len(vs) >= 12
    assert any(v.endswith('since yesterday') for v in vs) and any(v.endswith('internship') for v in vs)
    assert base_terms('nurse', '', 'today', ['INTERN'], True, 'en') == 'nurse remote internship since yesterday'
    assert base_terms('Pflege', 'Berlin', 'week', [], False, 'de') == 'Pflege Berlin in der letzten Woche'
    u = search_url('data engineer London', 'gb', 'en')
    assert u.startswith('http://www.google.co.uk/search?') and 'udm=8' in u and 'gl=uk' in u
    filt = variants('nurse', '', 'today', ['FULLTIME'], True, 'en')
    assert all('since yesterday' in v and 'full time' in v and 'remote' in v for v in filt)


def test_input_validation():
    with pytest.raises(InputError):
        parse_input({'queries': []})
    with pytest.raises(InputError):
        parse_input({'queries': ['a'], 'languageCode': 'english'})
    with pytest.raises(InputError):
        parse_input({'queries': ['a'], 'countryCode': 'xx'})
    c = parse_input({'queries': [' nurse ', 'Nurse', '', 'data  analyst'], 'maxJobsPerQuery': 9999})
    assert c['queries'] == ['nurse', 'data analyst'] and c['maxPerQuery'] == 500 and c['path'] == 'auto'
