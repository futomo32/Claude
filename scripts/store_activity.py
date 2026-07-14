# -*- coding: utf-8 -*-
"""店舗コード別の「購入活動」を集計する(読み取り専用・個人情報は出さない)。

不明店舗(99等)の顧客が、ここ10年で実際に商品購入しているかを判定するためのツール。
販売台帳(d_hanbai)を顧客の店舗コード(strkotencode)で集計し、
店舗別の販売件数・直近10年の件数・最終購入日・年別分布を出す。金額の合計のみ表示、氏名は出さない。

  python3 scripts/store_activity.py            # data/real/csv
  python3 scripts/store_activity.py --demo     # data/demo_csv
"""
import csv
import datetime
import os
import re
import sys
from collections import defaultdict

csv.field_size_limit(10 * 1024 * 1024)
BASE = os.path.join(os.path.dirname(__file__), "..")
SRC = os.path.join(BASE, "data", "real", "csv")

THIS_YEAR = datetime.date.today().year
CUTOFF = THIS_YEAR - 10  # ここ10年 = CUTOFF年以降


def s(v):
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def rows(name):
    path = os.path.join(SRC, name + ".csv")
    if not os.path.exists(path):
        return
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


def year_of(v):
    t = s(v)
    if not t:
        return None
    m = re.match(r"(\d{4})[-/.]", t)
    if m:
        y = int(m.group(1))
        if 1950 <= y <= THIS_YEAR + 1:
            return y
    return None


def n(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


def main():
    global SRC
    if "--demo" in sys.argv:
        SRC = os.path.join(BASE, "data", "demo_csv")

    # 店舗別 顧客数
    cust_by_store = defaultdict(int)
    for r in rows("d_user"):
        st = s(r.get("strkotencode"))
        if st:
            cust_by_store[st] += 1

    # 店舗別 販売活動(顧客の店舗コード=strkotencode で集計)
    n_rows = defaultdict(int)
    n_recent = defaultdict(int)
    amt_recent = defaultdict(int)
    max_year = {}
    recent_custs = defaultdict(set)
    year_hist = defaultdict(lambda: defaultdict(int))  # store -> year -> 件数
    for r in rows("d_hanbai"):
        st = s(r.get("strkotencode"))
        if not st:
            continue
        y = year_of(r.get("datkaidate")) or year_of(r.get("datcredate"))
        n_rows[st] += 1
        if y:
            year_hist[st][y] += 1
            if st not in max_year or y > max_year[st]:
                max_year[st] = y
            if y >= CUTOFF:
                n_recent[st] += 1
                amt_recent[st] += n(r.get("curkaikin")) or 0
                cid = f"{st}-{s(r.get('lngkokey'))}"
                recent_custs[st].add(cid)

    stores = sorted(set(cust_by_store) | set(n_rows), key=lambda x: -cust_by_store.get(x, 0))
    print(f"=== 店舗別 購入活動(ここ10年 = {CUTOFF}年以降) ===\n")
    print(f"{'店舗':>6} {'顧客数':>8} {'販売総件数':>10} {'直近10年件数':>12} {'直近10年購入客数':>16} {'最終購入年':>10}")
    print("-" * 74)
    for st in stores:
        print(f"{st:>6} {cust_by_store.get(st,0):>8,} {n_rows.get(st,0):>10,} "
              f"{n_recent.get(st,0):>12,} {len(recent_custs.get(st,set())):>16,} "
              f"{max_year.get(st,'-'):>10}")

    print("\n=== 不明店舗の年別 販売件数(直近15年) ===")
    for st in stores:
        if st in ("01", "02"):
            continue
        yrs = year_hist.get(st, {})
        if not yrs:
            continue
        print(f"\n店舗 {st}(直近10年売上合計 {amt_recent.get(st,0):,}円):")
        for y in range(THIS_YEAR, THIS_YEAR - 15, -1):
            if yrs.get(y):
                bar = "#" * min(40, yrs[y] // 50 + 1)
                print(f"   {y}: {yrs[y]:>6,} 件 {bar}")


if __name__ == "__main__":
    main()
