import datetime
import os
import sys

import pytest
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import today  # noqa: E402

BIRTHDAY = datetime.datetime(2001, 9, 11)


# ---------- uptime ----------

def test_uptime_plural_units():
    assert today.uptime(BIRTHDAY, datetime.datetime(2026, 9, 16)) == '25 years, 0 months, 5 days'


def test_uptime_singular_units():
    assert today.uptime(BIRTHDAY, datetime.datetime(2002, 10, 12)) == '1 year, 1 month, 1 day'


def test_uptime_birthday_cake():
    assert today.uptime(BIRTHDAY, datetime.datetime(2026, 9, 11)) == '25 years, 0 months, 0 days 🎂'


# ---------- svg ----------

@pytest.mark.parametrize('just_len, expected', [
    (0, ''), (1, ' '), (2, '. '), (3, ' ... '), (8, ' ........ '),
])
def test_leader(just_len, expected):
    assert today.leader(just_len) == expected


def test_format_value():
    assert today.format_value(1234567) == '1,234,567'
    assert today.format_value('25 years, 0 months, 5 days') == '25 years, 0 months, 5 days'


SVG = '''<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg"><text>
<tspan id="star_data_dots"> ... </tspan><tspan id="star_data">0</tspan>
<tspan id="loc_add">0</tspan></text></svg>'''


def test_update_svg_sets_values_and_leaders(tmp_path):
    path = tmp_path / 'card.svg'
    path.write_text(SVG, encoding='utf-8')
    today.update_svg(str(path), {'star_data': (1234, 13), 'loc_add': (5, 0)})
    root = etree.parse(str(path)).getroot()
    assert root.find(".//*[@id='star_data']").text == '1,234'
    assert root.find(".//*[@id='star_data_dots']").text == ' ........ '   # 13 - len('1,234') = 8 dots
    assert root.find(".//*[@id='loc_add']").text == '5'


# ---------- cache ----------

def repo(name, commits):
    return {
        'nameWithOwner': name,
        'stargazers': {'totalCount': 0},
        'defaultBranchRef': {'target': {'history': {'totalCount': commits}}} if commits else None,
    }


class FakeApi:
    def __init__(self, histories):
        self.histories = histories   # {'owner/name': [(author_id, additions, deletions), ...]}
        self.scanned = []

    def commit_history(self, owner, name, author_id):
        self.scanned.append(f'{owner}/{name}')
        assert author_id == 'ME'
        yield from self.histories[f'{owner}/{name}']


def test_cache_scans_new_repos_and_counts_only_my_commits(tmp_path):
    api = FakeApi({'me/a': [('ME', 10, 2), ('OTHER', 100, 100), ('ME', 5, 1)]})
    path = str(tmp_path / 'cache.txt')
    entries = today.update_loc_cache(api, 'ME', [repo('me/a', 3)], path)
    assert today.loc_totals(entries) == (15, 3, 12, 2)
    assert today.read_cache(path) == entries


def test_cache_skips_unchanged_repos(tmp_path):
    api = FakeApi({'me/a': [('ME', 10, 2)]})
    path = str(tmp_path / 'cache.txt')
    today.update_loc_cache(api, 'ME', [repo('me/a', 1)], path)
    today.update_loc_cache(api, 'ME', [repo('me/a', 1)], path)
    assert api.scanned == ['me/a']


def test_cache_rescans_when_commit_count_changes(tmp_path):
    api = FakeApi({'me/a': [('ME', 10, 2)]})
    path = str(tmp_path / 'cache.txt')
    today.update_loc_cache(api, 'ME', [repo('me/a', 1)], path)
    api.histories['me/a'].append(('ME', 1, 1))
    entries = today.update_loc_cache(api, 'ME', [repo('me/a', 2)], path)
    assert api.scanned == ['me/a', 'me/a']
    assert today.loc_totals(entries) == (11, 3, 8, 2)


def test_cache_keeps_known_entries_when_repos_are_added_or_reordered(tmp_path):
    api = FakeApi({'me/a': [('ME', 1, 0)], 'me/b': [('ME', 2, 0)]})
    path = str(tmp_path / 'cache.txt')
    today.update_loc_cache(api, 'ME', [repo('me/a', 1)], path)
    entries = today.update_loc_cache(api, 'ME', [repo('me/b', 1), repo('me/a', 1)], path)
    assert api.scanned == ['me/a', 'me/b']
    assert [e.repo_hash for e in entries] == [today.repo_hash('me/b'), today.repo_hash('me/a')]


def test_empty_repo_is_cached_as_zeros_without_scanning(tmp_path):
    api = FakeApi({})
    entries = today.update_loc_cache(api, 'ME', [repo('me/empty', 0)], str(tmp_path / 'c.txt'))
    assert entries == [today.CacheEntry(today.repo_hash('me/empty'), 0, 0, 0, 0)]
    assert api.scanned == []


def test_read_cache_ignores_comments_and_missing_file(tmp_path):
    path = tmp_path / 'c.txt'
    assert today.read_cache(str(path)) == []
    path.write_text('# comment\n\n' + 'a' * 64 + ' 3 2 10 4\n', encoding='utf-8')
    assert today.read_cache(str(path)) == [today.CacheEntry('a' * 64, 3, 2, 10, 4)]
