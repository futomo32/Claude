# -*- coding: utf-8 -*-
"""入金履歴に「取消」の行を1件足す(2026-09-14)。

作った理由:
  売上を打ち直した時、取り消した方の売掛は手で削除されたが、**入金履歴には
  「掛売 ¥50,000」の行がそのまま残り、2件掛売があったように見えていた**(店の指摘)。
  v1.4.26 で**これから先は自動で「取消」の行が入る**ようにしたが、
  **すでに残ってしまっている分**は自動では直らないので、この道具で1件ずつ足す。

  入るのは入金履歴(receivable_entries)の1行だけ:
      日付 / 区分「取消」/ 商品名 / 購入金額 **マイナス** / 備考
  ★売掛残高(receivables)には一切触らない。請求額は変わらない。
  ★入金履歴を合計している画面は無いので、他の数字も動かない。

★安全のための決まり:
  ・既定は「下読み」。何を入れるかを出すだけで、データは1文字も変更しない。
  ・書き込むのは --apply を付けた時だけ。その直前に必ずバックアップを取る。
  ・**同じ内容の「取消」行が既にあれば入れない**(二重に足すと相殺しすぎる)。
  ・個人情報は出さない(顧客IDと金額だけ。氏名は出さない)。

日付の決め方:
  --date を指定しなければ、**その顧客の取消済み明細の取消日**を探して使う
  (記録としては「実際に取り消した日」が正しいため)。見つからなければ今日。

使い方:
  py -3 scripts\\add_void_entry.py --customer 01-8689 --name "K18/SVブレス" --amount 50000
  py -3 scripts\\add_void_entry.py --customer 01-8689 --name "K18/SVブレス" --amount 50000 --apply
  (日付を自分で決める場合)  --date 2026-08-28
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(BASE, "server"))
import db_query  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="入金履歴に「取消」の行を1件足す(既定は下読み)")
    ap.add_argument("--customer", required=True, help="顧客ID(例 01-8689)")
    ap.add_argument("--name", required=True, help="商品名(取り消した売掛の商品名)")
    ap.add_argument("--amount", required=True, help="取り消す金額(プラスで入れる。行にはマイナスで入る)")
    ap.add_argument("--date", help="取消の日付(YYYY-MM-DD)。省略すると取消済み明細の取消日を探す")
    ap.add_argument("--note", default="打ち直しのため取消(後から記録)", help="備考")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読みのみ)")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1
    try:
        amount = int(str(a.amount).replace(",", "").replace("¥", ""))
    except ValueError:
        print("金額は数字で入れてください(例 50000)")
        return 1
    if amount <= 0:
        print("金額はプラスで入れてください(行にはマイナスで入ります)")
        return 1

    cid = str(a.customer).strip()
    print("読むだけの下読みです(--apply を付けるまでデータは変更しません)。")
    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)
    con.row_factory = sqlite3.Row

    row = con.execute("SELECT customer_id FROM customers WHERE customer_id=?", (cid,)).fetchone()
    if not row:
        print("[中止] 顧客 %s が見つかりません。" % cid)
        con.close()
        return 1

    # 日付: 指定が無ければ、その顧客の取消済み明細の取消日を使う
    when = (a.date or "").strip()
    how = "指定"
    if not when:
        r = con.execute("""SELECT substr(MAX(l.voided_at),1,10)
                           FROM sale_lines l JOIN sales_slips s ON s.slip_id = l.slip_id
                           WHERE s.customer_id=? AND COALESCE(l.voided,0)=1""", (cid,)).fetchone()
        if r and r[0]:
            when, how = r[0], "取消済み明細の取消日"
        else:
            when, how = datetime.date.today().isoformat(), "今日(取消済み明細が見つからず)"

    # 二重に足さないための確認
    dup = con.execute("""SELECT COUNT(*) FROM receivable_entries
                         WHERE customer_id=? AND entry_type='取消'
                               AND COALESCE(product_name,'')=? AND COALESCE(amount,0)=?""",
                      (cid, a.name, -amount)).fetchone()[0]

    print("\n入れる行:")
    print("  顧客ID  : %s" % cid)
    print("  日付    : %s  (%s)" % (when, how))
    print("  区分    : 取消")
    print("  商品名  : %s" % a.name)
    print("  購入金額: -%s" % format(amount, ","))
    print("  備考    : %s" % a.note)
    print("\n※売掛残高(receivables)には触りません。請求額は変わりません。")

    # 今の入金履歴(件数だけ。中身は出さない)
    n = con.execute("SELECT COUNT(*) FROM receivable_entries WHERE customer_id=?", (cid,)).fetchone()[0]
    print("このお客様の入金履歴: 今 %s件" % format(n, ","))
    if dup:
        print("\n[中止] 同じ内容の「取消」行が既に %s件 あります。二重に足すと相殺しすぎます。" % dup)
        con.close()
        return 1

    if not a.apply:
        print("\n下読みだけで終了しました。書き込むには --apply を付けてください。")
        con.close()
        return 0

    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_取消行追加前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)
    con = sqlite3.connect(DB)
    con.execute("""INSERT INTO receivable_entries
                     (customer_id,entry_type,entry_date,product_name,amount,paid,note)
                   VALUES (?,?,?,?,?,?,?)""",
                (cid, "取消", when, a.name, -amount, None, a.note))
    con.commit()
    n2 = con.execute("SELECT COUNT(*) FROM receivable_entries WHERE customer_id=?", (cid,)).fetchone()[0]
    print("書き込み完了。このお客様の入金履歴: %s件 になりました。" % format(n2, ","))
    print("顧客詳細の「入金管理」を開き直すと、取消の行が並びます。")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
