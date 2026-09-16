# -*- coding: utf-8 -*-
"""「伝票0番」にまとまってしまった古い売上を、正しい顧客・正しい買上日で入れ直す(2026-09-16)。

何が起きていたか:
  宝飾ナビは **2011年から伝票番号(YYMMDD+連番)を振り始めており、それ以前の売上は
  すべて `curdenpyono = 0`** が入っている。取込プログラムはこの「0」を伝票番号として
  扱っていたため、**全顧客の2011年より前の売上が「伝票0番」という1枚の伝票に
  まとめられ、最初に出てきた1人のお客様にだけ紐づいて**いた。
  その結果:
    ・他のお客様の**2011年より前の購入履歴が丸ごと消えていた**
    ・買上日もその1枚の日付に潰れていた(1994年の品も2010年の品も同じ日付)
    ・累計購入額・顧客ランク・DM抽出まで狂っていた
  実例: 河野様は宝飾ナビ ¥6,698,110 に対しトキワ ¥4,456,810(差 ¥2,241,300 = 欠けた9件)。

  取込プログラム(import_csv.py)は 2026-09-16 に直したが、**すでに入っているDBは
  直らない**ので、この道具で入れ直す。

★再取込はしない:
  再取込すると 9/2 以降にトキワで打った売上・ポイント・処方箋まで消えてしまう。
  ここでは **「伝票0番」の伝票と、その明細だけ**を消して、CSVから入れ直す。
  在庫・ポイント・売掛・処方箋には**一切触らない**。

★安全のための決まり:
  ・既定は「下読み」。何件消して何件入れるかを出すだけで、データは1文字も変更しない。
  ・書き込むのは --apply を付けた時だけ。その直前に必ずバックアップを取る。
  ・**伝票番号が入っている伝票には触らない**(2011年以降とトキワの売上は無傷)。
  ・個人情報は出さない(顧客IDと件数・金額だけ。氏名は出さない)。

使い方:
  python3 scripts/fix_slip_zero.py            # 下読み(何が起きるか見るだけ)
  python3 scripts/fix_slip_zero.py --apply    # バックアップしてから入れ直す
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
SRC = "d_hanbai"
ZERO_VALUES = {"0", "0.0", "-0", ""}     # 伝票番号として扱わない値
# 支払方法・カード種別・担当者。★import_csv.py と同じ対応表にすること
# (違う値で入れ直すと、同じ移行データなのに画面の表示が行によって変わってしまう)
KAKE = {"1": "現金", "2": "掛売", "3": "クレジット", "4": "分割",
        "5": "クレジットローン", "6": "トレジャリーカード"}
CREDIT = {"1": "JCB", "2": "VISA", "3": "UFJミリオン", "7": "TS3",
          "8": "セディナ", "9": "オリエント", "A": "山陰信販", "B": "オリコ"}


def s(v):
    return unicodedata.normalize("NFKC", "" if v is None else str(v)).strip()


def n(v):
    t = s(v).replace(",", "")
    if not t:
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def dt(v):
    """「2008/6/22 0:00」→「2008-06-22」。読めない値は None。"""
    t = s(v).split(" ")[0].replace("/", "-")
    p = t.split("-")
    if len(p) != 3 or not all(x.isdigit() for x in p):
        return None
    y, m, d = int(p[0]), int(p[1]), int(p[2])
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return "%04d-%02d-%02d" % (y, m, d)


def read_rows(path):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    print("  [読めません] 文字コードを判定できませんでした: %s" % path)
    return []


def main():
    ap = argparse.ArgumentParser(description="伝票0番にまとまった古い売上を入れ直す(既定は下読み)")
    ap.add_argument("--apply", action="store_true", help="実際に入れ直す(既定は下読みのみ)")
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
    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)
    con.row_factory = sqlite3.Row

    # ── いま「伝票0番」になっている伝票を調べる ──
    bad = list(con.execute("""SELECT slip_id, customer_id, sold_at,
                                     (SELECT COUNT(*) FROM sale_lines l WHERE l.slip_id = s.slip_id) n,
                                     (SELECT COALESCE(SUM(amount),0) FROM sale_lines l
                                       WHERE l.slip_id = s.slip_id) amt
                              FROM sales_slips s
                              WHERE TRIM(COALESCE(s.slip_no,'')) IN ('0','0.0','-0')"""))
    print("\n=== いまのDB ===")
    if not bad:
        print("  「伝票0番」の伝票はありません。")
        print("  (すでに直っているか、この不具合が起きていないDBです)")
    for b in bad:
        print("  伝票 #%s … 持ち主 %s / 日付 %s / 明細 %s件 / 合計 ¥%s"
              % (b["slip_id"], b["customer_id"], b["sold_at"],
                 format(b["n"], ","), format(int(b["amt"] or 0), ",")))
    del_lines = sum(int(b["n"] or 0) for b in bad)

    # ── CSVから「伝票番号なし」の行を読む ──
    rows = read_rows(path)
    print("\n=== 元のCSV(%s.csv %s行) ===" % (SRC, format(len(rows), ",")))
    known = set(r[0] for r in con.execute("SELECT customer_id FROM customers"))
    pkeys = set(r[0] for r in con.execute("SELECT product_key FROM products"))
    # 担当者コード→名前(トキワの担当者マスタから。移行時と同じ名前で入るように)
    staff_of = {s(r[0]): r[1] for r in con.execute(
        "SELECT staff_code, name FROM staff WHERE COALESCE(staff_code,'')<>''")}

    plan = collections.OrderedDict()   # (cid, 買上日) → [行,...]
    no_cust, no_date = 0, 0
    years = collections.Counter()
    for r in rows:
        if s(r.get("curdenpyono")) not in ZERO_VALUES:
            continue                                  # 伝票番号がある=触らない
        store, key = s(r.get("strkotencode")), s(r.get("lngkokey"))
        cid = ("%s-%s" % (store, key)) if (store and key) else None
        sold = dt(r.get("datkaidate")) or dt(r.get("datcredate"))
        if not cid or cid not in known:
            no_cust += 1
            continue
        if not sold:
            no_date += 1
            continue
        years[sold[:4]] += 1
        plan.setdefault((cid, sold), []).append(r)

    n_lines = sum(len(v) for v in plan.values())
    custs = set(k[0] for k in plan)
    amt = sum(n(r.get("curkaikin")) or 0 for v in plan.values() for r in v)
    print("  伝票番号なし(0)の行: %s件" % format(n_lines + no_cust + no_date, ","))
    print("    ・入れ直せる: %s件 (¥%s) / 伝票 %s枚 / お客様 %s人"
          % (format(n_lines, ","), format(amt, ","), format(len(plan), ","), format(len(custs), ",")))
    print("    ・トキワに居ないお客様: %s件(入れません)" % format(no_cust, ","))
    print("    ・買上日が読めない: %s件(入れません)" % format(no_date, ","))
    if years:
        ys = sorted(years)
        print("    ・年の範囲: %s 〜 %s" % (ys[0], ys[-1]))

    print("\n=== やること ===")
    print("  1. 「伝票0番」の伝票 %s枚 とその明細 %s件 を消す"
          % (format(len(bad), ","), format(del_lines, ",")))
    print("  2. CSVから %s件 を、正しいお客様・正しい買上日で入れ直す" % format(n_lines, ","))
    print("  ※伝票番号が入っている伝票(2011年以降・トキワの売上)には触りません。")
    print("  ※在庫・ポイント・売掛・処方箋にも触りません。")
    if not bad and not n_lines:
        con.close()
        return 0

    if not a.apply:
        print("\n下読みだけで終了しました。入れ直すには --apply を付けてください。")
        con.close()
        return 0

    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_伝票0番の修復前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)

    con = sqlite3.connect(DB)
    cur = con.cursor()
    ids = [b["slip_id"] for b in bad]
    for sid in ids:
        cur.execute("DELETE FROM sale_lines WHERE slip_id=?", (sid,))
        cur.execute("DELETE FROM sales_slips WHERE slip_id=?", (sid,))
    print("消しました: 伝票 %s枚 / 明細 %s件" % (format(len(ids), ","), format(del_lines, ",")))

    made = 0
    for (cid, sold), items in plan.items():
        r0 = items[0]
        tan = s(r0.get("strhantancode"))
        cur.execute("""INSERT INTO sales_slips
                       (slip_no,customer_id,staff_code,staff_name,store_code,sold_at,
                        pay_method,credit_kind,used_points,earned_points)
                       VALUES (NULL,?,?,?,?,?,?,?,?,?)""",
                    (cid, tan, staff_of.get(tan), s(r0.get("strkotencode")), sold,
                     KAKE.get(s(r0.get("strkakekbn"))),
                     CREDIT.get(s(r0.get("strcrekbn")), s(r0.get("strcrekbn")) or None),
                     n(r0.get("curusepoint")) or 0, n(r0.get("curkasanpoint")) or 0))
        sid = cur.lastrowid
        for r in items:
            store, key = s(r.get("strsytencode")), s(r.get("lngsykey"))
            pk = ("%s-%s" % (store, key)) if (store and key) else None
            if pk not in pkeys:
                pk = None                     # 商品台帳に無い商品は紐付けない(品名は空)
            try:
                rate = float(s(r.get("curwariritu")).replace("%", "")) if s(r.get("curwariritu")) else None
            except ValueError:
                rate = None
            cur.execute("""INSERT INTO sale_lines
                           (slip_id,product_key,free_name,info,list_price,amount,tax,discount_rate)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (sid, pk, None, s(r.get("strsyinfo")) or None,
                         n(r.get("curteika")), n(r.get("curkaikin")),
                         n(r.get("curkaizeikin")), rate))
            made += 1
    con.commit()
    print("入れ直しました: 伝票 %s枚 / 明細 %s件" % (format(len(plan), ","), format(made, ",")))
    print("\n※顧客の累計購入額は売上から計算しているので、画面を開き直せば正しくなります。")
    print("※顧客ランクは金額が変わった分、必要なら『顧客ランク更新』を流し直してください。")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
