# -*- coding: utf-8 -*-
"""催事(店外イベント)のあと、持ち出したDBに**何か書いていないか**を数えるだけの道具。

作った理由(2026-09-24 店の指定):
  催事は「案A=見るだけ」の運用(docs/event-offsite.md)。見るだけなら、帰ってきてから
  Macのデータを店へ戻す必要はなく、消して終わりでよい。ただしトキワはMacでも全機能が
  動いているので、**うっかり押せば書けてしまう**(お声がけの✓・会計・新規顧客など)。
  書いてしまったものに気づかず消すと、**その記録は店に残らないまま消える**。
  → 催事の日以降に作られた記録を数えて、0なら安心して消せるようにする。

★このスクリプトは**読むだけ**。DBには一切書き込まない(読み取り専用で開く)。
★個人情報は画面に出さない(顧客名・住所・電話は出さず、件数と日付・伝票番号だけ)。

使い方:
  python3 scripts/check_offsite_writes.py --since 2026-10-01
  python3 scripts/check_offsite_writes.py --since 2026-10-01 --db /path/to/tokiwa.db

  --since には**催事へ持ち出した日**(出発の日)を入れる。その日の0時以降に
  作られた記録を数える。
"""
import argparse
import os
import sqlite3
import sys
import unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE, "db", "tokiwa.db")

# (見出し, テーブル, 日付の列, 画面のどこを見るか)
# ★created_at がある表はそれを使う(=実際に書き込んだ日時なので確実)。
#   無い表は業務上の日付(発生日)で代用する。下の「調べきれないもの」を参照。
CHECKS = [
    ("売上(レジの会計)",       "sales_slips",        "created_at",   "顧客詳細 → 購入・アプローチ履歴"),
    ("売上の取消",             "sales_slips",        "voided_at",    "顧客詳細 → 購入・アプローチ履歴"),
    ("新しく登録した顧客",     "customers",          "created_at",   "顧客管理"),
    ("修理のお預かり",         "repairs",            "created_at",   "修理伝票"),
    ("お声がけの記録(✓)",     "approach_history",   "approach_date", "ホーム / 顧客詳細 → 購入・アプローチ履歴"),
    ("売掛・入金",             "receivable_entries", "entry_date",   "顧客詳細 → 入金管理"),
    ("ポイントの動き",         "point_transactions", "occurred_at",  "顧客詳細 → ポイント"),
    ("ポイント残高の書き換え", "point_balances",     "updated_at",   "顧客詳細 → ポイント"),
    ("レジ入出金",             "cash_movements",     "occurred_at",  "日報 → 入出金明細"),
    ("メガネ処方箋",           "prescriptions",      "rx_date",      "顧客詳細 → メガネ処方箋"),
    ("顧客メモ",               "customer_memos",     "updated_at",   "顧客詳細 → 基本情報"),
]


def pad(s, width):
    """全角は2文字ぶんとして桁をそろえる(日本語の見出しが揃わないと読みにくいため)。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in s)
    return s + " " * max(0, width - w)


def has_column(con, table, col):
    try:
        return col in [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
    except sqlite3.Error:
        return False


def main():
    ap = argparse.ArgumentParser(description="催事のあと、持ち出したDBに何か書いていないかを数える(読むだけ)")
    ap.add_argument("--since", required=True, help="催事へ持ち出した日 YYYY-MM-DD")
    ap.add_argument("--db", default=DEFAULT_DB, help="調べるDB(既定 db/tokiwa.db)")
    a = ap.parse_args()
    since = a.since.strip()
    if len(since) != 10 or since[4] != "-" or since[7] != "-":
        print("[エラー] 日付は 2026-10-01 の形で入れてください。")
        return 2
    if not os.path.exists(a.db):
        print("[エラー] DBが見つかりません: %s" % a.db)
        return 2

    # ★読み取り専用で開く(このスクリプトが書き換えることは仕組みとしてあり得ない)
    con = sqlite3.connect("file:%s?mode=ro" % a.db, uri=True)
    print("=" * 62)
    print(" 催事のあと確認 ― %s 以降に書かれた記録をさがします" % since)
    print(" 調べるDB: %s" % a.db)
    print(" ※読むだけです。このDBは一切書き換えません。")
    print("=" * 62)
    print()

    total = 0
    found = []
    skipped = []
    for label, table, col, where in CHECKS:
        if not has_column(con, table, col):
            skipped.append("%s(%s.%s が無い)" % (label, table, col))
            continue
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL AND date(%s) >= date(?)"
                % (table, col, col), (since,)).fetchone()[0]
        except sqlite3.Error as e:
            skipped.append("%s(%s)" % (label, e))
            continue
        total += int(n or 0)
        mark = "★" if n else "  "
        print("%s %s %4d 件" % (mark, pad(label, 30), n))
        if n:
            found.append((label, table, col, where, int(n)))
    print()

    if total == 0:
        print("=" * 62)
        print(" ★何も書かれていません(0件)。")
        print("   このMacのデータ(db/tokiwa.db)は、そのまま消して大丈夫です。")
        print("   次の催事では、また店のPCから新しいものをコピーしてください。")
        print("=" * 62)
    else:
        print("=" * 62)
        print(" ★%d件の記録が見つかりました。" % total)
        print("   このMacにだけ残っている記録です。**消す前に**中身を確かめ、")
        print("   本番機(店のPC)で入れ直してください。")
        print("   売上は レジの「過去の日付で登録する」で、催事当日の日付にして打ちます。")
        print("=" * 62)
        print()
        print(" 見つかった場所:")
        for label, table, col, where, n in found:
            print("   ・%s … %d件  → 画面では %s" % (label, n, where))
        print()
        # 中身をたどれるように、日付と番号だけ出す(氏名などは出さない)
        _detail(con, since, found)

    if skipped:
        print()
        print(" (この表は調べていません: %s)" % " / ".join(skipped))
    print()
    print(" ※この確認で分かるのは「%s 以降に**作られた**記録」です。" % since)
    print("   それより前の記録を**書き換えた**場合(顧客の住所を直した等)は分かりません。")
    con.close()
    return 0


def _detail(con, since, found):
    """見つかった記録を辿れるように、日付と番号だけ出す(氏名・金額の明細は出さない)。"""
    print(" 中身の手がかり(氏名は出しません):")
    for label, table, col, _where, _n in found:
        key = {"sales_slips": "slip_no", "repairs": "repair_no", "customers": "customer_id",
               "cash_movements": "category", "approach_history": "kind",
               "receivable_entries": "entry_type", "point_transactions": "tx_type",
               "prescriptions": "rx_no"}.get(table)
        cols = "date(%s)" % col + (", COALESCE(%s,'')" % key if key and has_column(con, table, key) else ", ''")
        try:
            rows = con.execute(
                "SELECT %s FROM %s WHERE %s IS NOT NULL AND date(%s) >= date(?) "
                "ORDER BY %s LIMIT 20" % (cols, table, col, col, col), (since,)).fetchall()
        except sqlite3.Error:
            continue
        print("   [%s]" % label)
        for d, k in rows:
            print("     %s  %s" % (d, k))
        if len(rows) == 20:
            print("     …(20件まで表示)")


if __name__ == "__main__":
    sys.exit(main())
