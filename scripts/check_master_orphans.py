# -*- coding: utf-8 -*-
"""各マスタの「孤立項目(使用件数=0)」を数える診断(読み取り専用)。

担当者・仕入先・商品分類・保管場所・支払方法の各マスタについて、登録されている項目が
実データで1件も使われていない(孤立している)ものが何件あるかを数え、名前を一覧する。
マスタ整理(不要な項目の削除)の目安に使う。

  python3 scripts/check_master_orphans.py         # 孤立項目名も表示(既定50件まで)
  python3 scripts/check_master_orphans.py 0        # 件数のみ(名前を出さない)

出力はマスタの項目名(商品分類・仕入先・担当者など業務マスタ)。顧客の個人情報は扱わない。
"""
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")

# 名前を最大何件まで表示するか(引数で変更可。0で非表示)
SHOW = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 50

# 担当者が紐づく列(名前で照合)
STAFF_USAGE = [("customers", "staff_name"), ("sales_slips", "staff_name"),
               ("approach_history", "staff_name"), ("prescriptions", "handler"),
               ("repairs", "staff_name")]

# 汎用/仕入先マスタ: (ラベル, 使用テーブル, 使用列, master_items種別 or None=仕入先, seed)
SIMPLE = [
    ("仕入先",   "products",      "supplier", None,        []),
    ("商品分類", "products",      "category", "category",  []),
    ("保管場所", "products",      "location", "location",  []),
    ("支払方法", "sale_payments", "method",   "pay_method", ["現金", "クレジット", "PayPay", "掛売", "分割"]),
]


def texists(con, t):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is not None


def usage(con, table, col, value):
    if not texists(con, table):
        return 0
    return con.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (value,)).fetchone()[0]


def report(label, items, usage_fn):
    """items: 項目名リスト。usage_fn(name)->使用件数。孤立(0件)を集計して表示。"""
    orphans = [n for n in items if usage_fn(n) == 0]
    print(f"■ {label}マスタ: 全 {len(items):,} 件 / 孤立(未使用) {len(orphans):,} 件")
    if orphans and SHOW:
        shown = orphans[:SHOW]
        print("   孤立項目: " + "、".join(str(x) for x in shown) + (f" …ほか{len(orphans) - len(shown)}件" if len(orphans) > len(shown) else ""))
    return len(orphans)


def main():
    if not os.path.exists(DB):
        sys.exit(f"DBがありません: {DB}")
    con = sqlite3.connect(DB)
    total_orphans = 0

    # 担当者
    if texists(con, "staff"):
        staff = [r[0] for r in con.execute("SELECT name FROM staff WHERE name IS NOT NULL")]
    else:
        staff = []
    def staff_usage(name):
        return sum(usage(con, t, c, name) for t, c in STAFF_USAGE)
    total_orphans += report("担当者", staff, staff_usage)

    # 仕入先・商品分類・保管場所・支払方法
    for label, utable, ucol, mtype, seed in SIMPLE:
        # 項目一覧: マスタテーブルがあればそれを、無ければ実データ(＋seed)から再構成
        items = []
        if mtype is None:  # 仕入先(supplier_master)
            if texists(con, "supplier_master"):
                items = [r[0] for r in con.execute("SELECT name FROM supplier_master")]
        else:  # master_items
            if texists(con, "master_items"):
                items = [r[0] for r in con.execute("SELECT name FROM master_items WHERE master_type=?", (mtype,))]
        if not items:  # マスタ未初期化 → 実データの重複なし値＋seedで代用
            data_vals = [r[0] for r in con.execute(
                f"SELECT {ucol} FROM {utable} WHERE {ucol} IS NOT NULL AND {ucol}<>'' GROUP BY {ucol}")] if texists(con, utable) else []
            items = sorted(set(data_vals) | set(seed))
        total_orphans += report(label, items, lambda n, ut=utable, uc=ucol: usage(con, ut, uc, n))

    con.close()
    print("-" * 40)
    print(f"■ 全マスタ合計の孤立項目: {total_orphans:,} 件")
    print("  ※孤立=そのマスタ項目が実データで1件も使われていない。削除の目安に。")
    print("  ※自動生成系(仕入先・分類・場所)は基本0。担当者や支払方法(初期候補)に出やすい。")


if __name__ == "__main__":
    main()
