# -*- coding: utf-8 -*-
"""処方箋の「レンズカラー」を、レンズ商品のブランド欄から埋める(2026-09-10)。

作った理由:
  店から「処方箋のレンズのカラーが無い」と指摘があった。調べたところ、宝飾ナビは
  カラー品番(COPR50F 等)を **商品の「ブランド」欄** に入れて管理していた
  (`m_brand.strbrname` に COPR50F が登録されていることを確認)。
  処方箋台帳(45列)にはカラーの列そのものが無い。
  → トキワに `prescriptions.lens_color` を作り(v1.4.19)、レンズを紐付けると
    その商品のブランド欄が入るようにした。**過去の処方箋は空のまま**なので、
    このスクリプトで後から埋める。

  ★CSVは読まない。トキワのDBの中だけで完結する(処方箋 → レンズ商品 → ブランド)。

たどり方(2通り。どちらもDB内):
  1. `prescriptions.lens_key`   … 移行した処方箋が持っている商品キー(宝飾ナビの商品ID)
  2. `prescriptions.sale_line_id` → `sale_lines.product_key`
     … トキワで登録し、購入明細に紐付けた処方箋
  両方ある場合は 1 を優先する(処方箋が直接指している商品の方が確かなため)。

★安全のための決まり:
  ・既定は「下読み」。何件入るかを出すだけで、データは1文字も変更しない。
  ・書き込むのは --apply を付けた時だけ。その直前に必ずバックアップを取る。
  ・**すでにカラーが入っている処方箋は触らない**(店が手で書いた値を消さないため)。
    上書きしたい時だけ --overwrite を付ける。
  ・個人情報は出さない(件数と、カラーの値の種類だけ)。

下読みで出るもの(2026-09-10 追加):
  実データで流したところ **89%(44,305件)が「商品台帳にその商品が無い」** に入り、
  諦めるしかないのか、まだ手があるのかが件数だけでは分からなかった。そこで
    ・「商品台帳に無い」の中身 …… **元からレンズを紐付けていない(キーが0)** と、
       **キーはあるのに商品が無い**(宝飾ナビ側で消された/移行で外れた)に分ける
    ・年別の内訳 …………………… 古い年に偏っているかを見る
  を出すようにした。前者は埋めようがなく、後者はまだ手がある可能性がある。

使い方:
  python3 scripts/fill_lens_colors.py             # 下読み(何件入るか見るだけ)
  python3 scripts/fill_lens_colors.py --apply     # バックアップしてから書き込む
  python3 scripts/fill_lens_colors.py --apply --overwrite   # 入っている分も上書き
"""
import argparse
import collections
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
    ap = argparse.ArgumentParser(description="処方箋のレンズカラーを埋める(既定は下読み)")
    ap.add_argument("--apply", action="store_true", help="実際に書き込む(既定は下読みのみ)")
    ap.add_argument("--overwrite", action="store_true",
                    help="すでにカラーが入っている処方箋も上書きする(既定は空のものだけ)")
    a = ap.parse_args()

    if not os.path.exists(DB):
        print("DBが見つかりません: %s" % DB)
        return 1

    print("読むだけの下読みです(--apply を付けるまでデータは変更しません)。")
    con = sqlite3.connect(DB)
    db_query.ensure_schema(con)      # lens_color 列が無いDBでも動くように(冪等)
    con.row_factory = sqlite3.Row

    total = con.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
    filled = con.execute("SELECT COUNT(*) FROM prescriptions "
                         "WHERE COALESCE(lens_color,'')<>''").fetchone()[0]
    print("処方箋: %s件(うちカラー入力済み %s件)"
          % (format(total, ","), format(filled, ",")))

    # ★1回のSQLで「処方箋 → レンズ商品 → ブランド」をたどる。
    #   lens_key を優先し、無ければ紐付けた購入明細の商品キーを使う。
    rows = list(con.execute("""
        SELECT rx.id,
               COALESCE(rx.lens_key, l.product_key) pk,
               COALESCE(rx.lens_color,'') cur,
               p.product_key found, p.brand brand, rx.rx_date
        FROM prescriptions rx
        LEFT JOIN sale_lines l ON l.line_id = rx.sale_line_id
        LEFT JOIN products p ON p.product_key = COALESCE(rx.lens_key, l.product_key)"""))

    plan = []
    no_key, no_product, no_brand, skip_filled = 0, 0, 0, 0
    kinds = collections.Counter()
    # ── 「商品台帳に無い」の中身を割って出す(2026-09-10 追加)。
    #    89%がここに入っており、**諦めるしかないのか、まだ手があるのか**が
    #    件数だけでは分からなかったため。
    zero_key = 0                          # キーが「◯◯-0」= 元からレンズを紐付けていない
    miss_store = collections.Counter()    # 実在しないキーの店舗コード別
    by_year = collections.defaultdict(lambda: collections.Counter())   # 年別の内訳
    for r in rows:
        year = str(r["rx_date"] or "")[:4] or "(日付なし)"
        cur_val = (r["cur"] or "").strip()
        if cur_val and not a.overwrite:
            skip_filled += 1
            by_year[year]["済"] += 1
            continue
        if not r["pk"]:
            no_key += 1            # レンズの商品が分からない処方箋(手書き・番号なし)
            by_year[year]["キー無"] += 1
            continue
        # ★商品が有るか無いかは product_key で判定する。
        #   以前は brand が NULL かどうかで見ていたため、**商品はあるがブランドが空**の
        #   ものまで「商品台帳に無い」に数えていた(2026-09-10 修正)。
        if r["found"] is None:
            no_product += 1        # 商品台帳にその商品が無い(移行で外れた/宝飾ナビ側で削除)
            by_year[year]["商品無"] += 1
            pk = str(r["pk"])
            if pk.rsplit("-", 1)[-1] in ("0", "00", ""):
                zero_key += 1      # 元からレンズを紐付けていない処方箋
            else:
                miss_store[pk.split("-", 1)[0]] += 1
            continue
        brand = (r["brand"] or "").strip()
        if not brand:
            no_brand += 1          # 商品はあるが、ブランド欄が空(カラー未登録)
            by_year[year]["色無"] += 1
            continue
        if brand == cur_val:
            skip_filled += 1
            by_year[year]["済"] += 1
            continue
        plan.append((brand, r["id"]))
        kinds[brand] += 1
        by_year[year]["入る"] += 1

    print("\n入れられる処方箋: %s件" % format(len(plan), ","))
    print("  入れられないもの:")
    print("    ・レンズの商品が分からない: %s件" % format(no_key, ","))
    print("    ・商品台帳にその商品が無い: %s件" % format(no_product, ","))
    print("    ・商品のブランド欄が空(カラー未登録): %s件" % format(no_brand, ","))
    print("    ・すでに同じ値が入っている/手入力済み: %s件" % format(skip_filled, ","))
    if kinds:
        print("\n  入るカラーの種類: %s種類(多い順に10件)" % format(len(kinds), ","))
        for k, c in kinds.most_common(10):
            print("    %-20s %s件" % (k[:20], format(c, ",")))

    # ── 内訳(1)「商品台帳に無い」の中身 ──
    if no_product:
        print("\n=== 「商品台帳にその商品が無い」%s件の内訳 ===" % format(no_product, ","))
        print("  ・元からレンズを紐付けていない(キーが 0): %s件" % format(zero_key, ","))
        print("     → これは移行の取りこぼしではありません。宝飾ナビ側でレンズ商品を")
        print("       選ばずに処方箋だけ作った分なので、埋めようがありません。")
        rest = no_product - zero_key
        print("  ・商品キーはあるのに商品台帳に無い: %s件" % format(rest, ","))
        if rest:
            print("     → 宝飾ナビ側で商品が消されている(売れたレンズを消す運用)か、")
            print("       移行で外れた可能性があります。店舗コード別:")
            for st, c in miss_store.most_common(6):
                print("       %-6s %s件" % (st, format(c, ",")))

    # ── 内訳(2)年別。古い年に偏っているかを見る ──
    print("\n=== 年別(処方日) ===")
    print("  %-10s %8s %8s %8s %8s %8s" % ("年", "全体", "入る", "商品無", "キー無", "色無"))
    for year in sorted(by_year, reverse=True):
        c = by_year[year]
        tot = sum(c.values())
        print("  %-10s %8s %8s %8s %8s %8s"
              % (year, format(tot, ","), format(c["入る"], ","), format(c["商品無"], ","),
                 format(c["キー無"], ","), format(c["色無"], ",")))

    if not a.apply:
        print("\n下読みだけで終了しました。書き込むには --apply を付けてください。")
        con.close()
        return 0
    if not plan:
        print("\n書き込む内容がありません。")
        con.close()
        return 0

    bdir = os.path.join(BASE, "db", "backups")
    os.makedirs(bdir, exist_ok=True)
    bak = os.path.join(bdir, "tokiwa_レンズカラー前_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    con.close()
    shutil.copy2(DB, bak)
    print("\nバックアップ: %s" % bak)
    con = sqlite3.connect(DB)
    con.executemany("UPDATE prescriptions SET lens_color=? WHERE id=?", plan)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM prescriptions "
                    "WHERE COALESCE(lens_color,'')<>''").fetchone()[0]
    print("書き込み完了。カラーが入っている処方箋: %s件" % format(n, ","))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
