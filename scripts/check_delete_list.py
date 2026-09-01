# -*- coding: utf-8 -*-
"""削除商品番号リストのプレビュー(読み取り専用・実際には消さない)。

data/real/削除商品番号.txt に書いた内容が、実データの商品台帳(d_item)のどれに一致するか、
販売履歴(d_hanbai)があるものが含まれていないかを確認する。
「販売履歴あり」の商品を消すと購入履歴の商品名が表示できなくなるため、事前に警告する。

★**同じ商品番号で「在庫」が2件以上あるもの**を一覧に出す(2026-09-01 追加)。
  ここだけは番号だけでは1件に決まらないので、仕入価格を添えて絞る必要がある。
  そのまま貼れる形(`104714,72000`)で候補を表示する。

  python3 scripts/check_delete_list.py

リストの書き方は scripts/_dellist.py を参照(import_csv.py と共通の読み方)。
出力するのは件数と商品番号・金額のみ(顧客名等の個人情報は出さない)。
"""
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dellist as dellist   # noqa: E402  削除リストの読み方(import_csv.py と共通)

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
    dl = dellist.load(LIST)
    print(f"削除リストの指定: {len(dl.nos):,} 件(商品番号)"
          + (f" ＋ {len(dl.keys):,} 件(商品キー)" if dl.keys else ""))
    n_priced = sum(1 for v in dl.nos.values() if v is not None)
    if n_priced:
        print(f"  うち仕入価格で絞っているもの: {n_priced:,} 件")
    if dl.errors:
        print(f"\n  ★読めない行が {len(dl.errors)} 件あります(この行は無視されます)")
        for lineno, line, why in dl.errors[:15]:
            print(f"    {lineno}行目『{line}』… {why}")
        if len(dl.errors) > 15:
            print(f"    …他{len(dl.errors) - 15}件")
    print()

    # d_item を走査: 商品番号→(店-キー)の一覧(重複=同じ番号が複数商品)
    matched = defaultdict(list)   # 商品番号 → [product_key,...]
    key_of_no = {}                # product_key → 商品番号(販売履歴照合用)
    state_of_pk = {}              # product_key → 状態(在庫/売上/返品/受託)
    cost_of_pk = {}               # product_key → 仕入価格(絞り込みの候補を出すため)
    # ★同じ番号で在庫が2件以上あるものを見つけるため、リストの番号は価格指定に関係なく拾う
    stock_by_no = defaultdict(list)   # 商品番号 → [(product_key, 仕入価格), ...] ※在庫のみ
    seen_nos = set()                  # 商品台帳に存在した番号(価格で外れたものも含む)
    for r in rows("d_item"):
        no = s(r.get("strsyno"))
        tc, sk = s(r.get("strsytencode")), s(r.get("lngsykey"))
        pk = f"{tc}-{sk}" if tc and sk else None
        if not pk:
            continue
        st = STATE.get(s(r.get("strjotaikbn")), "その他")
        if no in dl.nos:
            seen_nos.add(no)
            if st == "在庫":
                stock_by_no[no].append((pk, dellist.money(r.get("curorokin"))))
        if dl.hit(no, pk, r.get("curorokin")):
            matched[no].append(pk)
            key_of_no[pk] = no
            state_of_pk[pk] = st
            cost_of_pk[pk] = dellist.money(r.get("curorokin"))

    matched_keys = set(key_of_no)
    print(f"商品台帳で一致した商品: {sum(len(v) for v in matched.values()):,} 件"
          f"(ユニーク商品番号 {len(matched):,} 件)")
    # ※価格で絞って外れただけの番号はここに出さない(下の「価格で絞ったが…」で扱う)
    not_found = set(dl.nos) - seen_nos
    if not_found:
        print(f"  ※商品台帳に見つからない番号: {len(not_found):,} 件(既に無い/入力ミスの可能性)")
        print("    " + ", ".join(sorted(not_found)[:20]) + (" …" if len(not_found) > 20 else ""))

    if dl.keys:
        found_keys = dl.keys & matched_keys
        print(f"  商品キー指定: {len(found_keys):,}/{len(dl.keys):,} 件が見つかりました")
        miss = sorted(dl.keys - matched_keys)
        if miss:
            print(f"  ※見つからない商品キー {len(miss):,} 件: "
                  + ", ".join(miss[:10]) + (" …" if len(miss) > 10 else ""))

    dup = {no: ks for no, ks in matched.items() if len(ks) > 1}
    # ※「まとめて消える」わけではない(在庫のものだけ消える)。誤解を招くので表現を直した
    print(f"\n■ 同じ商品番号が複数商品に付いている: {len(dup):,} 番号"
          "  ※このうち消えるのは在庫のものだけです")
    for no, ks in list(dup.items())[:15]:
        print(f"    番号 {no} → {len(ks)}商品")

    # ★ここが本題: 番号だけでは1件に決まらないもの(=在庫が2件以上ある番号)
    ambiguous = {no: v for no, v in stock_by_no.items()
                 if len(v) > 1 and dl.nos.get(no) is None}
    print(f"\n■ ★番号だけでは決まらないもの(在庫が2件以上ある番号): {len(ambiguous):,} 件")
    if not ambiguous:
        print("    (なし。すべての番号で在庫は1件なので、番号だけの指定で正しく消えます)")
    else:
        print("    この番号は「どちらの在庫を消すか」が決まりません。")
        print("    下の形で仕入価格を添えると1件に絞れます(そのまま削除商品番号.txt に貼れます):")
        print()
        for no, items in sorted(ambiguous.items())[:30]:
            costs = [c for _pk, c in items]
            print(f"    番号 {no} … 在庫{len(items)}件  仕入価格: "
                  + " / ".join(f"{c:,}" if c is not None else "(空欄)" for c in costs))
            for c in costs:
                if c is not None:
                    print(f"        {no},{c}")
        if len(ambiguous) > 30:
            print(f"    …他{len(ambiguous) - 30}件")
        print()
        print("    ※価格が同じで区別できない場合は、商品キー(例 01-104714)で指定してください。")

    # 価格で絞ったのに1件も当たらなかったもの(書き方の間違いに気づけるように)
    priced_miss = [no for no, v in dl.nos.items() if v is not None and not matched.get(no)]
    if priced_miss:
        print(f"\n■ ★価格で絞ったが1件も一致しなかった番号: {len(priced_miss):,} 件")
        print("    価格の入力ミスの可能性があります(このままだと消えません):")
        for no in priced_miss[:20]:
            have = stock_by_no.get(no, [])
            if have:
                print(f"    番号 {no} … 指定 {sorted(dl.nos[no])} / 実際の在庫の仕入価格 "
                      + " / ".join(f"{c:,}" if c is not None else "(空欄)" for _pk, c in have))
            else:
                print(f"    番号 {no} … 在庫が1件もありません")
        if len(priced_miss) > 20:
            print(f"    …他{len(priced_miss) - 20}件")

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
    print(f"  リストの指定         : {dl.n_lines:,} 行"
          + (f"(うち読めない行 {len(dl.errors):,})" if dl.errors else ""))
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
