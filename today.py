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

def leader(just_len):
    """Dotted leader padding a value to its reserved width."""
    if just_len <= 0:
        return ''
    if just_len == 1:
        return ' '
    if just_len == 2:
        return '. '
    return ' ' + '.' * just_len + ' '


def format_value(value):
    return f'{value:,}' if isinstance(value, int) else str(value)


def justify(root, element_id, value, length=0):
    """Set #element_id's text and resize #element_id_dots so the value stays right-aligned."""
    text = format_value(value)
    _set_text(root, element_id, text)
    _set_text(root, f'{element_id}_dots', leader(length - len(text)))


def _set_text(root, element_id, text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = text


def update_svg(path, values):
    """values: {element_id: (value, reserved_length)} — see RESERVED."""
    tree = etree.parse(path)
    root = tree.getroot()
    for element_id, (value, length) in values.items():
        justify(root, element_id, value, length)
    tree.write(path, encoding='utf-8', xml_declaration=True)


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
    counting just the commits authored by `owner_id`. The file is rewritten after every
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
        for author_id, additions, deletions in api.commit_history(owner, name):
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
