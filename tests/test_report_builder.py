import io
import zipfile

import pytest

from app.jobs.report_builder import InvalidSnapshot, build_menu_report
from tests.helpers import SNAPSHOT


def test_build_menu_report_returns_valid_xlsx():
    content = build_menu_report(SNAPSHOT)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        assert "xl/worksheets/sheet1.xml" in z.namelist()
        strings = z.read("xl/sharedStrings.xml").decode()
    for text in ("Menu 1", "Sub 1", "Dish 1"):
        assert text in strings


def test_empty_menu_list_is_valid():
    assert build_menu_report([])[:2] == b"PK"


@pytest.mark.parametrize(
    "snapshot",
    [None, {"a": 1}, [{"title": "x"}], [{"title": "x", "description": "", "submenus": [{}]}]],
)
def test_invalid_snapshot_raises(snapshot):
    with pytest.raises(InvalidSnapshot):
        build_menu_report(snapshot)
