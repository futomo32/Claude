#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DMを「出さない」判定が実データで正しく効くかを確かめる診断。

作った理由(2026-08-06):
  DMの送付可否は2つの仕組みで決まる。
    ① 住所の先頭の記号 … ＴＴＴ(転居)・ＳＳＳ(死去)・ＭＭＭ(店の都合)・
                          ＫＫＫ(本人希望)・ＦＦＦ(福祉/生活保護)
    ② DM区分(customers.dm_ok) … 「送らない」等
  ②は取込元ごとに表記が違う(CSV取込=送る/送らない、xlsx取込=元の列の値をそのまま、
  旧UI=可/不可)。トキワは db_query.DM_NO_VALUES に載っている表記だけを「送らない」と
  見なし、**それ以外は「送る」扱いにする**。つまり一覧に無い表記が実データにあると、
  出さないつもりの顧客にDMを送ってしまう。
  実データは開発環境に無いため機械的に確かめられない。このスクリプトを店のPCで走らせて、
  「拾えていない表記が無いか」を確認する。

やっていること:
  1. dm_ok に実際に入っている値の種類と件数を数え、トキワの判定結果を併記する
  2. ★判定が「送る」になる値のうち、出さない意図に見えるものを警告する
  3. 住所の記号(①)が何件あるかを理由別に数える
  4. ①と②の食い違い(記号は付いているがdm_okは送る、等)を件数で示す
     ※トキワはどちらか一方でも「出さない」なら出さないので、食い違い自体は事故に
       ならない。記入漏れの傾向を知るための参考値。

使い方:
  Windows  : python scripts\\diag_dm_flags.py
  Mac/Linux: python3 scripts/diag_dm_flags.py

個人情報:
  出力は「値の種類」と「件数」だけ。顧客名・住所・電話番号は一切出力しない。
  住所は先頭の記号の判定にのみ使い、住所そのものは表示しない。
  (CLAUDE.md「診断・分析スクリプトは個人情報を画面出力しない設計にする」に従う)
"""
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")

# 判定は server/db_query.py の唯一の正を読む(ここに書き写すと直し漏れが出る)
sys.path.insert(0, os.path.join(BASE, "server"))
import db_query  # noqa: E402

# 「送る」判定になった値のうち、出さない意図に見えるものを拾うための否定語。
# ★「送」のような肯定にも含まれる字は入れない(「送る」自身が引っかかり、
#   これを DM_NO_VALUES に足すと全員がDM対象外になってしまう)。
#   否定を表す字だけを並べ、部分一致で見る。
SUSPECT_WORDS = ("不", "無", "なし", "ない", "ません", "否", "拒", "止", "禁", "NG", "ng")


def pct(a, b):
    return f"{a / b * 100:5.1f}%" if b else "    -"


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        print("  実データを取り込んだPCで実行してください。")
        sys.exit(1)

    con = sqlite3.connect(DB)
    total = con.execute("SELECT COUNT(*) FROM customers WHERE COALESCE(is_test,0)=0").fetchone()[0]
    if not total:
        print("[エラー] 顧客が0件です。取込が終わっているか確認してください。")
        sys.exit(1)

    print("=" * 72)
    print("  DMを「出さない」判定の点検")
    print(f"  顧客 {total:,}件(検証用ペルソナは除く)")
    print("  ※出力は値の種類と件数だけです。顧客名・住所・電話番号は出しません")
    print("=" * 72)

    # ── ① DM区分(dm_ok)に入っている値 ──
    print("\n■ DM区分(dm_ok)に実際に入っている値")
    print(f"  {'値':<16}{'件数':>9}{'割合':>8}  トキワの判定")
    rows = con.execute("""SELECT COALESCE(dm_ok,'') v, COUNT(*) n FROM customers
                          WHERE COALESCE(is_test,0)=0 GROUP BY v ORDER BY n DESC""").fetchall()
    suspects = []
    for v, n in rows:
        blocked = db_query.dm_is_blocked(v)
        shown = "(空欄)" if not v else (v if len(v) <= 14 else v[:14] + "…")
        verdict = "出さない" if blocked else "送る"
        mark = ""
        if not blocked and v and any(w in v for w in SUSPECT_WORDS):
            mark = "  ★要確認"
            suspects.append((v, n))
        print(f"  {shown:<16}{n:>9,}{pct(n, total):>8}  {verdict}{mark}")

    # ── ② 住所の先頭の記号 ──
    print("\n■ 住所の先頭の記号(理由別)")
    marks = {}
    no_addr = 0
    for (addr,) in con.execute("""SELECT address FROM customers
                                  WHERE COALESCE(is_test,0)=0"""):
        if not addr:
            no_addr += 1
            continue
        reason = db_query.dm_block_reason(addr)
        if reason:
            marks[reason] = marks.get(reason, 0) + 1
    if marks:
        for reason, n in sorted(marks.items(), key=lambda kv: -kv[1]):
            print(f"  {reason:<16}{n:>9,}{pct(n, total):>8}")
        print(f"  {'合計':<16}{sum(marks.values()):>9,}{pct(sum(marks.values()), total):>8}")
    else:
        print("  記号の付いた住所は見つかりませんでした。")
        print("  → 記号の書き方が想定と違う可能性があります(想定: Ｔ/Ｓ/Ｍ/Ｋ/Ｆ を3つ重ねる)")
    if no_addr:
        print(f"  ※住所が未登録の顧客が {no_addr:,}件あります(記号の判定対象外)")

    # ── ③ ①と②の食い違い ──
    print("\n■ 2つの仕組みの食い違い(参考)")
    both = mark_only = flag_only = 0
    for addr, dm in con.execute("""SELECT address, dm_ok FROM customers
                                   WHERE COALESCE(is_test,0)=0"""):
        m = bool(db_query.dm_block_reason(addr))
        f = db_query.dm_is_blocked(dm)
        if m and f:
            both += 1
        elif m:
            mark_only += 1
        elif f:
            flag_only += 1
    print(f"  住所の記号もDM区分も「出さない」  : {both:>9,}件")
    print(f"  住所の記号だけ(DM区分は送る)      : {mark_only:>9,}件")
    print(f"  DM区分だけ(住所に記号なし)        : {flag_only:>9,}件")
    print(f"  DMを出さない顧客(合計)            : {both + mark_only + flag_only:>9,}件"
          f"  → 残り {total - (both + mark_only + flag_only):,}件が送付対象")
    print("  ※どちらか一方でも「出さない」なら出さないため、食い違い自体は事故になりません。")

    con.close()

    # ── まとめ ──
    print("\n" + "=" * 72)
    if suspects:
        print("  ★次の値は「送る」と判定されていますが、出さない意図に見えます。")
        print("    店での使い方を確認してください:")
        for v, n in suspects:
            print(f"      「{v}」 … {n:,}件")
        print("\n    出さない意図で使っている表記だった場合のみ、その値を")
        print("    server/db_query.py の DM_NO_VALUES と")
        print("    tokiwa-ui.html の DM_NO_VALUES の両方に追加してください")
        print("    (サーバー=B2書き出し・詳細検索 / 画面=24面ラベル印刷)。")
        print("    ※送る意図の値を足すと、その顧客全員がDM対象外になります。")
    else:
        print("  拾えていない表記は見つかりませんでした。")
        print("  ただし機械的な判定なので、上の一覧に見慣れない値があれば確認してください。")
    print("=" * 72)


if __name__ == "__main__":
    main()
