# -*- coding: utf-8 -*-
"""商品金額のマッピング検証(読み取り専用)。

11xlsx(hs1401_item)は「仕入単価/上代価格/特別上代」を日本語で解決済み。
CSV(d_item)は curorokin/curkoukin/curtokkin… とコードのまま。
両者を商品キー(店舗コード+商品キー)で突き合わせ、
「どのCSV列が、どのxlsx金額と一致するか」を一致率で出す。
→ import_csv.py の金額マッピング(cost=curorokin, list=curkoukin)が正しいか確認できる。

  python3 scripts/validate_amounts.py                     # 実データ(data/real ↔ data/real/csv)
  python3 scripts/validate_amounts.py <xlsxフォルダ> <csvフォルダ>
"""
import csv
import glob
import os
import sys

csv.field_size_limit(10 * 1024 * 1024)
try:
    import openpyxl
except ImportError:
    print("[エラー] openpyxl が必要です。 pip3 install openpyxl")
    sys.exit(1)

BASE = os.path.join(os.path.dirname(__file__), "..")
XDIR = os.path.join(BASE, "data", "real")
CDIR = os.path.join(BASE, "data", "real", "csv")
if len(sys.argv) >= 3:
    XDIR, CDIR = sys.argv[1], sys.argv[2]

XLSX_COLS = ["仕入単価", "上代価格", "特別上代", "小売価格消費税"]
CSV_CANDS = ["curorokin", "curkoukin", "curtokkin", "curkouzeikin", "curtokzeikin", "curororit"]


def to_int(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError, AttributeError):
        return None


def find_xlsx(key):
    for p in sorted(glob.glob(os.path.join(XDIR, "*.xlsx"))):
        if key in os.path.basename(p):
            return p
    return None


def load_xlsx_amounts():
    p = find_xlsx("item") or find_xlsx("商品")
    if not p:
        print(f"[エラー] 商品xlsxが {XDIR} に見つかりません")
        sys.exit(1)
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb.active
    ws.reset_dimensions()
    it = ws.iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(it)]
    idx = {name: i for i, name in enumerate(header)}
    ki = idx.get("店舗コード")
    si = idx.get("商品キー")
    cols = {c: idx[c] for c in XLSX_COLS if c in idx}
    print(f"xlsx: {os.path.basename(p)} / 金額列: {list(cols)}")
    data = {}
    for r in it:
        if r is None or (ki is not None and r[ki] is None):
            continue
        key = (str(r[ki]).strip(), str(r[si]).strip()) if ki is not None and si is not None else None
        if not key:
            continue
        data[key] = {c: to_int(r[i]) for c, i in cols.items()}
    wb.close()
    return data, list(cols)


def csv_rows():
    path = os.path.join(CDIR, "d_item.csv")
    if not os.path.exists(path):
        print(f"[エラー] {path} がありません")
        sys.exit(1)
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline(); f.seek(0)
            break
        except UnicodeDecodeError:
            f.close()
    else:
        f = open(path, "r", encoding="cp932", errors="replace", newline="")
    try:
        for r in csv.DictReader(f):
            yield r
    finally:
        f.close()


def main():
    print("xlsxの金額を読み込み中…(1〜2分)")
    xa, xcols = load_xlsx_amounts()
    print(f"xlsx商品: {len(xa):,}件\nCSVと突き合わせ中…\n")

    tally = {(x, c): [0, 0] for x in xcols for c in CSV_CANDS}
    matched = 0
    for r in csv_rows():
        key = (str(r.get("strsytencode", "")).strip(), str(r.get("lngsykey", "")).strip())
        xrow = xa.get(key)
        if not xrow:
            continue
        matched += 1
        cvals = {c: to_int(r.get(c)) for c in CSV_CANDS}
        for x in xcols:
            xv = xrow.get(x)
            if xv is None:
                continue
            for c in CSV_CANDS:
                cv = cvals[c]
                if cv is None:
                    continue
                tally[(x, c)][1] += 1
                if cv == xv:
                    tally[(x, c)][0] += 1

    print(f"突き合わせ成功: {matched:,}件\n")
    print("=== どのCSV列が、どのxlsx金額と一致するか(一致率) ===")
    for x in xcols:
        print(f"\n■ xlsx『{x}』に最も一致するCSV列:")
        ranked = sorted(CSV_CANDS, key=lambda c: -(tally[(x, c)][0] / tally[(x, c)][1] if tally[(x, c)][1] else 0))
        for c in ranked:
            m, t = tally[(x, c)]
            if t == 0:
                continue
            rate = m / t * 100
            mark = " ★これ" if rate >= 95 else (" (概ね一致)" if rate >= 80 else "")
            print(f"    {c:16s}: {rate:5.1f}% ({m:,}/{t:,}){mark}")
    print("\n判定: import_csv.py は cost_price=curorokin, list_price=curkoukin としている。")
    print("      上の『仕入単価』★と『上代価格』★が想定通りか確認してください。")


if __name__ == "__main__":
    main()
