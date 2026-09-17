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
