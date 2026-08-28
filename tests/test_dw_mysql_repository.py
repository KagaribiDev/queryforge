from datetime import date, datetime
from decimal import Decimal

from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository


def test_metadata_sample_values_are_json_compatible():
    convert = DWMySQLRepository._to_json_compatible

    assert convert(Decimal("123.45")) == 123.45
    assert convert(date(2025, 1, 2)) == "2025-01-02"
    assert convert(datetime(2025, 1, 2, 3, 4, 5)) == "2025-01-02T03:04:05"
    assert convert("华东") == "华东"
