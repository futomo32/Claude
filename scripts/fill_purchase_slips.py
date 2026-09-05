# -*- coding: utf-8 -*-
"""宝飾ナビの仕入データから「納品書No」と「伝票日付」を商品に埋める(2026-09-05)。

作った理由:
  トキワの商品に納品書No・伝票日付の欄を作ったが(v1.4.2 / v1.4.10)、
  **過去の21万件は空**のまま。宝飾ナビの元CSVには入っているので、後から埋める。
  ★再取込は不要。この2項目だけを足す。

  元データ(scripts/find_slip_no.py で確定・docs/csv-migration-design.md に記録):
    d_siire.strsirsakidenno … 納品書No   12.5% / 21,097件
    d_siire.datdendate      … 伝票日付   88.2% / 148,377件
    d_jutaku(受託)にも同じ列がある(納品書No 5.7% / 1,172件)
  商品との突き合わせは **lngsykey(商品キー)** で行う。
  ★商品番号(strsyno)ではない。同じ数字が別商品に入っていることがあり、
    取り違えると**まったく別の品に別の納品書Noを入れてしまう**。

★既定は「下読み」。何件入るかを出すだけで、データは変更しない。
  書き込むのは --apply を付けた時だけで、その直前に必ずバックアップを取る。

使い方:
  python3 scripts/fill_purchase_slips.py            # 下読み(何件入るか見るだけ)
  python3 scripts/fill_purchase_slips.py --apply    # バックアップしてから書き込む
  python3 scripts/fill_purchase_slips.py --apply --overwrite
        # 既に値が入っている商品も上書きする(既定は空の商品だけ入れる)
"""
import argparse
import collections
import csv
import os
import shutil
import sqlite3
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(BASE, "server"))
import _paths  # noqa: E402
import db_query  # noqa: E402

REAL_BASE = os.path.join(BASE, "data", "real")
# 読む表と、その中の列名。宝飾ナビの仕入(d_siire)と受託(d_jutaku)が同じ形を持つ
SOURCES = [("d_siire", "仕入"), ("d_jutaku", "受託")]
COL_KEY = "lngsykey"            # 商品キー(★商品番号 strsyno とは別物)
COL_STORE = "strsytencode"      # 店舗コード。商品キーは「店舗-キー」で作る
COL_SLIP_NO = "strsirsakidenno"  # 納品書No
COL_SLIP_DATE = "datdendate"     # 伝票日付


def s(v):
    return unicodedata.normalize("NFKC", "" if v is None else str(v)).strip()


def ymd(v):
    """「2025/04/18 0:00:00」→「2025-04-18」。読めない値は None。"""
    t = s(v).split(" ")[0].replace("/", "-")
    p = t.split("-")
    if len(p) != 3 or not all(x.isdigit() for x in p):
        return None
    y, m, d = int(p[0]), int(p[1]), int(p[2])
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return "%04d-%02d-%02d" % (y, m, d)


def read_source(path):
    """CSVを (見出し, 行の反復子) で返す。宝飾ナビの書き出しは cp932 のことが多い。"""
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            return rows
        except UnicodeDecodeError:
            continue
    print("  [読めません] 文字コードを判定できませんでした: %s" % path)
    return []


