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


def has_col(con, table, col):
    """列が存在するか(サーバー未起動のDBには新しい列が無いことがある)。"""
    try:
        return any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})"))
    except sqlite3.Error:
        return False


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

    print("\n[受託品かどうかの手がかり]  ※宝飾ナビの受託は「定価0円・下代なし」運用だった")
    z = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} "
                 f"AND (list_price IS NULL OR list_price=0)")
    nc = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} "
                  f"AND (cost_price IS NULL OR cost_price=0)")
    print(f"  在庫のうち上代が0円/空 : {z:>7} 件  ({pct(z, stock)})")
    print(f"  在庫のうち下代が0円/空 : {nc:>7} 件  ({pct(nc, stock)})")
    print("  状態区分(state)の種類(全商品):")
    try:
        for st, c in con.execute(
                "SELECT COALESCE(state,'(なし)') s, COUNT(*) c FROM products "
                "GROUP BY s ORDER BY c DESC"):
            print(f"     {st} : {c} 件")
    except sqlite3.Error as e:
        print("     取得不可:", e)
    cons_col = has_col(con, "products", "is_consignment")
    if cons_col:
        print("  受託フラグ(is_consignment)の内訳(在庫):")
        try:
            for f, c in con.execute(
                    f"SELECT COALESCE(is_consignment,0) f, COUNT(*) c FROM products "
                    f"WHERE {STOCK} GROUP BY f ORDER BY f"):
                print(f"     {'受託=1' if f else '通常=0'} : {c} 件")
        except sqlite3.Error as e:
            print("     取得不可:", e)
    else:
        print("  受託フラグ(is_consignment): この列はまだありません(トキワを一度起動すると作られます)")

    print("\n[★重複している品番の中身を並べる(在庫が複数ある品番のみ)]")
    print("  同じ品番の2点が『在庫品＋受託品』なら、上代0円・下代なしの側が受託の可能性が高い。")
    print("  ※下代(原価)は金額を出さず 有/無 のみ表示します。")
    cons_sel = "COALESCE(is_consignment,0)" if cons_col else "0"
    try:
        rows = con.execute(
            f"SELECT product_no, name, supplier, list_price, cost_price, location, "
            f"registered_at, {cons_sel} FROM products "
            f"WHERE {STOCK} AND {NUM5} AND product_no IN ("
            f"  SELECT product_no FROM products WHERE {STOCK} AND {NUM5} "
            f"  GROUP BY product_no HAVING COUNT(*)>1) "
            f"ORDER BY product_no, registered_at").fetchall()
        if not rows:
            print("   (重複なし)")
        else:
            prev = None
            for pno, name, sup, lp, cp, loc, reg, cons in rows:
                if prev is not None and pno != prev:
                    print("   " + "-" * 76)
                prev = pno
                cost = "有" if cp else "なし"
                price = "0円/空" if not lp else f"{lp:,}円"
                print(f"   {pno}  上代 {price:>10}  下代 {cost:>3}  "
                      f"{'受託' if cons else '通常'}  置場 {loc or '-'}  登録 {reg or '-'}")
                print(f"          品名 {name or '-'}   仕入先 {sup or '-'}")
    except sqlite3.Error as e:
        print("   取得不可:", e)

    print("\n[★ドライラン] 不明品(空レコード)を整理したら重複は何組残るか")
    print("  ※計算だけで、DBは何も消しません。移行の直前にもう一度実行すれば、その時点の残件が出ます。")
    defs = [
        ("A: 上代0円/空 かつ 下代0円/空",
         "(list_price IS NULL OR list_price=0) AND (cost_price IS NULL OR cost_price=0)"),
        ("B: 品名が空",
         "(name IS NULL OR TRIM(name)='')"),
        ("C: A または B",
         "((list_price IS NULL OR list_price=0) AND (cost_price IS NULL OR cost_price=0)) "
         "OR (name IS NULL OR TRIM(name)='')"),
    ]
    for label, cond in defs:
        gone = one(con, f"SELECT COUNT(*) FROM products WHERE {STOCK} AND {NUM5} AND ({cond})")
        # その分を除いたうえで、まだ複数残る品番を数え直す
        kinds = one(con, f"SELECT COUNT(*) FROM (SELECT product_no FROM products "
                         f"WHERE {STOCK} AND {NUM5} AND NOT ({cond}) "
                         f"GROUP BY product_no HAVING COUNT(*)>1)")
        items = one(con, f"SELECT COALESCE(SUM(c),0) FROM (SELECT COUNT(*) c FROM products "
                         f"WHERE {STOCK} AND {NUM5} AND NOT ({cond}) "
                         f"GROUP BY product_no HAVING c>1)")
        left = (n5 - gone) if isinstance(n5, int) and isinstance(gone, int) else None
        print(f"\n  【定義{label}】")
        print(f"    消える見込みの在庫    : {gone} 件")
        if left is not None:
            print(f"    残る在庫              : {left} 件")
        print(f"    残る重複品番          : {kinds} 種類 / {items} 件  ← 番号の振り直しが必要な分")
        if left and isinstance(items, int):
            print(f"    1件に確定できる割合    : {pct(left - items, left)}")

    print("\n  → 残った重複は「番号の振り直し」で対応します(削除より安全)。")
    print("    内部キー(product_key)で売上・在庫・売掛が紐づいているので、表示番号を変えても壊れません。")

    con.close()
    print("\n※ 読み取りのみ。DBは変更しません。")
    print("※ 判定の目安: 「1件に確定できる割合」が95%以上なら、スキャン→即確認で運用できる")
    print("   (残りだけ候補選択)。低い場合は候補選択画面を先に用意する必要があります。")


if __name__ == "__main__":
    main()
