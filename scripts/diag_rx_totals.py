# -*- coding: utf-8 -*-
"""処方箋の「合計金額」が空になっている割合を調べる診断(読み取り専用・個人情報は出さない)。

顧客詳細のメガネ処方箋タブで合計金額が「―」になる処方箋がある件の切り分け用。
表示するのは件数のみ(顧客名・金額そのものは出さない)。

  python3 scripts/diag_rx_totals.py            # data/real/csv
  python3 scripts/diag_rx_totals.py --demo     # data/demo_csv
"""
import csv
import os
import sys

csv.field_size_limit(10 * 1024 * 1024)
BASE = os.path.join(os.path.dirname(__file__), "..")
SRC = os.path.join(BASE, "data", "real", "csv")
if "--demo" in sys.argv:
    SRC = os.path.join(BASE, "data", "demo_csv")


def rows(name):
    path = os.path.join(SRC, name + ".csv")
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


def s(v):
    return (v or "").strip() or None


total = 0
has_total = 0
has_lens_key = 0
has_frame_key = 0
no_total_but_has_key = 0
for r in rows("d_shohosen"):
    total += 1
    gokei = s(r.get("curgokeiurine"))
    lens_key = s(r.get("lngsykey1"))
    frame_key = s(r.get("lngsykey2"))
    if gokei and gokei != "0":
        has_total += 1
    if lens_key:
        has_lens_key += 1
    if frame_key:
        has_frame_key += 1
    if (not gokei or gokei == "0") and (lens_key or frame_key):
        no_total_but_has_key += 1

print(f"処方箋 総件数: {total:,}")
print(f"  合計金額(curgokeiurine)が入っている: {has_total:,} 件 ({has_total*100//max(total,1)}%)")
print(f"  レンズ商品キーが入っている: {has_lens_key:,} 件")
print(f"  フレーム商品キーが入っている: {has_frame_key:,} 件")
print(f"  商品は紐づいているが合計金額が空: {no_total_but_has_key:,} 件")
print()
print("見るポイント: 「商品は紐づいているが合計金額が空」の件数が多ければ、")
print("宝飾ナビの運用上その項目に金額を入力していなかった(=移行前からのデータ欠落)可能性が高い。")
print("逆にこの件数が少なければ、別の原因(列の読み違い等)を疑う。")
