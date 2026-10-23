"""ClickHouse auto-create helpers used by fast_write."""
import pyarrow as pa
import pytest

from app.engine.executor import _ch_ident, _ch_type


@pytest.mark.parametrize("t,want", [
    (pa.int32(), "Nullable(Int32)"), (pa.int64(), "Nullable(Int64)"), (pa.uint8(), "Nullable(UInt8)"),
    (pa.float64(), "Nullable(Float64)"), (pa.bool_(), "Nullable(Bool)"), (pa.string(), "Nullable(String)"),
    (pa.large_string(), "Nullable(String)"), (pa.date32(), "Nullable(Date32)"),
    (pa.timestamp("us"), "Nullable(DateTime64(6))"), (pa.timestamp("ms", tz="UTC"), "Nullable(DateTime64(3, 'UTC'))"),
    (pa.decimal128(12, 2), "Nullable(Decimal(12, 2))"), (pa.dictionary(pa.int8(), pa.string()), "Nullable(String)"),
])
def test_ch_type(t, want):
    assert _ch_type(t) == want


def test_ch_ident_quotes_and_escapes():
    assert _ch_ident("default", "nyc") == "`default`.`nyc`"
    assert _ch_ident(None, "a`b") == "`a``b`"
