# -*- coding: utf-8 -*-
"""移行の答え合わせ: 元CSVにあるのにトキワに入っていないものを、全表で洗い出す(2026-09-17)。

作った理由:
  2026-09-16、**全顧客の古い購入履歴 108,487件(31億円)が消えていた**ことが分かった。
  宝飾ナビが2011年から伝票番号を振り始めており、それ以前は `curdenpyono = 0`。
  取込がこの「0」を伝票番号として扱ったため、全部が1枚の伝票に潰れていた。
  **たまたま宝飾ナビが残っていたので気づけただけ**で、同じ型の取りこぼしが他にも
  あるかは誰にも分からない状態だった。

  取込プログラムを読むと、行を落とす条件が次のとおりある:
    ・顧客: 店舗コードか顧客キーが空 / 同じキーの2件目
    ・商品: 商品キーが空 / 同じキーの2件目 / 削除リストに当たった在庫品(意図的)
    ・**メモ・家族・売掛・入金・ポイント・処方箋は「その顧客が取り込めていなければ丸ごと落とす」**
      → 顧客が1人落ちると、その人の記録が芋づる式に落ちる。しかも黙って。
  この道具は、その結果を**キーの集合**で突き合わせて数える。

★読むだけ。データは1文字も変更しない。
★個人情報は出さない(件数と、キー(顧客ID・商品キー)だけ。氏名は一切出さない)。
★「意図的に入れていないもの」は別枠にして、**説明のつかない差だけ**が残るようにしてある。

使い方:
  python3 scripts/diag_import_gaps.py           # 全部の検査
  python3 scripts/diag_import_gaps.py --list    # 説明のつかないキーを少しだけ並べる
"""
import argparse
import collections
import csv
import os
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(BASE, "server"))
import _paths  # noqa: E402

REAL_BASE = os.path.join(BASE, "data", "real")
SAMPLE = 8       # --list で並べるキーの数


def s(v):
    return unicodedata.normalize("NFKC", "" if v is None else str(v)).strip()


def key_of(r, tc, kc):
    t, k = s(r.get(tc)), s(r.get(kc))
    return ("%s-%s" % (t, k)) if (t and k) else None


def stream(path):
    """CSVを1行ずつ返す(20万行の表があるので貯めない)。"""
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline()
            f.seek(0)
            break
        except UnicodeDecodeError:
            continue
    else:
        print("  [読めません] %s" % path)
        return
    try:
        for row in csv.DictReader(f):
            yield row
    finally:
        f.close()


