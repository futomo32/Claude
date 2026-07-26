#!/usr/bin/env python3
"""棚卸しのバーコード照合が成立するかを調べる診断。
「現在の在庫の中で5桁の商品番号(品番)は一意か?」= スキャン1回で1件に確定できるか、を見る。
宝飾ナビのタグのバーコードは 管理番号の先頭10桁 しか入っておらず、DBの商品番号は5桁の品番
なので、照合は先頭5桁で行う必要がある。同じ品番の在庫が複数あると候補選択が必要になる。

出力は「番号と件数」だけ。商品名・顧客名などの個人情報や品名は一切出力しない。

  Windows  : python scripts\\diag_stock_scan.py
  Mac/Linux: python3 scripts/diag_stock_scan.py
"""
import os
import sqlite3

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")

STOCK = "state='在庫'"                                    # 棚卸しが照合する対象
NUM5 = "product_no GLOB '[0-9]*' AND LENGTH(product_no)=5"  # 5桁の品番


def one(con, sql, args=()):
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else 0
    except sqlite3.Error as e:
        return f"(取得不可: {e})"


def pct(a, b):
    try:
        return f"{a / b * 100:.1f}%"
    except (TypeError, ZeroDivisionError):
        return "-"


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        return
    con = sqlite3.connect(DB)

    print("=== 棚卸しスキャンの照合可否の診断 ===")
    print(f"DB: {os.path.abspath(DB)}")

    stock = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK}")
    print(f"\n在庫(state=在庫)の点数: {stock}")

    print("\n[在庫の商品番号の形]  ※スキャンで照合できるのは5桁の品番")
    n5 = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} AND {NUM5}")
    nstar = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} AND product_no LIKE '*%'")
    nhyph = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} AND product_no LIKE '%-%'")
    nblank = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} "
                      f"AND (product_no IS NULL OR product_no='')")
    print(f"  5桁の品番          : {n5:>7} 件  ({pct(n5, stock)})  ← スキャン照合の対象")
    print(f"  仮番号(*で始まる)   : {nstar:>7} 件  ({pct(nstar, stock)})  ← タグ/バーコード無し")
    print(f"  ハイフン入り        : {nhyph:>7} 件  ({pct(nhyph, stock)})  ← フル管理番号で入っている?")
    print(f"  空                  : {nblank:>7} 件")
    print("  桁数別(数字で始まるもの):")
    try:
        for L, c in con.execute(
                f"SELECT LENGTH(product_no) L, COUNT(*) c FROM products "
                f"WHERE {STOCK} AND product_no GLOB '[0-9]*' GROUP BY L ORDER BY L"):
            print(f"     {L:>2}桁 : {c:>7} 件")
    except sqlite3.Error as e:
        print("     取得不可:", e)

    print("\n[★本題] 在庫の5桁品番は一意か(スキャン1回で1件に確定できるか)")
    distinct = one(con, f"SELECT COUNT(DISTINCT product_no) FROM products WHERE {STOCK} AND {NUM5}")
    uniq = one(con, f"SELECT COUNT(*) FROM (SELECT product_no FROM products "
                    f"WHERE {STOCK} AND {NUM5} GROUP BY product_no HAVING COUNT(*)=1)")
    dup_kinds = one(con, f"SELECT COUNT(*) FROM (SELECT product_no FROM products "
                         f"WHERE {STOCK} AND {NUM5} GROUP BY product_no HAVING COUNT(*)>1)")
    dup_rows = one(con, f"SELECT COALESCE(SUM(c),0) FROM (SELECT COUNT(*) c FROM products "
                        f"WHERE {STOCK} AND {NUM5} GROUP BY product_no HAVING c>1)")
    print(f"  品番の種類数            : {distinct}")
    print(f"  在庫が1点だけの品番      : {uniq} 種類  ← ピッで即確定できる")
    print(f"  在庫が複数ある品番       : {dup_kinds} 種類 / {dup_rows} 件  ← 候補選択が必要")
    if isinstance(n5, int) and n5 and isinstance(dup_rows, int):
        print(f"\n  → スキャンで1件に確定できる割合: {pct(n5 - dup_rows, n5)} "
              f"(5桁品番の在庫 {n5} 件のうち)")

    print("\n[複数在庫がある品番の重なり具合]")
    try:
        rows = con.execute(
            f"SELECT c, COUNT(*) k FROM (SELECT COUNT(*) c FROM products "
            f"WHERE {STOCK} AND {NUM5} GROUP BY product_no) GROUP BY c ORDER BY c").fetchall()
        for c, k in rows:
            print(f"   同じ品番が {c:>3} 点 : {k:>6} 種類")
        if not rows:
            print("   (該当なし)")
    except sqlite3.Error as e:
        print("   取得不可:", e)

    print("\n[重複の多い品番(上位10・番号と件数のみ)]")
    try:
        rows = con.execute(
            f"SELECT product_no, COUNT(*) c FROM products WHERE {STOCK} AND {NUM5} "
            f"GROUP BY product_no HAVING c>1 ORDER BY c DESC, product_no LIMIT 10").fetchall()
        for pno, c in rows:
            print(f"   {pno} : {c} 点")
        if not rows:
            print("   (重複なし=すべて一意)")
    except sqlite3.Error as e:
        print("   取得不可:", e)

    con.close()
    print("\n※ 読み取りのみ。DBは変更しません。")
    print("※ 判定の目安: 「1件に確定できる割合」が95%以上なら、スキャン→即確認で運用できる")
    print("   (残りだけ候補選択)。低い場合は候補選択画面を先に用意する必要があります。")


if __name__ == "__main__":
    main()
