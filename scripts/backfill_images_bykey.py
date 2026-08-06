#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品写真をファイル名の商品キーから突き合わせて後埋めする(B-7の第2弾)。

背景(2026-08-06):
  トキワが写真を知る経路は d_item.strpicfilename だけだが、入力率4.2%しかない。
  一方 data/real/images/ には「キー.jpg」「キー_連番.jpg」形式のファイルが大量にあり、
  宝飾ナビはこの命名で写真を持っている。ただし実物を確認した結果:
    - 104714 → 連番なし=サファイアペンダント / _2〜_4=オパールリング(別商品が混在)
    - 200169 → 連番なし・_2・_5=ピンクブレス / _3=サングラス / _4=別ブレス(3商品混在)
  ファイル名には店舗コードが無く、キーの数字は台帳(01本店/98ビジュ等)ごとに別々に
  振られるため、**同じ数字に複数商品の写真が混ざる**。連番の大小にも規則性が無い。

方針: ★間違った写真を付けるくらいなら付けない(安全側)。
  1. キーの数字がトキワの商品1件だけに該当する場合のみ紐付ける
     (この場合、その数字の写真は全部その商品のもの。代表は一番大きい連番)
  2. 複数商品に該当する数字(店舗またぎの重複)は紐付けず、件数を報告するだけ
  3. 既に写真が付いている商品(strpicfilename由来)は上書きしない
  4. 既定は「何が起きるか表示するだけ」(ドライラン)。実際に書くのは --apply

使い方(店のPC):
  python3 scripts/backfill_images_bykey.py           # まず結果を見る(書き込まない)
  python3 scripts/backfill_images_bykey.py --apply   # 内容に納得したら反映

出力は件数とキーの数字だけ。商品名・顧客名は出さない。
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


def main():
    apply_mode = "--apply" in sys.argv
    if not os.path.exists(DB):
        sys.exit(f"[エラー] DBがありません: {DB}")
    if not os.path.isdir(IMG_DIR):
        sys.exit(f"[エラー] 画像フォルダがありません: {IMG_DIR}")

    # ── 画像をキーの数字ごとにまとめ、代表(一番大きい連番)を選ぶ ──
    groups = defaultdict(list)   # "104714" → [(連番, ファイル名), ...]
    others = 0
    for fn in os.listdir(IMG_DIR):
        m = FNAME.match(fn)
        if not m:
            others += 1          # K01型(strpicfilename由来)などはここ。触らない
            continue
        groups[m.group(1)].append((int(m.group(2) or 0), fn))
    best = {k: max(v)[1] for k, v in groups.items()}

    # ── 商品側: キーの数字部分 → 商品の一覧 ──
    con = sqlite3.connect(DB)
    by_digits = defaultdict(list)   # "104714" → [(product_key, image_file), ...]
    for pk, img in con.execute("SELECT product_key, image_file FROM products"):
        digits = str(pk).split("-", 1)[-1]
        by_digits[digits].append((pk, img))

    assign, skipped_multi, skipped_has, unmatched = [], [], 0, 0
    for digits, fn in sorted(best.items()):
        prods = by_digits.get(digits)
        if not prods:
            unmatched += 1
            continue
        if len(prods) > 1:
            skipped_multi.append((digits, len(prods)))   # 店舗またぎの重複 → 触らない
            continue
        pk, img = prods[0]
        if img:
            skipped_has += 1                             # 既に写真あり → 上書きしない
            continue
        assign.append((fn, pk))

    print("=" * 64)
    print(f"  画像フォルダ: キー名形式 {sum(len(v) for v in groups.values()):,}枚"
          f"(キー{len(groups):,}種) / その他の命名 {others:,}枚(対象外)")
    print(f"  紐付けできる商品        : {len(assign):,}件(キーが1商品に確定するもののみ)")
    print(f"  既に写真ありでスキップ  : {skipped_has:,}件")
    print(f"  複数商品に該当でスキップ: {len(skipped_multi):,}キー ★別商品の写真が混在し得るため自動では付けない")
    print(f"  該当商品なしのファイル  : {unmatched:,}キー")
    if skipped_multi[:20]:
        print("  (複数該当キーの例: " + ", ".join(f"{d}({n}商品)" for d, n in skipped_multi[:20]) + ")")
    print("=" * 64)

    if not apply_mode:
        print("★ドライランです。まだ何も書いていません。")
        print("  内容が妥当なら --apply を付けて実行してください:")
        print("    python3 scripts/backfill_images_bykey.py --apply")
        con.close()
        return

    con.executemany(
        "UPDATE products SET image_file=? WHERE product_key=? AND (image_file IS NULL OR image_file='')",
        assign)
    con.commit()
    con.close()
    print(f"反映しました: {len(assign):,}件")
    print("トキワを開き直して(またはF5)、商品・在庫や購入履歴で写真を確認してください。")
    print("複数該当でスキップした商品は、商品詳細の「写真を撮る/選ぶ」から手で付けられます。")


if __name__ == "__main__":
    main()
