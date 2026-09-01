# -*- coding: utf-8 -*-
"""削除リスト(data/real/削除商品番号.txt)の読み方をまとめた共通部品(2026-09-01 追加)。

★import_csv.py と check_delete_list.py の**両方**がここを使う。
  以前は同じ判定を2か所に書いていて「片方だけ直す」事故が起きやすかったため、
  読み方と当たり判定をここ1か所に集めた。

【書き方】1行に1つ。`#` で始まる行はコメント。
    104714              商品番号だけ。今まで通り
    104714,72000        商品番号＋仕入価格。両方合ったものだけ
    01-104714           商品キー(店コード-商品ID)。その1件だけを狙い撃ち
    104714,72000,メモ    3列目以降は無視されるのでメモに使える

【なぜ2列目が要るのか】
宝飾ナビは**同じ商品番号を別の商品に使い回している**。状態が「在庫」のものだけを
消すルール(下記)でほとんどは1件に決まるが、**同じ番号で在庫が2件以上ある**場合だけは
どちらを消すのか決まらない。そこで仕入価格を添えて絞れるようにした。
どの番号がそれに当たるかは check_delete_list.py が一覧で教えてくれる。

【消す条件(ここは変えていない)】
一致した商品のうち、**状態が「在庫」のものだけ**を取り込まない。売上・返品・受託は
必ず残す(売れた商品を消すと購入履歴で商品名が出せなくなる。受託は他社の預かり品)。
商品キーで指定した場合も同じ(狙い撃ちでも、売れている商品は消さない)。
"""
import os
import re
import unicodedata


def money(v):
    """金額を整数に。桁区切りのカンマ・円・￥・小数点以下は無視する。
    数字にならなければ None。"""
    t = unicodedata.normalize("NFKC", str(v if v is not None else "")).strip()
    t = t.replace(",", "").replace("¥", "").replace("円", "").replace(" ", "")
    if not t:
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


class DelList:
    """削除リストの中身。`nos` は商品番号、`keys` は商品キー。

    nos[商品番号] は None なら「価格を問わない」、集合なら「その仕入価格のものだけ」。
    """

    def __init__(self):
        self.nos = {}
        self.keys = set()
        self.errors = []     # (行番号, 元の行, 理由)
        self.n_lines = 0

    def __bool__(self):
        return bool(self.nos or self.keys)

    def hit(self, product_no, product_key, cost_price):
        """この商品がリストに当たるか。★在庫かどうかの判定は呼び側で行う。"""
        if product_key and product_key in self.keys:
            return True
        if product_no in self.nos:
            prices = self.nos[product_no]
            if prices is None:
                return True
            return money(cost_price) in prices
        return False


def _merge_thousands(parts):
    """`00465,140,000` のように**桁区切りのカンマ**で分かれてしまった欄をつなぎ直す。

    Excelの金額をそのまま貼ると `140,000` になるため、カンマで割ると欄がずれる。
    3桁ちょうどの数字が、数字だけの欄の後ろに来ていたら桁区切りとみなしてつなぐ。
    ★1列目(商品番号)には決してつながない——`123,456`(番号123・価格456)を
      `123456` に化けさせないため。
    """
    out = list(parts)
    i = 2
    while i < len(out):
        if re.match(r"^\d{3}$", out[i]) and re.match(r"^\d+$", out[i - 1]):
            out[i - 1] = out[i - 1] + out[i]
            del out[i]
        else:
            i += 1
    return out


def load(path):
    """削除リストを読む。ファイルが無ければ空の DelList を返す。

    ★書き方が違う行は黙って捨てず、errors に理由を積む(呼び側が画面に出す)。
    「消したつもりで消えていない」を防ぐため。
    """
    d = DelList()
    if not os.path.exists(path):
        return d
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        with open(path, encoding="cp932", errors="replace") as f:
            lines = f.readlines()

    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        d.n_lines += 1
        parts = _merge_thousands(
            [p.strip() for p in unicodedata.normalize("NFKC", line).split(",")])
        first = parts[0]
        if not first:
            d.errors.append((i, line, "1列目(商品番号)が空です"))
            continue
        # 「店コード-商品ID」の形なら商品キーとして扱う(その1件だけを狙い撃ち)
        if re.match(r"^\w+-\w+$", first):
            if len(parts) > 1 and parts[1]:
                d.errors.append((i, line, "商品キー指定に価格は付けられません(その1件だけが対象のため)"))
                continue
            d.keys.add(first)
            continue
        price = None
        if len(parts) > 1 and parts[1]:
            price = money(parts[1])
            if price is None:
                d.errors.append((i, line, f"2列目『{parts[1]}』が金額として読めません(仕入価格を数字で)"))
                continue
        if price is None:
            # 価格指定なし = その番号は価格を問わない。既にあった価格指定より優先する
            d.nos[first] = None
        elif first not in d.nos:
            d.nos[first] = {price}
        elif d.nos[first] is not None:
            d.nos[first].add(price)
    return d
