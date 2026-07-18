# -*- coding: utf-8 -*-
"""写真が出るはずの在庫品を数件ピックアップする(B-7の表示確認用)。

DBの products.image_file(backfill済み)と、実際の画像フォルダ data/real/images/ を
突き合わせ、「在庫」かつ「画像ファイルが実在する」商品を選んで商品番号を表示する。
ここに出た番号を在庫画面で検索すれば、写真が出るはずの確認ができる。

  python3 scripts/pick_photo_samples.py        # 既定5件
  python3 scripts/pick_photo_samples.py 10     # 件数指定

出力は商品番号・品名・画像ファイル名のみ(顧客の個人情報は扱わない)。
先に scripts/backfill_images.py を実行して image_file を埋めておくこと。
"""
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
IMAGES = os.path.join(BASE, "data", "real", "images")


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    if not os.path.exists(DB):
        sys.exit(f"DBがありません: {DB}")
    if not os.path.isdir(IMAGES):
        sys.exit(f"画像フォルダがありません: {IMAGES}")

    # 画像フォルダを索引化(サブフォルダ・大文字小文字を無視。サーバーと同じ探し方)
    index = {}
    for root, _dirs, fnames in os.walk(IMAGES):
        for fn in fnames:
            index.setdefault(fn.lower(), os.path.join(root, fn))

    con = sqlite3.connect(DB)
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if "image_file" not in cols:
        con.close()
        sys.exit("products.image_file 列がありません。先に migrate_db.py と backfill_images.py を実行してください。")

    found = []
    n_named = 0
    for r in con.execute("""SELECT product_no, name, image_file FROM products
                            WHERE state='在庫' AND image_file IS NOT NULL AND image_file<>''
                            ORDER BY product_no"""):
        n_named += 1
        base = os.path.basename((r[2] or "").replace("\\", "/")).lower()
        if base in index:
            found.append((r[0], r[1], r[2]))
            if len(found) >= want:
                break
    con.close()

    if not found:
        print("該当なし。backfill_images.py を実行済みか、画像フォルダの中身を確認してください。")
        print(f"(在庫かつ画像名ありの商品: {n_named:,} 件だが、実ファイルが見つからなかった)")
        return
    print(f"■ 写真が出るはずの在庫品 {len(found)} 件(この番号を在庫画面で検索して確認):")
    for pno, name, img in found:
        print(f"   商品番号 {pno}  /  {name}  /  画像 {img}")


if __name__ == "__main__":
    main()
