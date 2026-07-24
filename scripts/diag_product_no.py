#!/usr/bin/env python3
"""商品番号(product_no)の桁数分布・9桁データの件数と紐づき・番号の重複を調べる診断。
個人情報(顧客名など)は出力しない。実店舗のDBに対して安全に実行できる。

  python3 scripts/diag_product_no.py
"""
import os
import sqlite3

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")


def one(con, sql, args=()):
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else 0
    except sqlite3.Error as e:
        return f"(取得不可: {e})"


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        return
    con = sqlite3.connect(DB)
    numeric = "product_no GLOB '[0-9]*'"          # 数字で始まる商品番号
    where9 = f"{numeric} AND LENGTH(product_no)=9"  # 9桁ちょうど

    print("=== 商品番号の診断 ===")
    print(f"DB: {os.path.abspath(DB)}")
    print(f"総商品数: {one(con, 'SELECT COUNT(*) FROM products')}")

    print("\n[桁数別の分布(数字で始まる商品番号)]")
    try:
        for r in con.execute(
                f"SELECT LENGTH(product_no) L, COUNT(*) c FROM products "
                f"WHERE {numeric} GROUP BY L ORDER BY L"):
            print(f"   {r[0]}桁 : {r[1]:>7} 件")
    except sqlite3.Error as e:
        print("   取得不可:", e)

    print(f"\n[9桁の商品番号] : {one(con, f'SELECT COUNT(*) FROM products WHERE {where9}')} 件")
    print("  状態別:")
    try:
        for r in con.execute(
                f"SELECT COALESCE(state,'(なし)') s, COUNT(*) c FROM products "
                f"WHERE {where9} GROUP BY s ORDER BY c DESC"):
            print(f"     {r[0]} : {r[1]} 件")
    except sqlite3.Error as e:
        print("     取得不可:", e)

    print("\n[9桁データがどこと繋がっているか(内部キー product_key 経由)]")
    print("  売上明細に紐づく:",
          one(con, f"SELECT COUNT(DISTINCT p.product_key) FROM products p "
                   f"JOIN sale_lines s ON s.product_key=p.product_key WHERE {where9}"), "点")
    print("  在庫イベントに紐づく:",
          one(con, f"SELECT COUNT(DISTINCT p.product_key) FROM products p "
                   f"JOIN stock_events e ON e.product_key=p.product_key WHERE {where9}"), "点")
    print("  売掛に紐づく:",
          one(con, f"SELECT COUNT(DISTINCT p.product_key) FROM products p "
                   f"JOIN receivables r ON r.product_key=p.product_key WHERE {where9}"), "点")

    print("\n[商品番号の重複]")
    dup_kinds = one(con, "SELECT COUNT(*) FROM (SELECT product_no FROM products "
                         "GROUP BY product_no HAVING COUNT(*)>1)")
    print("  重複している番号の種類数:", dup_kinds)
    try:
        rows = con.execute("SELECT product_no, COUNT(*) c FROM products "
                           "GROUP BY product_no HAVING c>1 ORDER BY c DESC LIMIT 20").fetchall()
        if rows:
            print("  重複の多い番号(上位20):")
            for pno, c in rows:
                print(f"     {pno} : {c} 件")
    except sqlite3.Error as e:
        print("  取得不可:", e)

    print("\n[採番ルール決めの参考]")
    for n in (5, 6):
        mx = one(con, f"SELECT MAX(CAST(product_no AS INTEGER)) FROM products "
                      f"WHERE {numeric} AND LENGTH(product_no)={n}")
        print(f"  {n}桁の商品番号の最大値: {mx}")
    print("  現在の在庫(state=在庫)の5桁商品番号・大きい順10件:")
    try:
        rows = con.execute(
            "SELECT product_no, name FROM products WHERE state='在庫' "
            "AND product_no GLOB '[0-9]*' AND LENGTH(product_no)=5 "
            "ORDER BY CAST(product_no AS INTEGER) DESC LIMIT 10").fetchall()
        for pno, name in rows:
            print(f"     {pno} : {name}")
        if not rows:
            print("     (該当なし)")
    except sqlite3.Error as e:
        print("     取得不可:", e)

    con.close()
    print("\n※ 内部キー(product_key)は常に一意なので、表示番号(product_no)が重複・9桁でも")
    print("   売上・在庫・売掛のリンクは壊れません。番号の振り直しも安全です。")


if __name__ == "__main__":
    main()
