#!/usr/bin/env python3
"""Fill dark_mode.svg and light_mode.svg with live GitHub stats.

Environment:
  ACCESS_TOKEN  fine-grained PAT — all repositories, Contents + Metadata (read),
                account Followers (read)
  USER_NAME     GitHub login to build the card for
"""
import datetime
import hashlib
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass

import requests
from dateutil import relativedelta
from lxml import etree

BIRTHDAY = datetime.datetime(2001, 9, 11)
GRAPHQL_URL = 'https://api.github.com/graphql'
SVG_FILES = ('dark_mode.svg', 'light_mode.svg')
CACHE_DIR = 'cache'
ALL_AFFILIATIONS = ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER']
INFO_WIDTH = 58      # characters per info line in the SVG templates
RULE_COLUMN = 34     # width of the part before ' | ' on the two-value stats lines


# ---------- uptime ----------

def plural(n):
    return '' if n == 1 else 's'


def uptime(birthday, today=None):
    """'X years, X months, X days' since birthday, plus a cake on the birthday itself."""
    today = today or datetime.datetime.today()
    diff = relativedelta.relativedelta(today, birthday)
    cake = ' 🎂' if diff.months == 0 and diff.days == 0 else ''
    return (f'{diff.years} year{plural(diff.years)}, '
            f'{diff.months} month{plural(diff.months)}, '
            f'{diff.days} day{plural(diff.days)}{cake}')


# ---------- svg ----------

def leader(width):
    """Dotted leader of exactly `width` characters: ' ', '  ', ' . ', ' .. ', ..."""
    if width <= 0:
        return ''
    if width <= 2:
        return ' ' * width
    return ' ' + '.' * (width - 2) + ' '


def format_value(value):
    return f'{value:,}' if isinstance(value, int) else str(value)


def justify(root, element_id, value, width=0):
    """Set #element_id's text and resize #element_id_dots so leader + value spans `width`."""
    text = format_value(value)
    _set_text(root, element_id, text)
    _set_text(root, f'{element_id}_dots', leader(max(1, width - len(text)) if width else 0))