def main():
    ap = argparse.ArgumentParser(description="納品書No・伝票日付を商品に埋める(既定は下読み)")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読みのみ)")
    ap.add_argument("--overwrite", action="store_true",
                    help="既に値が入っている商品も上書きする(既定は空の商品だけ)")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1
    csv_dir = _paths.find_dir(REAL_BASE, "*.csv", "csv")

    # ── 元データを読む。1つの商品キーに複数行あることがあるので、
    #    ★伝票日付が新しい行を優先する(最後の仕入がその商品の実態に近いため)
    picked = {}
    stats = collections.Counter()
    for table, label in SOURCES:
        path = os.path.join(csv_dir, table + ".csv")
        if not os.path.exists(path):
            print("  ※ %s.csv がありません(飛ばします)" % table)
            continue
        rows = read_source(path)
        print("  %s(%s): %s行" % (table, label, format(len(rows), ",")))
        for r in rows:
            store, key = s(r.get(COL_STORE)), s(r.get(COL_KEY))
            if not store or not key:
                continue
            pk = "%s-%s" % (store, key)
            no = s(r.get(COL_SLIP_NO))
            dt = ymd(r.get(COL_SLIP_DATE))
            if not no and not dt:
                continue
            stats[label + "・値のある行"] += 1
            cur = picked.get(pk)
            # 伝票日付が新しい方を採る。日付が無い行は、まだ何も無い時だけ使う
            if cur is None or (dt and (not cur[1] or dt > cur[1])):
                picked[pk] = (no or (cur[0] if cur else ""), dt or (cur[1] if cur else None))
    print("\n元データで値のある商品キー: %s件" % format(len(picked), ","))

    # ── DBの商品と突き合わせる ──
    con = sqlite3.connect(DB)
    # ★列が無いと落ちるので、先に足しておく(サーバーを一度も起動していないPCでも動くように)。
    #   ensure_schema は冪等なので何度呼んでも安全
    db_query.ensure_schema(con)
    con.row_factory = sqlite3.Row
    have = {r["product_key"]: (s(r["purchase_slip_no"]), s(r["purchase_slip_date"]))
            for r in con.execute("SELECT product_key, purchase_slip_no, purchase_slip_date "
                                 "FROM products")}
    print("トキワの商品: %s件" % format(len(have), ","))

    plan_no, plan_date, skip_filled, not_found = [], [], 0, 0
    for pk, (no, dt) in picked.items():
        if pk not in have:
            not_found += 1
            continue
        cur_no, cur_dt = have[pk]
        if no and (a.overwrite or not cur_no):
            plan_no.append((no, pk))
        elif no and cur_no:
            skip_filled += 1
        if dt and (a.overwrite or not cur_dt):
            plan_date.append((dt, pk))

    print("\n──── 下読みの結果 ────")
    print("  納品書No を入れる商品 : %s件" % format(len(plan_no), ","))
    print("  伝票日付 を入れる商品 : %s件" % format(len(plan_date), ","))
    if skip_filled:
        print("  既に納品書Noが入っていて飛ばす: %s件(--overwrite で上書きできます)"
              % format(skip_filled, ","))
    if not_found:
        print("  ★元データにあるがトキワに無い商品キー: %s件" % format(not_found, ","))
        print("     (取込対象外だった商品。埋めようがないので飛ばします)")
    left = len(have) - len(plan_no)
    print("\n  ※商品は全部で %s件。納品書Noが入るのはその一部です" % format(len(have), ","))
    print("    (宝飾ナビ側でも入力されていない商品が多いため。空のままが %s件ほど残ります)"
          % format(max(0, left), ","))

    if not a.apply:
        print("\n下読みだけで終了しました。書き込むには --apply を付けてください。")
        con.close()
        return 0
    if not plan_no and not plan_date:
        print("\n書き込む内容がありません。")
        con.close()
        return 0

    # ── バックアップしてから書き込む ──
    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_納品書No前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)
    con = sqlite3.connect(DB)
    if plan_no:
        con.executemany("UPDATE products SET purchase_slip_no=? WHERE product_key=?", plan_no)
    if plan_date:
        con.executemany("UPDATE products SET purchase_slip_date=? WHERE product_key=?", plan_date)
    con.commit()
    n1 = con.execute("SELECT COUNT(*) FROM products WHERE COALESCE(purchase_slip_no,'')<>''").fetchone()[0]
    n2 = con.execute("SELECT COUNT(*) FROM products WHERE COALESCE(purchase_slip_date,'')<>''").fetchone()[0]
    print("書き込み完了。納品書Noが入っている商品: %s件 / 伝票日付: %s件"
          % (format(n1, ","), format(n2, ",")))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
