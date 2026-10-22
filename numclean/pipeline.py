"""Repeatable cleaning pipeline: detect encoding -> UTF-8, validate/repair numeric columns, write clean files + correction log.
Usage: python -m numclean.pipeline <in_dir> <out_dir> [--numeric col1,col2] [--decimal auto|.|,]"""
import argparse, csv, json, re, sys
from pathlib import Path
import pandas as pd
from charset_normalizer import from_bytes

CURRENCY = re.compile(r"(?i)R\$|US\$|\b(EUR|USD|CHF|INR|GBP|JPY|IDR|Rp|Rs\.?)\b|[₹$€£¥\s\u00a0\u202f']")  # symbols/codes/spaces/apostrophes
SCI = re.compile(r"[+-]?\d+(\.\d+)?[eE][+-]?\d+")

def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"): return "utf-8-sig"
    try: raw.decode("ascii"); return "ascii"
    except UnicodeDecodeError: pass
    try: raw.decode("utf-8"); return "utf-8"
    except UnicodeDecodeError: pass
    best = from_bytes(raw).best()
    return best.encoding if best else "latin-1"

def parse_number(s, decimal="auto"):
    """Return (value or None, note). Handles 1,234.56 / 1.234,56 / (123) negatives / trailing minus / currency / spaces."""
    if s is None: return None, None
    t = str(s).strip()
    if t == "" or t.lower() in {"na", "n/a", "null", "none", "-"}: return None, "empty"
    orig = t; neg = False
    if t.startswith("(") and t.endswith(")"): neg, t = True, t[1:-1]
    if t.endswith("-"): neg, t = True, t[:-1]
    if SCI.fullmatch(t): return float(t), None
    t = CURRENCY.sub("", t)
    if re.search(r"[^\d,.\-+]", t): return None, f"invalid:{orig!r}"   # stray letters (e.g. O instead of 0)
    if decimal == "auto":
        if "," in t and "." in t: decimal = "," if t.rfind(",") > t.rfind(".") else "."
        elif t.count(",") == 1 and len(t.split(",")[1]) != 3: decimal = ","
        else: decimal = "."
    t = t.replace("." if decimal == "," else ",", "")
    if decimal == ",": t = t.replace(",", ".")
    try: v = float(t)
    except ValueError: return None, f"invalid:{orig!r}"
    v = -abs(v) if neg else v
    return v, (None if str(v) == orig or orig == t else f"fixed:{orig!r}->{v}")

def clean_file(path: Path, out_dir: Path, numeric=None, decimal="auto"):
    raw = path.read_bytes(); enc = detect_encoding(raw); text = raw.decode(enc)
    head = text.splitlines()[0]; delim = max(",;\t|", key=head.count)   # delimiter = most frequent in header
    df = pd.read_csv(pd.io.common.StringIO(text), sep=delim, dtype=str, keep_default_na=False)
    log = []
    cols = numeric or [c for c in df.columns if df[c].str.contains(r"\d").mean() > 0.6]
    for c in cols:
        vals = []
        for i, s in enumerate(df[c]):
            v, note = parse_number(s, decimal)
            if note and note != "empty": log.append({"file": path.name, "row": i + 2, "column": c, "action": note})
            vals.append(v)
        arr = pd.array(vals, dtype="Float64")
        df[c] = arr.astype("Int64") if (arr.dropna() % 1 == 0).all() else arr   # keep integers as integers
    out = out_dir / (path.stem + ".csv"); df.to_csv(out, index=False, encoding="utf-8")
    return {"file": path.name, "encoding": enc, "delimiter": delim, "rows_in": len(df), "rows_out": len(df),
            "numeric_columns": cols, "corrections": sum(1 for l in log if l["action"].startswith("fixed")),
            "invalid_to_null": sum(1 for l in log if l["action"].startswith("invalid"))}, log

def run(in_dir, out_dir, numeric=None, decimal="auto"):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True); summary, logs = [], []
    for p in sorted(Path(in_dir).glob("*")):
        if p.suffix.lower() in {".csv", ".txt", ".tsv"}:
            s, l = clean_file(p, out_dir, numeric, decimal); summary.append(s); logs += l
    pd.DataFrame(logs, columns=["file", "row", "column", "action"]).to_csv(out_dir / "_corrections_log.csv", index=False)
    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary, logs

if __name__ == "__main__":
    a = argparse.ArgumentParser(); a.add_argument("in_dir"); a.add_argument("out_dir")
    a.add_argument("--numeric"); a.add_argument("--decimal", default="auto"); x = a.parse_args()
    s, l = run(x.in_dir, x.out_dir, x.numeric.split(",") if x.numeric else None, x.decimal)
    for r in s: print(f"{r['file']:<22} {r['encoding']:<10} rows={r['rows_in']:<4} fixed={r['corrections']:<3} invalid->NULL={r['invalid_to_null']}")
    print(f"log: {Path(x.out_dir)/'_corrections_log.csv'}")
