"""Callback data classes (colon-namespaced per convention).

Callback data strings are generated as prefix:field1:field2, e.g.
  LangCallback(action="set", code="en")  ->  lang:set:en
  ComplianceCallback(step="age", value="yes") -> compliance:age:yes
  MenuCallback(action="catalog") -> menu:catalog
"""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class LangCallback(CallbackData, prefix="lang"):
    action: str
    code: str


class ComplianceCallback(CallbackData, prefix="compliance"):
    step: str
    value: str


class MenuCallback(CallbackData, prefix="menu"):
    action: str
