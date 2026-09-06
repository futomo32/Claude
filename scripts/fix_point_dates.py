# -*- coding: utf-8 -*-
"""ポイント履歴の日付を「処理日時」に直し、「お買上げ日」を別列に入れ直す(2026-09-06)。

作った理由:
  トキワのポイント履歴が **同じ日付ばかり**(あるお客様では「2011-09-02」が何十行も)
  並んでいた。宝飾ナビの同じ画面を見比べたところ、日付として出ているのは
  **処理日時(datinpdate)** の方で、トキワが取り込んでいたのは
  **お買上げ日(dathakko)** だった。お買上げ日は古い値のまま同じ日付が入り続ける
  ことがあるため、履歴が並べ替えも判別もできない状態になっていた。

  → 取込プログラム(import_csv.py)は直したが、**すでに取り込んだ分は直らない**。
    再取込は重く、9/2以降トキワで積んだ会計も混ざっているので、
    このスクリプトで**移行分だけ**を後から直す。

★安全のための決まり(この方針は他の埋め込みスクリプトと同じ):
  ・既定は「下読み」。何件直るかを出すだけで、データは1文字も変更しない。
  ・書き込むのは --apply を付けた時だけ。その直前に必ずバックアップを取る。
  ・少しでも食い違うお客様は **触らない**(飛ばして件数を報告する)。
    ずれたまま書き込むと、別の取引の日付を書いてしまい取り返しがつかない。
  ・個人情報は出さない(顧客IDと件数だけ。氏名は一切出さない)。

突き合わせのしかた:
  point_transactions には宝飾ナビの連番(lngpointseq)を保存していないため、
  **顧客ごとに「取込順」で1対1に対応づける**(取込は d_pointhistory.csv の
  行順にINSERTしているので、id の昇順＝CSVの行順になる)。
  そのうえで、各ペアの **加算・使用・残高が完全に一致すること**を確かめ、
  1つでも違えばそのお客様は丸ごと飛ばす。

使い方:
  python3 scripts/fix_point_dates.py            # 下読み(何件直るか見るだけ)
  python3 scripts/fix_point_dates.py --apply    # バックアップしてから書き込む
  python3 scripts/fix_point_dates.py --kbn      # 区分コードの内訳を出す(日本語化の検討用)
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
SRC = "d_pointhistory"
# トキワ自身が作る区分。これが付いている行は移行分ではないので絶対に触らない
TOKIWA_KINDS = {"加算", "使用", "手動修正", "返品調整", "統合", "顧客変更", "失効", "サービス", "調整"}


def s(v):
    return unicodedata.normalize("NFKC", "" if v is None else str(v)).strip()


def num(v):
    """「1,320」「1320.0」→ 1320。読めなければ0。"""
    t = s(v).replace(",", "")
    if not t:
        return 0
    try:
        return int(float(t))
    except ValueError:
        return 0


def ymd(v):
    """「2026/05/31 11:29:00」→「2026-05-31」。読めない値は None。"""
    t = s(v).split(" ")[0].replace("/", "-")
    p = t.split("-")
    if len(p) != 3 or not all(x.isdigit() for x in p):
        return None
    y, m, d = int(p[0]), int(p[1]), int(p[2])
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return "%04d-%02d-%02d" % (y, m, d)


def read_source(path):
    """CSVを行のリストで返す。宝飾ナビの書き出しは cp932/utf-8-sig のどちらもある。"""
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    print("  [読めません] 文字コードを判定できませんでした: %s" % path)
    return []


def main():
    ap = argparse.ArgumentParser(description="ポイント履歴の日付を処理日時に直す(既定は下読み)")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読みのみ)")
    ap.add_argument("--kbn", action="store_true",
                    help="区分コード(lngpointkbn)の内訳を出す。日本語化の対応表を作る検討用")
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

    # ── CSVを顧客ごとに、ファイルの並び順のまま束ねる ──
    by_cust = collections.OrderedDict()
    kbn_stat = collections.Counter()
    kbn_shape = collections.defaultdict(collections.Counter)
    for r in rows:
        store, key = s(r.get("strkotencode")), s(r.get("lngkokey"))
        if not store or not key:
            continue
        cid = "%s-%s" % (store, key)
        add, use = num(r.get("curkasanpoint")), num(r.get("curusepoint"))
        kbn = s(r.get("lngpointkbn"))
        kbn_stat[kbn] += 1
        kbn_shape[kbn]["加算あり" if add else ("使用あり" if use else "どちらも0")] += 1
        by_cust.setdefault(cid, []).append({
            "kbn": kbn, "add": add, "use": use, "bal": num(r.get("curzanpoint")),
            "when": ymd(r.get("datinpdate")), "bought": ymd(r.get("dathakko"))})

    if a.kbn:
        print("\n=== 区分コード(lngpointkbn)の内訳 ===")
        print("  ※日本語化の対応表を決めるための材料。宝飾ナビの画面(繰越/修正/購入…)と見比べる")
        for k, c in kbn_stat.most_common():
            shape = " / ".join("%s×%s" % (a2, format(b, ",")) for a2, b in kbn_shape[k].most_common())
            print("  区分 %-6s %8s件   %s" % (k or "(空)", format(c, ","), shape))

    # ── DBの移行分と突き合わせる ──
    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)     # bought_at 列が無いPCでも動くように(冪等)
    con.row_factory = sqlite3.Row
    db_rows = collections.OrderedDict()
    for r in con.execute("""SELECT id, customer_id, tx_type, COALESCE(add_points,0) a,
                                   COALESCE(use_points,0) u, balance, occurred_at, bought_at
                            FROM point_transactions ORDER BY customer_id, id"""):
        if s(r["tx_type"]) in TOKIWA_KINDS:
            continue                                  # トキワで積んだ分は対象外
        db_rows.setdefault(str(r["customer_id"]), []).append(r)
    print("トキワの移行分ポイント履歴: %s件 / %s人"
          % (format(sum(len(v) for v in db_rows.values()), ","), format(len(db_rows), ",")))

    plan = []
    skip_count, skip_len, skip_mismatch, no_csv = 0, 0, 0, 0
    for cid, drows in db_rows.items():
        crows = by_cust.get(cid)
        if not crows:
            no_csv += 1
            skip_count += len(drows)
            continue
        if len(crows) != len(drows):
            skip_len += 1
            skip_count += len(drows)
            continue
        # 1行ずつ、加算・使用・残高が一致するか確かめる(1つでも違えばこのお客様は触らない)
        if any(int(d["a"]) != c["add"] or int(d["u"]) != c["use"]
               or int(d["balance"] or 0) != c["bal"] for d, c in zip(drows, crows)):
            skip_mismatch += 1
            skip_count += len(drows)
            continue
        for d, c in zip(drows, crows):
            if c["when"] and (s(d["occurred_at"]) != c["when"] or s(d["bought_at"]) != s(c["bought"])):
                plan.append((c["when"], c["bought"], d["id"]))

    print("\n直す行: %s件" % format(len(plan), ","))
    print("  触らない行: %s件" % format(skip_count, ","))
    print("    ・CSVに履歴が無いお客様: %s人" % format(no_csv, ","))
    print("    ・件数が合わないお客様: %s人" % format(skip_len, ","))
    print("    ・中身(加算/使用/残高)が合わないお客様: %s人" % format(skip_mismatch, ","))
    if skip_count:
        print("  ※飛ばした分は今までどおりの日付のまま残ります(消えたりはしません)。")

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
    bak = os.path.join(bdir, "tokiwa_ポイント日付前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)
    con = sqlite3.connect(DB)
    con.executemany("UPDATE point_transactions SET occurred_at=?, bought_at=? WHERE id=?", plan)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM point_transactions "
                    "WHERE COALESCE(bought_at,'')<>''").fetchone()[0]
    print("書き込み完了。お買上げ日が入っている履歴: %s件" % format(n, ","))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
