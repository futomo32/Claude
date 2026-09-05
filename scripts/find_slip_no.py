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


def read_csv(path):
    """宝飾ナビの書き出しは cp932 のことが多いので順に試す。"""
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
                    if len(rows) >= SAMPLE_LIMIT:
                        break
            return head or [], rows
        except UnicodeDecodeError:
            continue
    print("  [読めません] 文字コードを判定できませんでした: %s" % path)
    return [], []


def col_stats(head, rows):
    """列ごとに 入力率・種類数・値の形 を集める。★値そのものは持たない。"""
    n = len(rows)
    out = []
    for ci, col in enumerate(head):
        vals = [norm(r[ci]) for r in rows if ci < len(r)]
        filled = [v for v in vals if v != ""]
        shapes = collections.Counter(shape_of(v) for v in filled)
        out.append({
            "col": col, "idx": ci, "n": n, "filled": len(filled),
            "rate": (len(filled) / n * 100) if n else 0.0,
            "kinds": len(set(filled)),
            "shapes": shapes.most_common(SHAPE_LIMIT),
            "secret": is_secret(col),
        })
    return out


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
    if st["filled"] and st["kinds"] < st["filled"] * 0.6:
        s += 4
    # 数字だけ・数字と記号だけの短い値が納品書Noらしい
    if st["shapes"]:
        top = st["shapes"][0][0]
        if re.fullmatch(r"[9\-]{3,12}", top):
            s += 3
    return s


def show_table(path, want_value=None, want_product=None):
    name = os.path.splitext(os.path.basename(path))[0]
    head, rows = read_csv(path)
    if not head:
        return []
    print("\n" + "=" * 72)
    print("■ %s  (列 %d / 読んだ行 %d%s)"
          % (name, len(head), len(rows), " ※上限まで" if len(rows) >= SAMPLE_LIMIT else ""))
    stats = col_stats(head, rows)
    ranked = sorted(stats, key=lambda st: (-score(st), st["idx"]))
    print("  %-22s %7s %8s %8s  %s" % ("列名", "入力率", "入力数", "種類", "形(多い順)"))
    for st in ranked:
        mark = "★" if score(st) >= 10 else ("・" if score(st) >= 7 else "  ")
        shapes = "(伏せ字)" if st["secret"] else \
            " / ".join("%s×%d" % (sh, c) for sh, c in st["shapes"]) or "(すべて空)"
        print("  %s%-20s %6.1f%% %8d %8d  %s"
              % (mark, st["col"][:20], st["rate"], st["filled"], st["kinds"], shapes[:60]))
    hits = []
    # 値で逆引き(紙の納品書の番号を渡された場合)
    if want_value:
        nv = norm(want_value).casefold()
        for st in stats:
            ci = st["idx"]
            k = sum(1 for r in rows if ci < len(r) and norm(r[ci]).casefold() == nv)
            if k:
                hits.append((name, st["col"], k))
    # 商品番号でその行の全列を出す(手元の納品書と見比べる用)
    if want_product:
        np_ = norm(want_product).casefold()
        shown = 0
        for i, r in enumerate(rows, start=2):
            if not any(norm(c).casefold() == np_ for c in r):
                continue
            shown += 1
            if shown > 3:
                print("  … 同じ商品番号の行が他にもあります(表示は3行まで)")
                break
            print("\n  ■ %s の %d行目 が一致 ── 手元の納品書と見比べてください" % (name, i))
            for col, val in zip(head, r):
                v = norm(val)
                if not v:
                    continue
                print("      %-22s = %s" % (col[:22], "(伏せ字)" if is_secret(col, v) else v[:60]))
    return hits


def main():
    ap = argparse.ArgumentParser(description="宝飾ナビの実データから納品書Noの列を探す(読むだけ)")
    ap.add_argument("--all", action="store_true", help="商品まわり以外の全テーブルも見る")
    ap.add_argument("--value", help="紙の納品書の番号。その値が入っている列を突き止める")
    ap.add_argument("--product", help="商品番号(管理番号)。その行の全列を出す")
    a = ap.parse_args()

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
    hits = []
    for f in files:
        hits += show_table(f, a.value, a.product)

    print("\n" + "=" * 72)
    if a.value:
        if hits:
            print("★ 指定の番号「%s」が見つかった列:" % a.value)
            for name, col, k in sorted(hits, key=lambda x: -x[2]):
                print("     %s . %s   (%d行で一致)" % (name, col, k))
            print("\n  → この列名を教えてください。取込に追加して、過去分を埋められます。")
        else:
            print("指定の番号「%s」はどの列にも見つかりませんでした。" % a.value)
            print("  ・--all を付けて全テーブルを見る")
            print("  ・番号の書き方を変えて試す(先頭の0を省いた/付けた 等)")
    else:
        print("★の付いた列が納品書Noの候補です。次にやること:")
        print("  1. 紙の納品書の番号を1つ用意して")
        print("     python3 scripts/find_slip_no.py --value <その番号>")
        print("  2. または、その納品書に載っている商品の番号で")
        print("     python3 scripts/find_slip_no.py --product <商品番号>")
        print("  どちらかで列を1つに絞れたら、その列名を教えてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
