# -*- coding: utf-8 -*-
"""消費税の計算を1か所にまとめた部品(2026-09-02 新設)。

★これまで税率(10%)と税額の計算が**7か所に直書き**されていた
  (db_query 2 / devices 1 / 画面 4)。8%(軽減税率)の商品を売ることになったので、
  1か所に集めた。税率が将来また変わっても、ここだけ直せばよい。

★画面側(tokiwa-ui.html の TAX ブロック)と**対で持っている。片方だけ直さないこと。**
  同じ規則をサーバー(Python)とブラウザ(JavaScript)の両方で使うため。

【日本の消費税(2026年9月時点)】
  標準税率 10% … 宝飾品・時計・メガネ・修理など、店の商品のほとんど
  軽減税率  8% … 飲食料品(酒類・外食を除く)と週2回以上発行の新聞のみ
                  ※宝飾品は対象外。店では贈答用の食品などが該当する

【端数の扱い】
  ★**税率ごとに区切って合計してから**消費税額を出す。
  先に全部を合計してから割ると1円ずれることがあり、適格請求書の要件
  (税率ごとの消費税額)も満たせない。
"""

STANDARD_RATE = 10          # 標準税率
REDUCED_RATE = 8            # 軽減税率
VALID_RATES = (STANDARD_RATE, REDUCED_RATE)
DEFAULT_RATE = STANDARD_RATE
REDUCED_MARK = "※"          # レシートで軽減税率対象に付ける印(適格請求書の要件)
REDUCED_NOTE = "※は軽減税率(8%)対象"


def normalize_rate(v):
    """入ってきた値を 10 か 8 に寄せる。分からなければ標準税率(10)。

    画面から "8" のような文字列で来たり、0.08 のような割合で来たりしても
    同じ答えになるようにする(取り違えると税額が10倍/1/10になるため)。
    """
    if v is None or v == "":
        return DEFAULT_RATE
    try:
        n = float(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return DEFAULT_RATE
    if 0 < n < 1:            # 0.08 / 0.1 のような割合表記
        n *= 100
    n = int(round(n))
    return n if n in VALID_RATES else DEFAULT_RATE


def tax_of(total_incl, rate=DEFAULT_RATE):
    """税込金額から内消費税を出す(切り捨て)。

    10% → total * 10 // 110 、 8% → total * 8 // 108。
    """
    r = normalize_rate(rate)
    t = int(total_incl or 0)
    return t * r // (100 + r)


def split_by_rate(lines):
    """明細を税率ごとにまとめる。

    lines は [{"amount": 金額(税込), "tax_rate": 10 or 8}, ...]。
    戻り: {10: {"total": 合計, "tax": 消費税}, 8: {...}} ← 使われている税率だけ
    ★税率ごとに合計してから消費税を出す(端数を税率ごとに処理するため)。
    """
    buckets = {}
    for ln in lines or []:
        r = normalize_rate(ln.get("tax_rate"))
        buckets[r] = buckets.get(r, 0) + int(ln.get("amount") or 0)
    out = {}
    for r in sorted(buckets, reverse=True):      # 10% を先、8% を後に出す
        out[r] = {"total": buckets[r], "tax": tax_of(buckets[r], r)}
    return out


def total_tax(lines):
    """明細全体の消費税額(税率ごとに出してから足す)。"""
    return sum(v["tax"] for v in split_by_rate(lines).values())


def has_reduced(lines):
    """8%の明細が混ざっているか(レシートの出し分けに使う)。"""
    return any(normalize_rate(ln.get("tax_rate")) == REDUCED_RATE for ln in lines or [])
