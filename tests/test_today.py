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
