# -*- coding: utf-8 -*-
"""商品画像ファイルと商品データの対応チェック(読み取り専用・個人情報は出さない)。

宝飾ナビの商品台帳(d_item)は各商品の画像ファイル名(strpicfilename)を持ち、
追加画像は d_item_pic に入っている。実際に受領した画像フォルダ(data/real/images/)の
ファイルと突き合わせ、B-7(商品写真)を作る前に「どれくらい対応が取れているか」を確認する。

  python3 scripts/check_images.py                 # 画像は data/real/images/
  python3 scripts/check_images.py <画像フォルダ>   # 別の場所を指定

出力: 件数・カバー率・拡張子の内訳のみ(ファイル名の一部例は出すが個人情報ではない)。
"""
import csv
import os
import sys
from collections import Counter

csv.field_size_limit(10 * 1024 * 1024)
BASE = os.path.join(os.path.dirname(__file__), "..")
CSV = os.path.join(BASE, "data", "real", "csv")
IMG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "data", "real", "images")


def s(v):
    return (v or "").strip() or None


def rows(name):
    path = os.path.join(CSV, name + ".csv")
    if not os.path.exists(path):
        return
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline(); f.seek(0)
            break
        except UnicodeDecodeError:
            f.close()
    else:
        f = open(path, "r", encoding="cp932", errors="replace", newline="")
    try:
        for r in csv.DictReader(f):
            yield r
    finally:
        f.close()


def main():
    if not os.path.isdir(IMG):
        print(f"[エラー] 画像フォルダがありません: {IMG}")
        print("  受領した画像を data/real/images/ に置いてから実行してください。")
        sys.exit(1)

    # 画像フォルダ内のファイルを収集(サブフォルダも再帰。basenameで小文字化して照合)
    files_lower = {}   # 小文字basename → 実際のパス
    exts = Counter()
    total_bytes = 0
    n_files = 0
    for root, _dirs, fnames in os.walk(IMG):
        for fn in fnames:
            if fn.startswith("."):
                continue
            n_files += 1
            p = os.path.join(root, fn)
            try:
                total_bytes += os.path.getsize(p)
            except OSError:
                pass
            files_lower[fn.lower()] = p
            exts[os.path.splitext(fn)[1].lower() or "(拡張子なし)"] += 1
    print(f"■ 画像フォルダ: {IMG}")
    print(f"   ファイル数: {n_files:,} / 合計サイズ: {total_bytes/1024/1024:.0f} MB")
    print(f"   拡張子の内訳: {dict(exts)}")
    print()

    def resolve(name):
        """商品データの画像ファイル名が、実フォルダに存在するか(basename・小文字で照合)。"""
        if not name:
            return None
        base = os.path.basename(name.replace("\\", "/")).lower()
        return files_lower.get(base)

    # d_item のメイン画像
    n_prod = n_with_name = n_found = 0
    referenced = set()
    for r in rows("d_item"):
        n_prod += 1
        nm = s(r.get("strpicfilename"))
        if nm:
            n_with_name += 1
            hit = resolve(nm)
            if hit:
                n_found += 1
                referenced.add(hit)
    print(f"■ 商品台帳(d_item)のメイン画像")
    print(f"   商品総数: {n_prod:,}")
    print(f"   画像ファイル名が入っている商品: {n_with_name:,} 件")
    print(f"   → うち実ファイルが見つかった: {n_found:,} 件"
          f"({n_found*100//max(n_with_name,1)}%)")
    print(f"   → 名前はあるがファイルが無い: {n_with_name - n_found:,} 件")
    print()

    # d_item_pic の追加画像
    pic_total = pic_found = 0
    for r in rows("d_item_pic"):
        nm = s(r.get("strpicfilename"))
        if nm:
            pic_total += 1
            hit = resolve(nm)
            if hit:
                pic_found += 1
                referenced.add(hit)
    if pic_total:
        print(f"■ 追加画像(d_item_pic)")
        print(f"   追加画像の登録: {pic_total:,} 件 / 実ファイルあり: {pic_found:,} 件")
        print()

    orphan = n_files - len(referenced)
    print(f"■ どの商品からも参照されていない画像ファイル: 約 {orphan:,} 件")
    print("   (商品削除済み・別用途の画像など。B-7では参照されているものだけ表示すればよい)")
    print()
    print("== まとめ ==")
    print(f"  B-7(商品写真)で表示できる見込み: メイン画像 {n_found:,} 商品分")
    print("  カバー率が低い場合は、画像ファイル名の付け方(商品番号 or 商品キー)を確認して")
    print("  取り込みルールを調整する(次のB-7実装時に対応)。")


if __name__ == "__main__":
    main()
