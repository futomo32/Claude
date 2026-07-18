# -*- coding: utf-8 -*-
"""既存DBの products.image_file を d_item.csv から埋める(B-7・再インポート不要)。

商品写真の表示に使うファイル名(strpicfilename)は後から products に追加した列なので、
取り込み済みのDBには入っていない。このツールは d_item.csv を読み、商品キーで突き合わせて
products.image_file を更新する(データは消さない・冪等)。実ファイルの有無は問わない
(表示側で見つからなければ写真なし扱いになるだけ)。

  python3 scripts/backfill_images.py
先に scripts/migrate_db.py で image_file 列を追加しておくこと。
"""
import csv
import os
import sqlite3
import sys

csv.field_size_limit(10 * 1024 * 1024)
BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
CSVP = os.path.join(BASE, "data", "real", "csv", "d_item.csv")


def s(v):
    return (v or "").strip() or None


def rows(path):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, encoding=enc, newline="")
            f.readline(); f.seek(0)
            break
        except UnicodeDecodeError:
            f.close()
    else:
        f = open(path, encoding="cp932", errors="replace", newline="")
    try:
        for r in csv.DictReader(f):
            yield r
    finally:
        f.close()


def main():
    if not os.path.exists(DB):
        sys.exit(f"DBがありません: {DB}")
    if not os.path.exists(CSVP):
        sys.exit(f"d_item.csv がありません: {CSVP}(data/real/csv に置いてください)")
    con = sqlite3.connect(DB)
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if "image_file" not in cols:
        con.close()
        sys.exit("products.image_file 列がありません。先に scripts/migrate_db.py を実行してください。")
    n = upd = 0
    for r in rows(CSVP):
        tc, kc = s(r.get("strsytencode")), s(r.get("lngsykey"))
        if not tc or not kc:
            continue
        img = os.path.basename((s(r.get("strpicfilename")) or "").replace("\\", "/")) or None
        if not img:
            continue
        n += 1
        cur = con.execute(
            "UPDATE products SET image_file=? WHERE product_key=? AND (image_file IS NULL OR image_file='')",
            (img, f"{tc}-{kc}"))
        upd += cur.rowcount
    con.commit()
    con.close()
    print(f"d_itemに画像名あり: {n:,} 件 / products.image_file を更新: {upd:,} 件")
    print("完了。トキワ起動.bat → 商品・在庫 で写真を確認してください。")


if __name__ == "__main__":
    main()