def _set_text(root, element_id, text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = text


def update_svg(path, values):
    """values: {element_id: (value, field_width)}"""
    tree = etree.parse(path)
    root = tree.getroot()
    for element_id, (value, width) in values.items():
        justify(root, element_id, value, width)
    tree.write(path, encoding='utf-8', xml_declaration=True)


def field_widths(stats):
    """Width (leader + value) of each dynamic field so every info line is INFO_WIDTH wide.

    The label strings mirror the SVG templates; fields with width 0 have no leader.
    """
    contrib, adds, dels = (format_value(stats[key]) for key in ('contrib_data', 'loc_add', 'loc_del'))
    return {
        'age_data': INFO_WIDTH - len('. Uptime:'),
        'repo_data': RULE_COLUMN - len('. Repos:') - len(' {Contributed: ') - len(contrib) - len('}'),
        'contrib_data': 0,
        'star_data': INFO_WIDTH - RULE_COLUMN - len(' | Stars:'),
        'commit_data': RULE_COLUMN - len('. Commits:'),
        'follower_data': INFO_WIDTH - RULE_COLUMN - len(' | Followers:'),
        'loc_data': INFO_WIDTH - len('. Lines of Code:') - len(f' ( {adds}++, {dels}-- )'),
        'loc_add': 0,
        'loc_del': 0,
    }


def fill(path, stats):
    """Write every stat into the SVG at `path`, keeping the info lines aligned."""
    widths = field_widths(stats)
    update_svg(path, {key: (value, widths[key]) for key, value in stats.items()})


# ---------- lines-of-code cache ----------

CACHE_HEADER = '''\
# Lines-of-code cache written by today.py — one line per repository:
#   sha256(nameWithOwner) total_commits my_commits additions deletions
# A repository is re-scanned only when its total_commits changes.
# Delete this file to force a full re-scan (slow: one API call per 100 commits).
'''


@dataclass
class CacheEntry:
    repo_hash: str
    total_commits: int
    my_commits: int
    additions: int
    deletions: int

    @classmethod
    def parse(cls, line):
        repo_hash, total, mine, adds, dels = line.split()
        return cls(repo_hash, int(total), int(mine), int(adds), int(dels))

    def format(self):
        return f'{self.repo_hash} {self.total_commits} {self.my_commits} {self.additions} {self.deletions}\n'


def repo_hash(name_with_owner):
    return hashlib.sha256(name_with_owner.encode('utf-8')).hexdigest()


def cache_path(user_name):
    return os.path.join(CACHE_DIR, hashlib.sha256(user_name.encode('utf-8')).hexdigest() + '.txt')


def read_cache(path):
    """Entries in the cache file; [] when it does not exist yet."""
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    return [CacheEntry.parse(line) for line in lines if line.strip() and not line.startswith('#')]


def write_cache(path, entries):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(CACHE_HEADER)
        f.writelines(entry.format() for entry in entries)


def commit_total(repo):
    ref = repo['defaultBranchRef']
    return ref['target']['history']['totalCount'] if ref else 0


def update_loc_cache(api, owner_id, repos, path):
    """Bring the cache in line with `repos` and return its entries (same order as `repos`).

    Only repositories whose commit count differs from the cached one are re-scanned,
    fetching just the commits authored by `owner_id`. The file is rewritten after every
    scanned repository so an API failure mid-way keeps the work done so far.
    """
    known = {entry.repo_hash: entry for entry in read_cache(path)}
    entries = [known.get(repo_hash(r['nameWithOwner'])) or CacheEntry(repo_hash(r['nameWithOwner']), 0, 0, 0, 0)
               for r in repos]
    for entry, r in zip(entries, repos):
        total = commit_total(r)
        if total == entry.total_commits:
            continue
        owner, name = r['nameWithOwner'].split('/')
        mine = adds = dels = 0
        for author_id, additions, deletions in api.commit_history(owner, name, owner_id):
            if author_id == owner_id:
                mine, adds, dels = mine + 1, adds + additions, dels + deletions
        entry.total_commits, entry.my_commits, entry.additions, entry.deletions = total, mine, adds, dels
        write_cache(path, entries)
    write_cache(path, entries)
    return entries


def loc_totals(entries):
    """(additions, deletions, net lines, my commits) summed over the cache."""
    adds = sum(e.additions for e in entries)
    dels = sum(e.deletions for e in entries)
    return adds, dels, adds - dels, sum(e.my_commits for e in entries)


# ---------- GitHub GraphQL ----------

class GitHubApi:
    def __init__(self, token, user_name):
        self.headers = {'authorization': 'token ' + token}
        self.user_name = user_name
        self.calls = Counter()

    def query(self, name, query, variables=None):
        self.calls[name] += 1
        response = requests.post(GRAPHQL_URL, json={'query': query, 'variables': variables or {}},
                                 headers=self.headers, timeout=60)
        if response.status_code == 403:
            raise RuntimeError(f'{name}: 403 — hit GitHub\'s anti-abuse rate limit, try again later')
        if response.status_code != 200:
            raise RuntimeError(f'{name} failed with {response.status_code}: {response.text}')
        payload = response.json()
        if payload.get('errors'):
            raise RuntimeError(f'{name} returned errors: {payload["errors"]}')
        return payload['data']

    def user_id(self):
        data = self.query('user_id', '''
            query($login: String!) { user(login: $login) { id } }''', {'login': self.user_name})
        return data['user']['id']

    def followers(self):
        data = self.query('followers', '''
            query($login: String!) { user(login: $login) { followers { totalCount } } }''',
            {'login': self.user_name})
        return data['user']['followers']['totalCount']

    def repositories(self, affiliations):
        """Every repository for the given ownerAffiliations, 60 per page (bigger pages 502)."""
        query = '''
        query($affiliations: [RepositoryAffiliation], $login: String!, $cursor: String) {
            user(login: $login) {
                repositories(first: 60, after: $cursor, ownerAffiliations: $affiliations) {
                    nodes {
                        nameWithOwner
                        stargazers { totalCount }
                        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
                    }
                    pageInfo { endCursor hasNextPage }
                }
            }
        }'''
        nodes, cursor = [], None
        while True:
            data = self.query('repositories', query,
                              {'affiliations': affiliations, 'login': self.user_name, 'cursor': cursor})
            page = data['user']['repositories']
            nodes += page['nodes']
            if not page['pageInfo']['hasNextPage']:
                return nodes
            cursor = page['pageInfo']['endCursor']

    def commit_history(self, owner, name, author_id):
        """Yield (author user id or None, additions, deletions) for the default-branch commits
        authored by `author_id`. Filtering server-side keeps forks of huge projects cheap."""
        query = '''
        query($owner: String!, $name: String!, $author: ID!, $cursor: String) {
            repository(owner: $owner, name: $name) {
                defaultBranchRef {
                    target { ... on Commit {
                        history(first: 100, after: $cursor, author: {id: $author}) {
                            nodes { author { user { id } } additions deletions }
                            pageInfo { endCursor hasNextPage }
                        }
                    } }
                }
            }
        }'''
        cursor = None
        while True:
            data = self.query('commit_history', query,
                              {'owner': owner, 'name': name, 'author': author_id, 'cursor': cursor})
            ref = data['repository']['defaultBranchRef']
            if ref is None:
                return
            history = ref['target']['history']
            for node in history['nodes']:
                user = node['author']['user']
                yield (user['id'] if user else None), node['additions'], node['deletions']
            if not history['pageInfo']['hasNextPage']:
                return
            cursor = history['pageInfo']['endCursor']


# ---------- main ----------

def main():
    token, user_name = os.environ.get('ACCESS_TOKEN'), os.environ.get('USER_NAME')
    if not token or not user_name:
        sys.exit('ACCESS_TOKEN and USER_NAME environment variables are required')
    started = time.perf_counter()
    api = GitHubApi(token, user_name)

    owner_id = api.user_id()
    owned = api.repositories(['OWNER'])
    contributed = api.repositories(ALL_AFFILIATIONS)
    followers = api.followers()
    entries = update_loc_cache(api, owner_id, contributed, cache_path(user_name))
    adds, dels, net, commits = loc_totals(entries)

    stats = {
        'age_data': uptime(BIRTHDAY),
        'repo_data': len(owned),
        'contrib_data': len(contributed),
        'star_data': sum(r['stargazers']['totalCount'] for r in owned),
        'commit_data': commits,
        'follower_data': followers,
        'loc_data': net,
        'loc_add': adds,
        'loc_del': dels,
    }
    for svg in SVG_FILES:
        fill(svg, stats)

    for key, value in stats.items():
        print(f'{key:<14} {format_value(value)}')
    print(f'GraphQL calls: {sum(api.calls.values())} ({dict(api.calls)}) in {time.perf_counter() - started:.1f}s')


if __name__ == '__main__':
    main()
