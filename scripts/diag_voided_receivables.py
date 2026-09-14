# -*- coding: utf-8 -*-
"""取り消した売上なのに売掛が残っているものを数える(2026-09-14)。

作った理由:
  店から「レジのデータを取り消した時、売掛だった場合は売掛が残ってしまうのでは」と
  指摘があった。調べたところ**そのとおり**で、取消(void_sale_line / void_sale_slip)は
    ・明細と伝票に取消印を付ける
    ・在庫品を在庫に戻す
    ・ポイントを戻す(付与の取消・使用の返却)
  までは行うが、**売掛(receivables)には一切触っていない**。
  売掛管理の集計も `WHERE balance > 0` で残高しか見ておらず、伝票が取り消されたか
  どうかを見ていない。→ **返品したのに請求してしまう(二重請求)**。

  直す前に、**今どれだけ残っているか**を数えるのがこのスクリプト。

★読むだけ。データは1文字も変更しない。
★個人情報は出さない(顧客IDと件数・金額だけ。氏名は一切出さない)。

見るもの:
  (1) 伝票まるごと取消なのに残高が残っている売掛
  (2) 伝票は取消になっていないが、**明細が全部取消**になっている売掛
      (1行ずつ取り消すと伝票の印は付かないため、これも実質は返品済み)
  (3) **入金がある**ものは自動で消せないので分けて数える
      (受け取ったお金の記録を消すと、返金の実態と帳簿が合わなくなる)
  (4) slip_id を持たない売掛(2026-09-03より前に作った分・移行データ)
      → 伝票と結びつかないので**自動では判定できない**。手で確認する分の目安

使い方:
  python3 scripts/diag_voided_receivables.py
  python3 scripts/diag_voided_receivables.py --list   # 対象の売掛IDを並べる(手当て用)
"""
import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(BASE, "server"))
import db_query  # noqa: E402


def yen(v):
    return "¥" + format(int(v or 0), ",")


def main():
    ap = argparse.ArgumentParser(description="取消済みの売上に残っている売掛を数える(読むだけ)")
    ap.add_argument("--list", action="store_true", help="対象の売掛ID・伝票番号を並べる(手当て用)")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1

    print("読むだけの調査です。データは1文字も変更しません。")
    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)     # slip_id 列が無いDBでも動くように(冪等)
    con.row_factory = sqlite3.Row

    total_n = con.execute("SELECT COUNT(*) FROM receivables").fetchone()[0]
    live = con.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM receivables "
                       "WHERE COALESCE(balance,0) > 0").fetchone()
    print("\n売掛: 全 %s件 / うち残高が残っているもの %s件 (%s)"
          % (format(total_n, ","), format(live[0], ","), yen(live[1])))

    # ── 伝票と結びついていない売掛(自動判定できない分) ──
    no_slip = con.execute("""SELECT COUNT(*), COALESCE(SUM(balance),0) FROM receivables
                             WHERE slip_id IS NULL AND COALESCE(balance,0) > 0""").fetchone()
    print("  ・伝票と結びついていない(slip_idなし): %s件 (%s)"
          % (format(no_slip[0], ","), yen(no_slip[1])))
    print("    ※2026-09-03より前に作った分と移行データ。取消と突き合わせられないので、")
    print("      残っていても**このスクリプトでは判定できません**(手で確認する分)。")

    # ── (1)(2) 取消済みの売上に残っている売掛 ──
    rows = list(con.execute("""
        SELECT r.id, r.customer_id, r.slip_id, r.product_name, COALESCE(r.balance,0) bal,
               COALESCE(r.down_payment,0) down, r.last_paid_at, r.bought_at,
               COALESCE(s.voided,0) slip_voided, s.voided_at, s.slip_no,
               (SELECT COUNT(*) FROM sale_lines l WHERE l.slip_id = s.slip_id) n_lines,
               (SELECT COUNT(*) FROM sale_lines l
                 WHERE l.slip_id = s.slip_id AND COALESCE(l.voided,0)=1) n_voided
        FROM receivables r JOIN sales_slips s ON s.slip_id = r.slip_id
        WHERE COALESCE(r.balance,0) > 0"""))

    slip_void, all_lines_void = [], []
    for r in rows:
        if r["slip_voided"]:
            slip_void.append(r)
        elif r["n_lines"] and r["n_lines"] == r["n_voided"]:
            all_lines_void.append(r)

    def show(title, items, note=""):
        n = len(items)
        amt = sum(int(x["bal"] or 0) for x in items)
        paid = [x for x in items if (x["last_paid_at"] or "") or int(x["down"] or 0) > 0]
        print("\n=== %s: %s件 (%s) ===" % (title, format(n, ","), yen(amt)))
        if note:
            print("  " + note)
        if n:
            print("  ・入金(頭金を含む)がある: %s件 (%s) ← **自動では消せない分**"
                  % (format(len(paid), ","), yen(sum(int(x["bal"] or 0) for x in paid))))
            print("  ・入金がまったく無い: %s件 (%s) ← 消してよい分"
                  % (format(n - len(paid), ","), yen(amt - sum(int(x["bal"] or 0) for x in paid))))
        if n and a.list:
            print("  %-8s %-10s %-12s %10s %10s  %s" % ("売掛ID", "顧客ID", "伝票", "残高", "頭金", "取消日"))
            for x in items[:200]:
                print("  %-8s %-10s %-12s %10s %10s  %s"
                      % (x["id"], x["customer_id"], x["slip_no"] or ("#" + str(x["slip_id"])),
                         format(int(x["bal"] or 0), ","), format(int(x["down"] or 0), ","),
                         (x["voided_at"] or "")[:10]))
            if n > 200:
                print("  … 他 %s件" % format(n - 200, ","))

    show("伝票まるごと取消なのに残っている売掛", slip_void)
    show("明細が全部取消なのに残っている売掛", all_lines_void,
         "1行ずつ取り消すと伝票の印は付かないが、実質は返品済み。")

    bad = len(slip_void) + len(all_lines_void)
    bad_amt = sum(int(x["bal"] or 0) for x in slip_void + all_lines_void)
    print("\n" + "=" * 56)
    print("  ★請求してしまう恐れがある売掛: %s件 (%s)" % (format(bad, ","), yen(bad_amt)))
    if not bad:
        print("  今のところ1件もありません(取消と売掛の食い違いは起きていません)。")
    else:
        print("  ※このスクリプトは何も直しません。直し方は店と相談してから作ります。")
        if not a.list:
            print("  ※ --list を付けると、対象の売掛ID・伝票番号を並べます。")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
