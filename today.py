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
