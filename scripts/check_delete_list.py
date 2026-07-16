# -*- coding: utf-8 -*-
"""削除商品番号リストのプレビュー(読み取り専用・実際には消さない)。

data/real/削除商品番号.txt に書いた商品番号(1行ずつ)が、実データの商品台帳(d_item)の
どれに一致するか、重複はないか、販売履歴(d_hanbai)があるものが含まれていないかを確認する。
「販売履歴あり」の商品を消すと購入履歴の商品名が表示できなくなるため、事前に警告する。

  python3 scripts/check_delete_list.py

出力するのは件数と商品番号のみ(顧客名等の個人情報は出さない)。
"""
import csv
import os
import sys
from collections import defaultdict

csv.field_size_limit(10 * 1024 * 1024)
BASE = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(BASE, "data", "real")
CSV = os.path.join(REAL, "csv")
LIST = os.path.join(REAL, "削除商品番号.txt")


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
    if not os.path.exists(LIST):
        print(f"[エラー] 削除リストがありません: {LIST}")
        print("  消したい商品番号を1行ずつ書いたテキストを data/real/削除商品番号.txt に置いてください。")
        sys.exit(1)
    del_nos = set()
    with open(LIST, encoding="utf-8") as f:
        for line in f:
            v = line.strip()
            if v and not v.startswith("#"):
                del_nos.add(v)
    print(f"削除リストの商品番号: {len(del_nos):,} 件\n")

    # d_item を走査: 商品番号→(店-キー)の一覧(重複=同じ番号が複数商品)
    matched = defaultdict(list)   # 商品番号 → [product_key,...]
    key_of_no = {}                # product_key → 商品番号(販売履歴照合用)
    for r in rows("d_item"):
        no = s(r.get("strsyno"))
        if no in del_nos:
            tc, sk = s(r.get("strsytencode")), s(r.get("lngsykey"))
            pk = f"{tc}-{sk}" if tc and sk else None
            if pk:
                matched[no].append(pk)
                key_of_no[pk] = no

    matched_keys = set(key_of_no)
    print(f"商品台帳で一致した商品: {sum(len(v) for v in matched.values()):,} 件"
          f"(ユニーク商品番号 {len(matched):,} 件)")
    not_found = del_nos - set(matched)
    if not_found:
        print(f"  ※商品台帳に見つからない番号: {len(not_found):,} 件(既に無い/入力ミスの可能性)")
        print("    " + ", ".join(sorted(not_found)[:20]) + (" …" if len(not_found) > 20 else ""))

    dup = {no: ks for no, ks in matched.items() if len(ks) > 1}
    print(f"\n■ 同じ商品番号が複数商品に付いている(まとめて消える): {len(dup):,} 番号")
    for no, ks in list(dup.items())[:15]:
        print(f"    番号 {no} → {len(ks)}商品")

    # 販売履歴(d_hanbai)に、削除対象の商品キーが使われていないか
    sold = set()
    for r in rows("d_hanbai"):
        tc, sk = s(r.get("strsytencode")), s(r.get("lngsykey"))
        pk = f"{tc}-{sk}" if tc and sk else None
        if pk in matched_keys:
            sold.add(pk)
    print(f"\n■ 販売履歴がある商品(消すと購入履歴の商品名が出なくなる=要確認): {len(sold):,} 件")
    if sold:
        sold_nos = sorted(set(key_of_no[pk] for pk in sold))
        print("    該当商品番号: " + ", ".join(sold_nos[:30]) + (" …" if len(sold_nos) > 30 else ""))
        print("    → これらは本当に消してよいか要確認(不明在庫なら通常は販売履歴なしのはず)")
    else:
        print("    (なし=すべて未販売。そのまま除外して問題なし)")

    print(f"\n== まとめ ==")
    print(f"  除外される商品: {len(matched_keys):,} 件(うち販売履歴あり {len(sold):,} 件)")
    print("  問題なければ import_csv.py を実行すると、これらを除外して本番DBを作り直します。")


if __name__ == "__main__":
    main()
