# -*- coding: utf-8 -*-
"""取り込んだDBの中身を後から確認する(読み取り専用・何も変更しない)。

取込の最後に出る確認と同じことを、**取込をやり直さずに**もう一度見るための道具。
2026-09-01、`--no-receivables` を付けた時に取込の最後の表示だけが落ちる不具合があり、
DBは正常なのに確認結果が見られなかったため用意した。

  python3 scripts/verify_import.py

出すのは件数と整合性だけ。**顧客名などの個人情報は表示しない。**
"""
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")

# 主要テーブルの件数
TABLES = ["stores", "staff", "customers", "customer_memos", "customer_families",
          "products", "sales_slips", "sale_lines", "receivables", "receivable_entries",
          "point_balances", "point_transactions", "prescriptions", "app_users"]

# 2026-09-01の取込で追加した4項目(go-live-checklist の確認と同じ)
NEW_COLS = [("products", "tag_name", "タグ品名", 48),
            ("products", "sub_category", "中分類", 96),
            ("products", "sub_stone", "脇石", 33),
            ("products", "sub_carat1", "脇石重量", 41),
            ("customers", "dm_note", "DM備考", 33)]


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        sys.exit(1)
    con = sqlite3.connect(DB)
    print(f"対象DB: {os.path.abspath(DB)}  ({os.path.getsize(DB)/1024/1024:.1f}MB)\n")

    print("== 件数 ==")
    for t in TABLES:
        try:
            print(f"  {t:22s}: {con.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]:,}")
        except sqlite3.Error as e:
            print(f"  {t:22s}: (読めません: {e})")

    print("\n== 商品の状態 ==")
    for st, c in con.execute("""SELECT COALESCE(state,'(なし)'), COUNT(*) FROM products
                                GROUP BY state ORDER BY 2 DESC"""):
        print(f"  {st:8s}: {c:,}")

    print("\n== 顧客メモ(番号ごと) ==")
    rows = list(con.execute("SELECT seq, COUNT(*) FROM customer_memos GROUP BY seq ORDER BY seq"))
    print("  " + " / ".join(f"{s}:{c:,}" for s, c in rows) if rows else "  (なし)")

    print("\n== 2026-09-01に追加した項目(0件なら取り込めていない) ==")
    for tbl, col, label, target in NEW_COLS:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE COALESCE({col},'')<>''").fetchone()[0]
            tot = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            pct = (n * 100 / tot) if tot else 0
            mark = "★0件です" if n == 0 else ("" if abs(pct - target) < 15 else "※目安と離れています")
            print(f"  {label:8s}({col:12s}): {n:>8,} 件 / {pct:5.1f}%  目安{target}%  {mark}")
        except sqlite3.Error as e:
            print(f"  {label:8s}({col:12s}): (読めません: {e})")

    print("\n== 売上明細の品名 ==")
    # ★v0.35.7の確認: 商品が消えている明細に、商品名が残っているか
    q = """SELECT
             SUM(CASE WHEN l.product_key IS NOT NULL THEN 1 ELSE 0 END),
             SUM(CASE WHEN l.product_key IS NULL AND COALESCE(l.free_name,'')<>'' THEN 1 ELSE 0 END),
             SUM(CASE WHEN l.product_key IS NULL AND COALESCE(l.free_name,'')='' THEN 1 ELSE 0 END)
           FROM sale_lines l"""
    a, b, c = con.execute(q).fetchone()
    print(f"  商品台帳にある明細        : {a or 0:,}")
    print(f"  商品は消えたが品名は残る  : {b or 0:,}  ← v0.35.7で守った分")
    print(f"  品名が空の明細            : {c or 0:,}  ← 元データに品名が無いもの")

    print("\n== 参照整合性 ==")
    viol = con.execute("PRAGMA foreign_key_check").fetchall()
    if viol:
        from collections import Counter
        vc = Counter((v[0], v[2]) for v in viol)
        print(f"  孤立参照 {len(viol):,}件:")
        for (tbl, parent), c2 in vc.most_common():
            print(f"    {tbl} → {parent}: {c2:,}件")
    else:
        print("  問題なし")

    print("\n== 店舗 ==")
    for code, name in con.execute("SELECT store_code, name FROM stores ORDER BY store_code"):
        print(f"  {code}: {name}")
    con.close()


if __name__ == "__main__":
    main()
