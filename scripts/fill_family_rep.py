# -*- coding: utf-8 -*-
"""宝飾ナビの「代表フラグ」を顧客に埋める(2026-09-10)。

作った理由:
  宝飾ナビには**代表フラグ**があり、家族5人でも代表(奥様など)にだけ印を付けておくと、
  DMを1通に絞れた。トキワには項目自体が無かったので v1.4.20 で作り
  (`customers.is_family_rep`)、複合検索の条件「代表フラグ」でも絞れるようにした。
  **過去の印は移行時に取り込んでいない**ので、このスクリプトで後から埋める。

  元データ: `d_user.lngdaihyoflg`(74列のうち52番目)。
  Access/宝飾ナビの真偽値は **-1 が真**(True)、0 が偽。1 を真として書き出す実装も
  あるため、**-1 と 1 の両方を「代表」として扱う**(片方だけ見ると全員が代表でない
  ことになり、印が全部消える)。

★安全のための決まり:
  ・既定は「下読み」。何件入るかを出すだけで、データは1文字も変更しない。
  ・書き込むのは --apply を付けた時だけ。その直前に必ずバックアップを取る。
  ・**トキワで既に印を付け直した人は触らない**(店の操作を上書きしないため)。
    ただし移行直後は全員が未設定(NULL)なので、初回は全員が対象になる。
    上書きしたい時だけ --overwrite を付ける。
  ・個人情報は出さない(件数だけ。氏名は一切出さない)。

使い方:
  python3 scripts/fill_family_rep.py            # 下読み(何件入るか見るだけ)
  python3 scripts/fill_family_rep.py --apply    # バックアップしてから書き込む
"""
import argparse
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
SRC = "d_user"
COL_FLAG = "lngdaihyoflg"       # 代表フラグ
COL_STORE = "strkotencode"      # 顧客キーは「店舗コード-顧客キー」で作る
COL_KEY = "lngkokey"
TRUE_VALUES = {"-1", "1"}       # ★Accessの真は -1。1 で書き出す実装もあるので両方見る


def s(v):
    return unicodedata.normalize("NFKC", "" if v is None else str(v)).strip()


def read_source(path):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    print("  [読めません] 文字コードを判定できませんでした: %s" % path)
    return []


def main():
    ap = argparse.ArgumentParser(description="代表フラグを顧客に埋める(既定は下読み)")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読みのみ)")
    ap.add_argument("--overwrite", action="store_true",
                    help="トキワで印を付け直した人も上書きする(既定は未設定の人だけ)")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1
    csv_dir = _paths.find_dir(REAL_BASE, "*.csv", "csv")
    path = os.path.join(csv_dir, SRC + ".csv")
    if not os.path.exists(path):
        print("%s.csv がありません: %s" % (SRC, path))
        return 1

    print("読むだけの下読みです(--apply を付けるまでデータは変更しません)。")
    rows = read_source(path)
    print("%s.csv: %s行" % (SRC, format(len(rows), ",")))
    if rows and COL_FLAG not in rows[0]:
        print("  [中止] 列 %s が見つかりません。列名が違う可能性があります。" % COL_FLAG)
        print("  この表の列: %s" % " / ".join(list(rows[0].keys())[:20]))
        return 1

    # 値の内訳を必ず出す(「全部0だった」等をその場で見抜けるようにする)
    kinds = {}
    reps = set()
    for r in rows:
        v = s(r.get(COL_FLAG))
        kinds[v or "(空)"] = kinds.get(v or "(空)", 0) + 1
        store, key = s(r.get(COL_STORE)), s(r.get(COL_KEY))
        if v in TRUE_VALUES and store and key:
            reps.add("%s-%s" % (store, key))
    print("\n%s の値の内訳:" % COL_FLAG)
    for k, c in sorted(kinds.items(), key=lambda x: -x[1]):
        mark = " ← 代表として扱う" if k in TRUE_VALUES else ""
        print("  %-8s %8s件%s" % (k, format(c, ","), mark))
    print("\n代表の印が付いている顧客: %s人" % format(len(reps), ","))
    if not reps:
        print("  ※1人もいません。宝飾ナビ側で使われていなかったか、列が違う可能性があります。")

    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)      # is_family_rep 列が無いDBでも動くように(冪等)
    con.row_factory = sqlite3.Row
    have = {r["customer_id"]: r["is_family_rep"]
            for r in con.execute("SELECT customer_id, is_family_rep FROM customers")}
    print("トキワの顧客: %s人" % format(len(have), ","))

    plan, not_found, skip_set = [], 0, 0
    for cid in reps:
        if cid not in have:
            not_found += 1           # 移行で外れた顧客(削除リスト等)
            continue
        if have[cid] is not None and not a.overwrite:
            skip_set += 1            # トキワで既に印を触っている人
            continue
        if have[cid] == 1:
            skip_set += 1
            continue
        plan.append((1, cid))

    print("\n印を付ける: %s人" % format(len(plan), ","))
    print("  ・トキワに居ない顧客: %s人" % format(not_found, ","))
    print("  ・すでに印がある/トキワで設定済み: %s人" % format(skip_set, ","))
    print("  ※印が付いていない人は触りません(0を書き込むこともしません)。")

    if not a.apply:
        print("\n下読みだけで終了しました。書き込むには --apply を付けてください。")
        con.close()
        return 0
    if not plan:
        print("\n書き込む内容がありません。")
        con.close()
        return 0

    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_代表フラグ前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)
    con = sqlite3.connect(DB)
    con.executemany("UPDATE customers SET is_family_rep=? WHERE customer_id=?", plan)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM customers "
                    "WHERE COALESCE(is_family_rep,0)=1").fetchone()[0]
    print("書き込み完了。代表の印が付いている顧客: %s人" % format(n, ","))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
