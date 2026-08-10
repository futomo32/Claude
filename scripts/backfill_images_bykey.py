#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品写真をファイル名から突き合わせて後埋めする(B-7の第2弾)。

ファイル名の規則(2026-08-10 diag_image_naming.py の実測で確定):
  「{店舗番号(前ゼロ無し)}{商品番号}.jpg」と「同_連番.jpg」。
  例: 店01・商品番号04714 → 104714.jpg, 104714_2.jpg …
  実データ7,121種のうち93.6%がこの解釈で商品に一致した(キー解釈は誤りで、
  一度6,353件を誤紐付けし --undo で取り消した経緯がある。同じ過ちを繰り返さない
  こと: 解釈を変える時は必ず diag_image_naming.py で一致率を確かめる)。

連番の意味(2026-08-06 店の確認):
  写真の登録履歴(誤登録も残る)。**一番大きい連番が現在の写真**。
  連番なしのファイルは一番古い履歴なので、連番付きが1枚も無い時だけ使う。

同じ店舗+番号を複数の商品が使っている問題(番号の使い回し・5,316種):
  写真がどの商品のものかはファイル名からは決められない。既定では宝飾ナビと
  同じ見え方に合わせ、**その店舗+番号を持つ全商品に同じ代表写真を付ける**。
  (誤りが混ざり得るが、ナビでも同じ表示だったもの。厳密にしたい場合は
   --strict で「1商品に確定する時だけ付ける」に切り替えられる)

使い方(店のPC):
  python3 scripts/backfill_images_bykey.py            # まず結果を見る(書き込まない)
  python3 scripts/backfill_images_bykey.py --apply    # 内容に納得したら反映
  python3 scripts/backfill_images_bykey.py --strict   # 1商品に確定する分だけ(＋--applyで反映)
  python3 scripts/backfill_images_bykey.py --undo     # この方式で付けた写真を全部外す

安全策:
  ・既に写真が付いている商品(strpicfilename由来・画面から登録)は上書きしない
  ・書くのは「数字だけ(＋_連番)」のファイル名のみ。この形はこのスクリプトしか
    書かないので、--undo で自分の分だけ正確に外せる
出力は件数と番号だけ。顧客情報は出さない。
"""
import os
import re
import sqlite3
import sys
from collections import defaultdict

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
IMG_DIR = os.path.join(BASE, "data", "real", "images")

# 「123456.jpg」「123456_2.jpg」だけを対象にする(K01+日時型など他の命名は触らない)
FNAME = re.compile(r"^(\d+)(?:_(\d+))?\.(jpe?g|png)$", re.IGNORECASE)


def undo(con):
    """このスクリプトが付けた写真を全部外す。
    「数字だけ(＋_連番)のファイル名」を image_file に書くのはこのスクリプトだけなので、
    その形の紐付けを空に戻せば反映前と同じ状態になる。"""
    hits = [(pk,) for pk, img in con.execute(
        "SELECT product_key, image_file FROM products WHERE COALESCE(image_file,'')<>''")
        if FNAME.match(img or "")]
    con.executemany("UPDATE products SET image_file=NULL WHERE product_key=?", hits)
    con.commit()
    print(f"取り消しました: {len(hits):,}件(数字名形式の写真の紐付けを外しました)")


def main():
    apply_mode = "--apply" in sys.argv
    strict = "--strict" in sys.argv
    if not os.path.exists(DB):
        sys.exit(f"[エラー] DBがありません: {DB}")
    if "--undo" in sys.argv:
        con = sqlite3.connect(DB)
        undo(con)
        con.close()
        return
    if not os.path.isdir(IMG_DIR):
        sys.exit(f"[エラー] 画像フォルダがありません: {IMG_DIR}")

    # ── 画像を「数字部分」ごとにまとめ、代表(一番大きい連番)を選ぶ ──
    groups = defaultdict(list)   # "104714" → [(連番, ファイル名), ...]
    others = 0
    for fn in os.listdir(IMG_DIR):
        m = FNAME.match(fn)
        if not m:
            others += 1          # K01型(strpicfilename由来)などはここ。触らない
            continue
        groups[m.group(1)].append((int(m.group(2) or 0), fn))
    best = {k: max(v)[1] for k, v in groups.items()}

    # ── 商品側: 「店舗番号(前ゼロ無し)+商品番号」→ 商品の一覧 ──
    con = sqlite3.connect(DB)
    by_sno = defaultdict(list)   # "104714" → [(product_key, image_file), ...]
    for pk, no, img in con.execute("SELECT product_key, product_no, image_file FROM products"):
        store, _, _key = str(pk or "").partition("-")
        no = str(no or "").strip()
        if not (store.isdigit() and no.isdigit()):
            continue             # 番号が英字混じり(R-5000等)の商品はこの命名の対象外
        by_sno[str(int(store)) + no].append((pk, img))

    assign, skipped_multi, skipped_has, unmatched = [], 0, 0, 0
    for digits, fn in sorted(best.items()):
        prods = by_sno.get(digits)
        if not prods:
            unmatched += 1
            continue
        if strict and len(prods) > 1:
            skipped_multi += 1
            continue
        for pk, img in prods:
            if img:
                skipped_has += 1     # 既に写真あり → 上書きしない
            else:
                assign.append((fn, pk))

    print("=" * 64)
    print(f"  画像フォルダ: 数字名形式 {sum(len(v) for v in groups.values()):,}枚"
          f"(番号{len(groups):,}種) / その他の命名 {others:,}枚(対象外)")
    print(f"  紐付けする商品          : {len(assign):,}件"
          + ("(--strict: 1商品に確定する番号のみ)" if strict else "(同じ店舗+番号の商品は全員に同じ代表写真)"))
    print(f"  既に写真ありでスキップ  : {skipped_has:,}件")
    if strict:
        print(f"  複数商品に該当でスキップ: {skipped_multi:,}番号")
    print(f"  該当商品なしのファイル  : {unmatched:,}番号(削除済み・未取込の商品の写真。無害)")
    print("=" * 64)

    if not apply_mode:
        print("★ドライランです。まだ何も書いていません。")
        print("  内容が妥当なら --apply を付けて実行してください。")
        con.close()
        return

    con.executemany(
        "UPDATE products SET image_file=? WHERE product_key=? AND (image_file IS NULL OR image_file='')",
        assign)
    con.commit()
    con.close()
    print(f"反映しました: {len(assign):,}件")
    print("トキワを開き直して(またはF5)、商品・在庫や購入履歴で写真を確認してください。")


if __name__ == "__main__":
    main()
