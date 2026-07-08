"""The project assumes a UTF-8 environment; assert that invariant.

Pure software. ``$LANG`` is environment-dependent, so we *skip* (not fail) when
it is unset instead of crashing on ``None``.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.software


def test_python_default_encoding_is_utf8():
    assert sys.getdefaultencoding() == "utf-8"


def test_locale_is_utf8_when_set():
    lang = os.environ.get("LANG")
    if not lang:
        pytest.skip("环境未设置 $LANG，跳过 locale 检查")
    upper = lang.upper()
    assert "UTF-8" in upper or "UTF8" in upper, f"系统 locale 不是 UTF-8: {lang}"
