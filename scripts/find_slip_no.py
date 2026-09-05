# -*- coding: utf-8 -*-
"""宝飾ナビの実データから「納品書No(仕入伝票番号)」の列を探す(2026-09-05)。

作った理由:
  トキワの商品に「仕入伝票番号」の欄を作った(v1.4.2)が、**過去の21万件は空**のまま。
  宝飾ナビ側に納品書Noを持っている列があるはずなのに、どのテーブルのどの列かが
  分からない。取込プログラムは d_user 74列のうち21列、d_item 81列のうち20列しか
  読んでおらず、**仕入テーブル(d_siire)にいたっては取込が一切実装されていない**。
  → まず「どの列か」を突き止めるための調査に使う。

  ※ scripts/find_column.py は「この値がどの列にあるか」を逆引きする道具。
    こちらは値が分からなくても **列名と中身の形から候補を絞れる** ようにしてある。
    紙の納品書の番号が分かっているなら、このスクリプトにも渡せる(--value)。

★このスクリプトは**読むだけ**。データは1文字も変更しない。
★個人情報は出さない(伏せ字のルールは scripts/_privacy.py に集約)。
  さらにこのスクリプトは**値そのものを並べず、「形」(桁数・英数字の並び)だけを出す**。

使い方:
  python3 scripts/find_slip_no.py
      → 商品まわりのテーブルの列を全部見て、納品書Noらしい列に★を付けて出す

  python3 scripts/find_slip_no.py --all
      → 商品まわりだけでなく**全テーブル**を見る(見つからなかった時)

  python3 scripts/find_slip_no.py --value 12345
      → 紙の納品書の番号を渡す。その値が入っている列を突き止める(一番確実)

  python3 scripts/find_slip_no.py --product 17543-1-01-20-130
      → 商品番号(管理番号)を渡す。その商品の行の全列を出すので、
        手元の納品書と見比べて「これだ」と目で確かめられる

  ★確認(これが一番はっきりする):
  python3 scripts/find_slip_no.py --product 21454 --find "納品書No=121463"
      → 「商品番号21454の行の中で、121463 が入っている列はどれか」を突き止める。
        宝飾ナビの『仕入商品登録・修正・削除』の画面を開いて、商品番号と
        納品書Noを読み取って渡せば、対応する列名が1発で分かる。
        複数の項目を一度に確かめてもよい:
          --find "納品書No=121463" --find "仕入品番=3S848" --find "伝票日付=2025/04/18"
        ※ここで渡す値は画面に見えている値をそのまま。全角/半角は気にしなくてよい。

出力の見方:
  入力率 … その列に値が入っている行の割合。低すぎる列は使い物にならない
  種類  … 値の種類数。★納品書Noなら「1枚の納品書に複数商品」なので
          種類数は行数よりかなり少ないはず(全部バラバラなら商品固有の番号=別物)
  形    … 値の形。9=数字 A=英字 - =記号。例 "99999"=5桁の数字
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _privacy import is_secret  # noqa: E402
import _paths  # noqa: E402

REAL_BASE = "data/real"
# 商品・仕入まわり。納品書Noがあるとすればこの辺(d_siire=仕入は取込未実装)
PRODUCT_TABLES = ["d_siire", "d_item", "d_item_memo", "d_tana", "d_jutaku"]

# 列名が納品書・伝票らしいか。宝飾ナビの列名はローマ字なので両方見る
SLIP_COL = re.compile(
    r"(nouhin|nohin|nouhinsho|denpyo|denpyou|denno|dennno|denp|slip|nofno|nyuka|"
    r"納品|伝票|仕入伝票|入荷)", re.IGNORECASE)
# 「番号らしい」語。上と組み合わせると精度が上がる
NO_COL = re.compile(r"(no$|no[^a-z]|number|bango|番号|ﾅﾝﾊﾞ|コード|code)", re.IGNORECASE)

SAMPLE_LIMIT = 20000        # 1テーブルから読む行数の上限(21万件を全部持たない)
SHAPE_LIMIT = 6             # 「形」を何種類まで出すか


def norm(v):
    return unicodedata.normalize("NFKC", "" if v is None else str(v)).strip()


def shape_of(s):
    """値の「形」にする。数字→9 / 英字→A / それ以外はそのまま。
    ★値そのものは出さないので、個人情報や取引先情報が漏れない。"""
    out = []
    for ch in s:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A")
        else:
            out.append(ch)
    # 同じ記号の連続はまとめない(桁数を見たいので、そのまま)
    return "".join(out)


def read_csv(path, limit=SAMPLE_LIMIT):
    """宝飾ナビの書き出しは cp932 のことが多いので順に試す。

    ★limit=None なら**全行**読む。値や商品番号を探す時は必ず全行読むこと——
      途中で打ち切ると、探しているものが後ろの方にあった場合に
      「見つかりません」と出てしまう(仕入 d_siire は16万件ある)。
      黙って取りこぼすのが一番まずい。
    """
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                head = None
                rows = []
                for i, row in enumerate(csv.reader(f)):
                    if i == 0:
                        head = row
                        continue
                    rows.append(row)
                    if limit is not None and len(rows) >= limit:
                        break
            return head or [], rows
        except UnicodeDecodeError:
            continue
    print("  [読めません] 文字コードを判定できませんでした: %s" % path)
    return [], []


KINDS_CAP = 5000    # 種類数を数える上限(これを超えたら「5000+」と出す。メモリ対策)


def stream_stats(path, head):
    """★ファイルを**全行**流し読みして、列ごとに 入力率・種類数・値の形 を集める。

    ★行を配列に貯めない(212,209件×81列を持つとメモリが足りない)。
      数えるものだけを持って読み捨てる。

    ★なぜ全行読むか(2026-09-05 店の実行結果で判明した重要な話):
      以前は先頭2万行だけで統計を取っていた。ところが宝飾ナビの書き出しは
      **商品キーの順=古い順**なので、先頭2万件は「一番古い9%」でしかない。
      その結果、実際には使われている項目まで「0.0% すべて空」と出てしまい、
      **「この項目は使われていない」と誤って判断する**ところだった。
      (実例: 仕入の伝票日付は先頭2万件では1.7%だが、2025年の画面には入っている)
    """
    filled = [0] * len(head)
    kinds = [set() for _ in head]
    over = [False] * len(head)
    shapes = [collections.Counter() for _ in head]
    n = 0
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rd = csv.reader(f)
                next(rd, None)          # 見出しを飛ばす
                for row in rd:
                    n += 1
                    for ci in range(len(head)):
                        if ci >= len(row):
                            continue
                        v = norm(row[ci])
                        if not v:
                            continue
                        filled[ci] += 1
                        if not over[ci]:
                            kinds[ci].add(v)
                            if len(kinds[ci]) > KINDS_CAP:
                                over[ci] = True
                                kinds[ci] = set()   # もう数えないので捨てる
                        shapes[ci][shape_of(v)] += 1
            break
        except UnicodeDecodeError:
            continue
    else:
        return n, []
    out = []
    for ci, col in enumerate(head):
        out.append({
            "col": col, "idx": ci, "n": n, "filled": filled[ci],
            "rate": (filled[ci] / n * 100) if n else 0.0,
            "kinds": ("%d+" % KINDS_CAP) if over[ci] else len(kinds[ci]),
            "kinds_num": (KINDS_CAP + 1) if over[ci] else len(kinds[ci]),
            "shapes": shapes[ci].most_common(SHAPE_LIMIT),
            "secret": is_secret(col),
        })
    return n, out


def score(st):
    """納品書Noらしさ。列名＋中身の形の両方で見る。"""
    s = 0
    if SLIP_COL.search(st["col"]):
        s += 10
    if NO_COL.search(st["col"]):
        s += 3
    if st["rate"] >= 50:
        s += 2
    # ★1枚の納品書に複数商品が載るので、種類数は行数よりかなり少ないはず。
    #   全部バラバラ(種類≒行数)なら商品固有の番号で、納品書Noではない
    if st["filled"] and st["kinds_num"] < st["filled"] * 0.6:
        s += 4
    # 数字だけ・数字と記号だけの短い値が納品書Noらしい
    if st["shapes"]:
        top = st["shapes"][0][0]
        if re.fullmatch(r"[9\-]{3,12}", top):
            s += 3
    return s


def show_table(path, want_value=None, want_product=None, finds=None, found=None, key_col=None):
    found = found if found is not None else []
    name = os.path.splitext(os.path.basename(path))[0]
    # ★何かを「探す」時は全行読む(打ち切ると取りこぼして「無い」と誤答するため)。
    #   列の統計を見るだけの時は、速さのために上限まででよい
    searching = bool(want_value or want_product or finds)
    # 探す時だけ行を配列で持つ(全行)。統計は行を貯めずに流し読みする
    head, rows = read_csv(path, None) if searching else (read_csv(path, 1)[0], [])
    if not head:
        return []
    print("\n" + "=" * 72)
    # 列の統計は「候補の絞り込み」の時だけ出す。
    # ★探している時に114表ぶんの一覧を出すと、肝心の答えが埋もれて見つけられない
    stats = []
    if searching:
        print("■ %s  (列 %d / 読んだ行 %d)" % (name, len(head), len(rows)))
    else:
        total, stats = stream_stats(path, head)
        print("■ %s  (列 %d / 全 %d行)" % (name, len(head), total))
    if stats:
        ranked = sorted(stats, key=lambda st: (-score(st), st["idx"]))
        print("  %-22s %7s %8s %8s  %s" % ("列名", "入力率", "入力数", "種類", "形(多い順)"))
        for st in ranked:
            mark = "★" if score(st) >= 10 else ("・" if score(st) >= 7 else "  ")
            shapes = "(伏せ字)" if st["secret"] else \
                " / ".join("%s×%d" % (sh, c) for sh, c in st["shapes"]) or "(すべて空)"
            print("  %s%-20s %6.1f%% %8d %8s  %s"
                  % (mark, st["col"][:20], st["rate"], st["filled"], st["kinds"], shapes[:60]))
    hits = []
    # 値で逆引き(紙の納品書の番号を渡された場合)
    if want_value:
        # ★stats は「探している時」は作らないので、列は head から数える
        nv = norm(want_value).casefold()
        for ci, col in enumerate(head):
            k = sum(1 for r in rows if ci < len(r) and norm(r[ci]).casefold() == nv)
            if k:
                hits.append((name, col, k))
                print("  ★ %s に 「%s」 が入っています(%d行)" % (col, want_value, k))
    # 商品番号でその行の全列を出す(手元の納品書と見比べる用)。
    # ★--find を一緒に渡すと、その行の中で値が一致した列に★を付けて確定できる
    finds = finds or []
    if want_product:
        np_ = norm(want_product).casefold()
        shown = 0
        for i, r in enumerate(rows, start=2):
            # ★どの列で一致したかを必ず出す(2026-09-05 追加)。
            #   宝飾ナビは「商品番号(strsyno)」と「商品キー(lngsykey)」が**別物**で、
            #   たまたま同じ数字が入っていることがある。列名を出さないと、
            #   まったく別の商品の行を見て「納品書Noが無い」と誤って結論してしまう
            #   (実際に商品番号21454で、商品キー21454の別商品が3件出た)。
            matched = [head[ci] if ci < len(head) else "?"
                       for ci, c in enumerate(r) if norm(c).casefold() == np_]
            if not matched:
                continue
            if key_col and not any(m == key_col for m in matched):
                continue
            shown += 1
            if shown > 5:
                print("  … 一致する行が他にもあります(表示は5行まで)")
                break
            print("\n  ■ %s の %d行目 が一致【%s = %s】── 手元の画面と見比べてください"
                  % (name, i, " / ".join(matched), want_product))
            for ci, (col, val) in enumerate(zip(head, r)):
                v = norm(val)
                if not v:
                    continue
                hit_label = None
                for label, want in finds:
                    if norm(want).casefold() == v.casefold():
                        hit_label = label
                        found.append((name, col, label, i))
                        break
                shown_val = "(伏せ字)" if is_secret(col, v) else v[:60]
                if hit_label:
                    print("    ★ %-22s = %-20s ← 【%s】はこの列です" % (col[:22], shown_val, hit_label))
                else:
                    print("      %-22s = %s" % (col[:22], shown_val))
            # ★空の列は上に出さないので、「列はあるが空だった」ことが分からない。
            #   伝票・納品書らしい列だけは、空でも名前を出す(存在するのに空 ≠ 列が無い)
            blanks = [c for ci2, c in enumerate(head)
                      if SLIP_COL.search(c) and (ci2 >= len(r) or not norm(r[ci2]))]
            if blanks:
                print("      (この行では空だった伝票らしい列: %s)" % " / ".join(blanks))
        if not shown:
            print("  (商品番号 %s の行はこの表にありません)" % want_product)
    return hits


def main():
    ap = argparse.ArgumentParser(description="宝飾ナビの実データから納品書Noの列を探す(読むだけ)")
    ap.add_argument("--all", action="store_true", help="商品まわり以外の全テーブルも見る")
    ap.add_argument("--value", help="紙の納品書の番号。その値が入っている列を突き止める")
    ap.add_argument("--product", help="商品番号(管理番号)。その行の全列を出す")
    ap.add_argument("--key-col", metavar="列名",
                    help="--product をこの列だけで照合する(例 --key-col strsyno / lngsykey)。"
                         "★宝飾ナビは商品番号(strsyno)と商品キー(lngsykey)が別物で、"
                         "同じ数字が入っていることがある。別商品を拾ってしまう時に使う")
    ap.add_argument("--find", action="append", default=[], metavar="項目名=値",
                    help="画面で見えている値。--product と一緒に使うと、その行の"
                         "どの列かを確定できる(例 --find \"納品書No=121463\")。何度でも指定可")
    a = ap.parse_args()
    finds = []
    for f in a.find:
        if "=" not in f:
            print("--find は「項目名=値」の形で指定してください(例 --find \"納品書No=121463\")")
            return 1
        label, _, val = f.partition("=")
        finds.append((label.strip(), val.strip()))
    if finds and not a.product:
        # 商品番号なしでも、値だけで全表を探せるようにする(--value と同じ扱い)
        print("※--product が無いので、値だけで全体から探します。")

    csv_dir = _paths.find_dir(REAL_BASE, "*.csv", "csv")
    files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))
    if not files:
        print("実データのCSVが見つかりません: %s" % csv_dir)
        print("宝飾ナビの書き出しを data/real/csv/ に置いてから実行してください。")
        return 1
    if not a.all:
        pick = [f for f in files
                if os.path.splitext(os.path.basename(f))[0] in PRODUCT_TABLES]
        if pick:
            files = pick
        else:
            print("※商品まわりのテーブル(%s)が見つからないので、全テーブルを見ます。"
                  % "/".join(PRODUCT_TABLES))

    print("読むだけの調査です。データは一切変更しません。")
    print("対象: %d ファイル(%s)" % (len(files), csv_dir))
    hits, found = [], []
    # --find だけで --product が無い時は、値そのもので全体を探す(--value と同じ動き)
    extra_values = [v for _, v in finds] if (finds and not a.product) else []
    for f in files:
        hits += show_table(f, a.value, a.product, finds, found, a.key_col)
        for v in extra_values:
            hits += show_table(f, v, None, None, found, None)

    print("\n" + "=" * 72)
    if found:
        # ★これが一番はっきりした答え。画面で見えている項目 → 実際の列名
        print("★ 画面の項目 → 宝飾ナビの列名 が分かりました:")
        seen = set()
        for name, col, label, i in found:
            k = (name, col, label)
            if k in seen:
                continue
            seen.add(k)
            print("     【%s】 = %s . %s   (%s の %d行目で確認)" % (label, name, col, name, i))
        print("\n  → この列名を教えてください。取込に追加して、過去分を埋められます。")
        print("     ★念のため、別の商品番号でもう1回試して同じ列になるか確かめると確実です")
        print("       (たまたま同じ値が別の列に入っていただけ、という取り違えを防げます)。")
    if a.value or (finds and not a.product):
        want = a.value or "・".join(v for _, v in finds)
        if hits:
            print("★ 指定の値「%s」が見つかった列:" % want)
            for name, col, k in sorted(hits, key=lambda x: -x[2]):
                print("     %s . %s   (%d行で一致)" % (name, col, k))
            print("\n  → この列名を教えてください。取込に追加して、過去分を埋められます。")
        else:
            print("指定の値「%s」はどの列にも見つかりませんでした。" % want)
            print("  ・--all を付けて全テーブルを見る")
            print("  ・番号の書き方を変えて試す(先頭の0を省いた/付けた 等)")
    elif a.product and finds:
        if not found:
            print("商品番号 %s の行は見つかりましたが、指定した値と一致する列はありませんでした。"
                  % a.product)
            print("  ・--all を付けて全テーブルを見る(仕入は d_siire にあるはずです)")
            print("  ・画面の表示と保存されている値が違うことがあります"
                  "(日付の区切り・先頭の0・全角/半角)。--value で値だけを探すのも有効です")
    elif not found:
        print("★の付いた列が納品書Noの候補です。次にやること:")
        print("  1. 紙の納品書の番号を1つ用意して")
        print("     python3 scripts/find_slip_no.py --value <その番号>")
        print("  2. または、その納品書に載っている商品の番号で")
        print("     python3 scripts/find_slip_no.py --product <商品番号>")
        print("  どちらかで列を1つに絞れたら、その列名を教えてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
