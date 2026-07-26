#!/usr/bin/env python3
"""商品の「増え方」(年ごとの新規登録数)を調べる診断。5桁の商品番号で足りるかの判断材料。
個人情報(顧客名・商品名など)は一切出力しない。実店舗のDBに対して安全に実行できる。

  Windows: python scripts\\diag_product_growth.py
  Mac/Linux: python3 scripts/diag_product_growth.py
"""
import os
import sqlite3

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")

NUM5 = "product_no GLOB '[0-9]*' AND LENGTH(product_no)=5"  # 採番に使う5桁の商品番号
MAX5 = 99999  # 5桁で表せる上限


def one(con, sql, args=()):
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else 0
    except sqlite3.Error as e:
        return f"(取得不可: {e})"


def year_counts(con, where=""):
    """登録年ごとの件数。registered_at が空のものは「(日付なし)」でまとめる。"""
    wsql = (" WHERE " + where) if where else ""
    sql = (f"SELECT CASE WHEN registered_at IS NULL OR registered_at='' THEN '(日付なし)' "
           f"ELSE substr(registered_at,1,4) END yr, COUNT(*) c FROM products{wsql} "
           f"GROUP BY yr ORDER BY yr")
    try:
        return con.execute(sql).fetchall()
    except sqlite3.Error as e:
        print("   取得不可:", e)
        return []


def show_years(rows):
    if not rows:
        print("   (該当なし)")
        return
    mx = max((c for _, c in rows), default=0)
    for yr, c in rows:
        bar = "#" * int(round(c / mx * 40)) if mx else ""
        print(f"   {yr:>9} : {c:>7} 件  {bar}")


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        return
    con = sqlite3.connect(DB)

    print("=== 商品の増え方の診断(5桁の商品番号で足りるか) ===")
    print(f"DB: {os.path.abspath(DB)}")
    total = one(con, "SELECT COUNT(*) FROM products")
    print(f"総商品数: {total}")
    n5 = one(con, f"SELECT COUNT(*) FROM products WHERE {NUM5}")
    print(f"うち5桁の商品番号: {n5} 件")
    nodate = one(con, "SELECT COUNT(*) FROM products "
                      "WHERE registered_at IS NULL OR registered_at=''")
    print(f"登録日が空の商品: {nodate} 件  ※多いと年別集計の精度が落ちます")

    print("\n[年別 新規登録数 ★5桁の商品番号のみ(採番の実消費数)]")
    rows5 = year_counts(con, NUM5)
    show_years(rows5)

    print("\n[年別 新規登録数 (全商品・参考。メガネの9桁シリーズ等も含む)]")
    show_years(year_counts(con))

    print("\n[5桁の商品番号の消費状況]")
    mx5 = one(con, f"SELECT MAX(CAST(product_no AS INTEGER)) FROM products WHERE {NUM5}")
    print(f"  現在の最大値      : {mx5}")
    if isinstance(mx5, int) and mx5:
        rest = MAX5 - mx5
        print(f"  5桁の上限         : {MAX5}")
        print(f"  残りの番号         : 約 {rest} 番")
    else:
        rest = None

    print("\n[直近の増え方(5桁のみ)]")
    est = None
    for yrs in (3, 5, 10):
        c = one(con, f"SELECT COUNT(*) FROM products WHERE {NUM5} "
                     f"AND registered_at >= date('now','-{yrs} years')")
        if isinstance(c, int):
            per = c / yrs
            print(f"  直近{yrs:>2}年: {c:>6} 件 → 平均 約 {per:,.0f} 件/年")
            if yrs == 5 and per > 0:
                est = per
        else:
            print(f"  直近{yrs:>2}年: {c}")

    if rest and est:
        print(f"\n[判定] 残り約 {rest:,} 番 ÷ 約 {est:,.0f} 件/年 "
              f"→ このペースなら 約 {rest / est:.0f} 年もちます")
        print("  目安: 30年以上もつなら5桁のままでOK。10年未満なら6桁化を検討。")
    else:
        print("\n[判定] 直近の登録実績が取れないため年数の見積りは省略します"
              "(登録日が空か、移行後まだ登録が無い可能性)。")

    print("\n[月別 直近24か月(5桁のみ・最近の勢いを見る)]")
    try:
        rows = con.execute(
            f"SELECT substr(registered_at,1,7) ym, COUNT(*) c FROM products "
            f"WHERE {NUM5} AND registered_at >= date('now','-24 months') "
            f"GROUP BY ym ORDER BY ym").fetchall()
        if rows:
            show_years(rows)
        else:
            print("   (該当なし)")
    except sqlite3.Error as e:
        print("   取得不可:", e)

    con.close()
    print("\n※ このスクリプトは読み取りのみ。DBは変更しません。")
    print("※ 判断に使うのは「5桁のみ」の年別件数です(メガネの9桁は別系統で採番に使いません)。")


if __name__ == "__main__":
    main()
