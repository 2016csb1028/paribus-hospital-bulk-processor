"""Unit tests: CSV parsing & validation."""
import pytest

from app.csv_parser import CSVFormatError, parse_and_validate


def test_parses_valid_csv_with_optional_phone():
    raw = b"name,address,phone\nGeneral Hospital,123 Main St,555-1234\nCity Clinic,9 Oak Ave,\n"
    rows, errors = parse_and_validate(raw)
    assert errors == []
    assert len(rows) == 2
    assert rows[0].name == "General Hospital"
    assert rows[0].phone == "555-1234"
    assert rows[1].phone is None


def test_phone_column_entirely_optional():
    raw = b"name,address\nA,1 St\nB,2 St\n"
    rows, errors = parse_and_validate(raw)
    assert len(rows) == 2 and not errors


def test_header_required():
    with pytest.raises(CSVFormatError):
        parse_and_validate(b"General Hospital,123 Main St,555-1234\n")


def test_empty_file_rejected():
    with pytest.raises(CSVFormatError):
        parse_and_validate(b"")


def test_missing_required_column_rejected():
    with pytest.raises(CSVFormatError, match="Missing: address"):
        parse_and_validate(b"name,phone\nA,555\n")


def test_unknown_column_rejected():
    with pytest.raises(CSVFormatError, match="Unknown"):
        parse_and_validate(b"name,address,fax\nA,1 St,999\n")


def test_row_limit_enforced():
    body = "name,address\n" + "\n".join(f"H{i},{i} St" for i in range(21))
    with pytest.raises(CSVFormatError, match="maximum allowed is 20"):
        parse_and_validate(body.encode())


def test_exactly_20_rows_allowed():
    body = "name,address\n" + "\n".join(f"H{i},{i} St" for i in range(20))
    rows, errors = parse_and_validate(body.encode())
    assert len(rows) == 20 and not errors


def test_per_row_errors_reported_with_row_numbers():
    raw = b"name,address,phone\n,No Name St,555\nOk Hospital,,\nFine,1 St,not!!a@phone#xyz$%^&*\n"
    rows, errors = parse_and_validate(raw)
    assert len(rows) == 0
    assert [e.row for e in errors] == [1, 2, 3]
    assert "name is required" in errors[0].errors
    assert "address is required" in errors[1].errors
    assert "phone has an invalid format" in errors[2].errors


def test_bom_and_whitespace_tolerated():
    raw = "\ufeffname , address\n  Trim Hospital  ,  5 Elm St \n".encode()
    rows, errors = parse_and_validate(raw)
    assert not errors
    assert rows[0].name == "Trim Hospital"
    assert rows[0].address == "5 Elm St"


def test_non_utf8_rejected():
    with pytest.raises(CSVFormatError, match="UTF-8"):
        parse_and_validate(b"name,address\n\xff\xfe,bad\n")
