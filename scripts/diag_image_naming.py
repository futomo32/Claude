#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品写真のファイル名の命名規則を、実データで機械的に特定する診断。

背景(2026-08-10):
  backfill_images_bykey.py は「ファイル名の数字=商品キーの数字部分」と解釈して
  6,353件を紐付けたが、誤りだった(時計に別商品のペンダント写真が付き、
  オパールリング(キー候補104714)には付かなかった)。
  推測で再設計せず、このスクリプトで**どの解釈が実データに一番合うか**を数えて決める。

検証する仮説(ファイル名の数字部分の正体):
  A. 商品キーの数字部分(lngsykey)                     … 例 01-104714 → 104714
  B. 店舗番号(前ゼロ無し)+商品番号                    … 例 店01・番号04714 → 104714
  C. 商品番号そのまま                                  … 例 番号13331 → 13331
  D. 店舗番号+商品キーの数字部分                       … 例 店01・キー4714 → 14714

判定方法:
  画像フォルダの数字名ファイル(7千種)それぞれについて、各仮説で商品に一致するかを数える。
  一致率が突出して高い仮説が正解。同率なら、一致した商品の重複数(1商品に確定するか)も見る。

さらに、話に出た実例(リング04714・時計13331・ブレス00169)については、
該当し得る商品の「キー・番号・店舗」を個別に表示して目視確認できるようにする。

出力: 件数・商品番号・キー・商品名(商品情報は個人情報ではないため表示する)。顧客情報は出さない。

使い方(店のPC): python3 scripts/diag_image_naming.py
"""
import os
import re
import sqlite3
import sys
from collections import defaultdict

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
IMG_DIR = os.path.join(BASE, "data", "real", "images")
FNAME = re.compile(r"^(\d+)(?:_(\d+))?\.(jpe?g|png)$", re.IGNORECASE)

# 個別に見たい実例(これまでの調査で正解が分かっているもの)
PROBES = [
    ("104714", "オパールリング(番号04714)の写真のはず"),
    ("13331", "時計テンデンス(番号13331)に誤って付いた"),
    ("200169", "ピンクブレス(店02?・番号00169?)の写真のはず"),
]


def main():
    if not os.path.exists(DB):
        sys.exit(f"[エラー] DBがありません: {DB}")
    if not os.path.isdir(IMG_DIR):
        sys.exit(f"[エラー] 画像フォルダがありません: {IMG_DIR}")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 商品側の索引を4仮説ぶん作る
    by_key = defaultdict(list)      # A: キーの数字部分
    by_store_no = defaultdict(list)  # B: 店舗番号+商品番号
    by_no = defaultdict(list)       # C: 商品番号(数字のみのもの)
    by_store_key = defaultdict(list)  # D: 店舗番号+キー数字
    for r in con.execute("SELECT product_key, product_no, name FROM products"):
        pk = str(r["product_key"] or "")
        store, _, keynum = pk.partition("-")
        no = str(r["product_no"] or "").strip()
        rec = (pk, no, r["name"] or "")
        if keynum.isdigit():
            by_key[keynum].append(rec)
        try:
            sd = str(int(store))
        except ValueError:
            sd = None
        if sd and no.isdigit():
            by_store_no[sd + no].append(rec)
        if no.isdigit():
            by_no[no].append(rec)
        if sd and keynum.isdigit():
            by_store_key[sd + keynum].append(rec)

    # 画像の数字名を集める(連番は無視して数字部分の種類だけ)
    bases = set()
    for fn in os.listdir(IMG_DIR):
        m = FNAME.match(fn)
        if m:
            bases.add(m.group(1))
    total = len(bases)
    if not total:
        sys.exit("数字名の画像がありません")

    print("=" * 70)
    print(f"  画像の数字名: {total:,}種 / 商品: {sum(len(v) for v in by_key.values()):,}件")
    print("  各仮説での一致率(高いものが正解の可能性大):")
    print("=" * 70)
    for label, idx in (("A. 商品キーの数字部分", by_key),
                       ("B. 店舗番号+商品番号", by_store_no),
                       ("C. 商品番号そのまま", by_no),
                       ("D. 店舗番号+キー数字", by_store_key)):
        hit = sum(1 for b in bases if b in idx)
        multi = sum(1 for b in bases if len(idx.get(b, [])) > 1)
        print(f"  {label:<22} 一致 {hit:>6,}/{total:,} ({hit/total*100:5.1f}%)"
              f"  うち複数商品に該当 {multi:,}")
    print()

    # 実例の個別確認
    print("── 実例の突き合わせ(正解を目視で確認する) " + "─" * 24)
    for base, why in PROBES:
        print(f"\n■ ファイル {base}*.jpg — {why}")
        for label, idx in (("A:キー一致", by_key), ("B:店+番号一致", by_store_no),
                           ("C:番号一致", by_no), ("D:店+キー一致", by_store_key)):
            for pk, no, name in idx.get(base, [])[:3]:
                print(f"   [{label}] キー={pk} 番号={no} 名={name[:30]}")
        if not any(base in idx for idx in (by_key, by_store_no, by_no, by_store_key)):
            print("   (どの仮説でも該当商品なし)")
    print()
    print("=" * 70)
    print("  この出力を開発側に渡してください。一致率と実例から命名規則を確定し、")
    print("  正しい紐付けを再実装します(反映済みの誤紐付けは --undo で外せます)。")
    print("=" * 70)
    con.close()


if __name__ == "__main__":
    main()