def main():
    ap = argparse.ArgumentParser(description="元CSVにあるのに入っていないものを洗い出す(読むだけ)")
    ap.add_argument("--list", action="store_true", help="説明のつかないキーを少しだけ並べる")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1
    csv_dir = _paths.find_dir(REAL_BASE, "*.csv", "csv")

    def csv_path(name):
        p = os.path.join(csv_dir, name + ".csv")
        return p if os.path.exists(p) else None

    print("読むだけの検査です。データは1文字も変更しません。")
    print("元CSV: %s" % csv_dir)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    findings = []      # (重大度, 見出し, 説明)

    # ── 1. 顧客 ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("■ 顧客(d_user → customers)")
    db_cust = set(r[0] for r in con.execute("SELECT customer_id FROM customers"))
    csv_cust, dup_cust, nokey_cust = set(), 0, 0
    p = csv_path("d_user")
    if p:
        for r in stream(p):
            cid = key_of(r, "strkotencode", "lngkokey")
            if not cid:
                nokey_cust += 1
            elif cid in csv_cust:
                dup_cust += 1
            else:
                csv_cust.add(cid)
    miss_cust = csv_cust - db_cust
    print("  CSVの顧客: %s人 / トキワ: %s人" % (format(len(csv_cust), ","), format(len(db_cust), ",")))
    print("  ・キーが空で数えられない行: %s件" % format(nokey_cust, ","))
    print("  ・同じキーが2度以上出た行(2件目以降を捨てている): %s件" % format(dup_cust, ","))
    print("  ★CSVにあるのにトキワに無い顧客: %s人" % format(len(miss_cust), ","))
    if miss_cust:
        findings.append(("★", "顧客", "%s人がトキワに入っていない" % format(len(miss_cust), ",")))
        if a.list:
            print("    例: %s" % " / ".join(sorted(miss_cust)[:SAMPLE]))

    # ── 2. 顧客にぶら下がるもの(顧客が落ちると芋づる式に落ちる) ──
    print("\n" + "=" * 60)
    print("■ 顧客にぶら下がるもの(★その顧客が居ないと丸ごと落ちる作り)")
    chain = [
        ("d_user_memo", "顧客メモ", "SELECT COUNT(*) FROM customer_memos", None),
        ("d_famiry", "家族", "SELECT COUNT(*) FROM customer_families", None),
        ("d_shohosen", "処方箋", "SELECT COUNT(*) FROM prescriptions", None),
        ("d_pointhistory", "ポイント履歴", "SELECT COUNT(*) FROM point_transactions", None),
    ]
    for name, label, sql, _x in chain:
        p = csv_path(name)
        if not p:
            print("  %s: CSVがありません" % label)
            continue
        total, lost_cust = 0, 0
        for r in stream(p):
            cid = key_of(r, "strkotencode", "lngkokey")
            if name == "d_shohosen":
                cid = key_of(r, "strkotencode", "lngkokey")
            total += 1
            if not cid or cid not in db_cust:
                lost_cust += 1
        db_n = con.execute(sql).fetchone()[0]
        # 顧客メモは1行に memo01〜10 が入るので件数の単位が違う(参考値として出す)
        unit = "行" if name != "d_user_memo" else "行(1行に最大10件のメモ)"
        print("  %s: CSV %s%s → トキワ %s件" % (label, format(total, ","), unit, format(db_n, ",")))
        if lost_cust:
            print("    ★顧客が居ないため落ちた行: %s件" % format(lost_cust, ","))
            findings.append(("★", label, "顧客が居ないため %s行 が落ちている" % format(lost_cust, ",")))

    # ── 3. 商品 ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("■ 商品(d_item → products)")
    db_prod = set(r[0] for r in con.execute("SELECT product_key FROM products"))
    csv_prod, dup_prod, nokey_prod = set(), 0, 0
    p = csv_path("d_item")
    if p:
        for r in stream(p):
            pk = key_of(r, "strsytencode", "lngsykey")
            if not pk:
                nokey_prod += 1
            elif pk in csv_prod:
                dup_prod += 1
            else:
                csv_prod.add(pk)
    miss_prod = csv_prod - db_prod
    print("  CSVの商品: %s件 / トキワ: %s件" % (format(len(csv_prod), ","), format(len(db_prod), ",")))
    print("  ・キーが空: %s件 / 同じキーの2件目以降: %s件"
          % (format(nokey_prod, ","), format(dup_prod, ",")))
    print("  CSVにあるのにトキワに無い商品: %s件" % format(len(miss_prod), ","))
    print("    ※このうち**削除リストで意図的に外した在庫品**が含まれます(想定どおり)。")
    print("      それを大きく超えるようなら、別の理由で落ちています。")
    if a.list and miss_prod:
        print("    例: %s" % " / ".join(sorted(miss_prod)[:SAMPLE]))

    # ── 4. 売上 ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("■ 売上(d_hanbai → sale_lines)")
    p = csv_path("d_hanbai")
    csv_lines, lost_cust_sale, no_date = 0, 0, 0
    if p:
        for r in stream(p):
            csv_lines += 1
            cid = key_of(r, "strkotencode", "lngkokey")
            if not cid or cid not in db_cust:
                lost_cust_sale += 1
    db_lines = con.execute("SELECT COUNT(*) FROM sale_lines").fetchone()[0]
    print("  CSVの明細: %s行 → トキワ: %s件" % (format(csv_lines, ","), format(db_lines, ",")))
    diff = csv_lines - db_lines
    print("  差: %s件" % format(diff, ","))
    print("  ・顧客が居ないため持ち主なしで入る行: %s件(消えてはいない)" % format(lost_cust_sale, ","))
    if abs(diff) > 100:
        findings.append(("★", "売上明細",
                         "CSVとトキワで %s件の差(伝票0番の入れ直しが未実施なら想定どおり)"
                         % format(diff, ",")))

    # ── 5. あり得ない形の検査(元CSVを見なくても分かる異常) ──
    print("\n" + "=" * 60)
    print("■ あり得ない形の検査(DBだけで分かる異常)")
    nocust = con.execute("SELECT COUNT(*) FROM sales_slips WHERE customer_id IS NULL").fetchone()[0]
    print("  ・持ち主(顧客)が空の伝票: %s枚" % format(nocust, ","))
    if nocust:
        findings.append(("★", "伝票", "持ち主が空の伝票が %s枚" % format(nocust, ",")))
    big = list(con.execute("""SELECT s.slip_id, s.slip_no, s.sold_at, COUNT(*) n
                              FROM sale_lines l JOIN sales_slips s ON s.slip_id = l.slip_id
                              GROUP BY l.slip_id HAVING n >= 50 ORDER BY n DESC LIMIT 5"""))
    print("  ・明細が50件以上ぶら下がっている伝票: %s枚" % format(len(big), ","))
    for b in big:
        print("      伝票 #%s(番号 %s / %s) … %s件"
              % (b["slip_id"], b["slip_no"] or "なし", b["sold_at"], format(b["n"], ",")))
        findings.append(("★", "伝票", "伝票 #%s に明細が %s件 集まっている"
                         % (b["slip_id"], format(b["n"], ","))))
    orphans = [
        ("親の伝票が無い売上明細",
         "SELECT COUNT(*) FROM sale_lines l LEFT JOIN sales_slips s ON s.slip_id=l.slip_id WHERE s.slip_id IS NULL"),
        ("顧客が居ない処方箋",
         "SELECT COUNT(*) FROM prescriptions rx LEFT JOIN customers c ON c.customer_id=rx.customer_id WHERE c.customer_id IS NULL"),
        ("顧客が居ないポイント履歴",
         "SELECT COUNT(*) FROM point_transactions t LEFT JOIN customers c ON c.customer_id=t.customer_id WHERE c.customer_id IS NULL"),
        ("顧客が居ない売掛",
         "SELECT COUNT(*) FROM receivables r LEFT JOIN customers c ON c.customer_id=r.customer_id WHERE c.customer_id IS NULL"),
    ]
    for label, sql in orphans:
        try:
            k = con.execute(sql).fetchone()[0]
        except sqlite3.Error as e:
            print("  ・%s: 調べられません(%s)" % (label, str(e)[:60]))
            continue
        print("  ・%s: %s件" % (label, format(k, ",")))
        if k:
            findings.append(("★", label, "%s件" % format(k, ",")))

    # ── まとめ ────────────────────────────────────────────
    print("\n" + "=" * 60)
    if findings:
        print("★気になるもの: %s件" % len(findings))
        for mark, what, why in findings:
            print("  %s %s … %s" % (mark, what, why))
        print("\n  ※「売掛」はお店が全件削除して紙の台帳から手入力した運用なので、")
        print("    CSVとの差は**意図的**です(ここでは検査していません)。")
        print("  ※商品の差には**削除リストで外した在庫品**が含まれます(意図的)。")
    else:
        print("  気になるものはありませんでした。")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
