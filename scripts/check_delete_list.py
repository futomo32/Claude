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
from collections import Counter, defaultdict

csv.field_size_limit(10 * 1024 * 1024)
BASE = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(BASE, "data", "real")
CSV = os.path.join(REAL, "csv")
LIST = os.path.join(REAL, "削除商品番号.txt")


def s(v):
    return (v or "").strip() or None


# 商品の状態(import_csv.py の STATE と同じ。片方だけ直さないこと)
STATE = {"0": "受託", "1": "在庫", "3": "売上", "5": "返品"}


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
    state_of_pk = {}              # product_key → 状態(在庫/売上/返品/受託)
    for r in rows("d_item"):
        no = s(r.get("strsyno"))
        if no in del_nos:
            tc, sk = s(r.get("strsytencode")), s(r.get("lngsykey"))
            pk = f"{tc}-{sk}" if tc and sk else None
            if pk:
                matched[no].append(pk)
                key_of_no[pk] = no
                state_of_pk[pk] = STATE.get(s(r.get("strjotaikbn")), "その他")

    matched_keys = set(key_of_no)
    print(f"商品台帳で一致した商品: {sum(len(v) for v in matched.values()):,} 件"
          f"(ユニーク商品番号 {len(matched):,} 件)")
    not_found = del_nos - set(matched)
    if not_found:
        print(f"  ※商品台帳に見つからない番号: {len(not_found):,} 件(既に無い/入力ミスの可能性)")
        print("    " + ", ".join(sorted(not_found)[:20]) + (" …" if len(not_found) > 20 else ""))

    dup = {no: ks for no, ks in matched.items() if len(ks) > 1}
    # ※「まとめて消える」わけではない(在庫のものだけ消える)。誤解を招くので表現を直した
    print(f"\n■ 同じ商品番号が複数商品に付いている: {len(dup):,} 番号"
          "  ※このうち消えるのは在庫のものだけです")
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

    # ★実際に消えるのは「在庫」だけ(2026-08-31 実装)。番号だけで消すと同じ番号の
    #   売れた商品まで巻き添えになるため、import_csv.py は在庫状態のものだけを除外する。
    by_state = Counter(state_of_pk.values())
    print("\n■ 一致した商品の状態(★消えるのは「在庫」だけです)")
    for st in ("在庫", "売上", "返品", "受託", "その他"):
        if by_state.get(st):
            mark = "← これだけ消えます" if st == "在庫" else "← 残します"
            print(f"    {st:4} : {by_state[st]:>6,}件  {mark}")

    will_delete = [pk for pk, st in state_of_pk.items() if st == "在庫"]
    del_sold = [pk for pk in will_delete if pk in sold]

    print("\n== まとめ ==")
    print(f"  リストに一致した商品 : {len(matched_keys):,} 件")
    print(f"  実際に消える商品     : {len(will_delete):,} 件(状態が「在庫」のものだけ)")
    print(f"  残る商品             : {len(matched_keys) - len(will_delete):,} 件"
          f"(売上・返品・受託。購入履歴を壊さないため)")
    if del_sold:
        print(f"  ★注意: 消える商品のうち {len(del_sold):,} 件に販売履歴があります。")
        print("     在庫のまま販売履歴があるのは不自然なので、リストを見直してください。")
    else:
        print("  消える商品に販売履歴はありません(想定どおり)。")
    print("\n  問題なければ import_csv.py を実行すると、これらを除外して本番DBを作り直します。")


if __name__ == "__main__":
    main()
