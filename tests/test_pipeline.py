import json
from numclean.pipeline import parse_number, run
def test_parse():
    assert parse_number("1,450.00")[0] == 1450.0 and parse_number("1.234,56")[0] == 1234.56
    assert parse_number("(250.00)")[0] == -250 and parse_number("12,00-")[0] == -12 and parse_number("EUR 3,50")[0] == 3.5
    assert parse_number("12O")[0] is None   # letter O, not zero -> logged as invalid
def test_run(tmp_path):
    s, log = run("sample_raw", tmp_path)
    by = {r["file"]: r for r in s}
    assert by["eu_export_latin1.csv"]["encoding"] not in ("ascii", "utf-8") and by["sales_ascii.csv"]["encoding"] == "ascii"
    assert all(r["rows_in"] == r["rows_out"] for r in s)
    out = (tmp_path / "eu_export_latin1.csv").read_text(encoding="utf-8"); assert "Käse" in out
    assert any(l["action"].startswith("invalid") for l in log)
