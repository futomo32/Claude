# -*- coding: utf-8 -*-
"""診断スクリプト共通の「個人情報を画面に出さない」ルール。

CLAUDE.md「診断・分析スクリプトは個人情報(顧客名等)を画面出力しない設計にする」を
1か所で守るためのモジュール。判定を各スクリプトに書き写すと直し漏れが出るので、
★伏せ字のルールを増やす時は必ずこのファイルだけを直すこと。

経緯(2026-08-03): find_column.py が顧客名・住所を画面に出してしまった。
宝飾ナビの生CSVは列名がローマ字(strkoname=顧客名, strkojyu1=住所)なのに、
日本語の列名だけで判定していたのが原因。ローマ字の列名も見るようにした。
"""
import re

# 値を伏せる列名。列名にこの語が含まれたら中身を出さない。
#   ko=顧客 / hon=本人 / tan=担当者 の接頭辞ごと拾う。
#   ※商品名 strsyname・タグ品名 strtaghinname を巻き込まないよう、語を絞って指定する。
SECRET_COL = re.compile(
    # 日本語の列名(xlsx側)
    r"(氏名|名前|顧客名|担当者名|カナ|かな|フリガナ|ふりがな|住所|番地|建物|電話|携帯|"
    r"郵便|〒|生年月日|誕生|メール|勤務先|世帯|続柄|性別"
    # 宝飾ナビのローマ字列名(生CSV側)
    r"|koname|kokname|kokana|kojyu|kopos|kotel|honname|hontel|tanname|tanmei"
    r"|birthday|jusho|address|zipcode|sexkbn|zokukbn"
    # 共通
    r"|TEL|ﾃﾚ|mail)", re.IGNORECASE)

# 念のための二重の網: 列名で拾えなくても、値が電話番号・郵便番号に見えたら伏せる
SECRET_VALUE = re.compile(r"^(0\d{1,4}-\d{1,4}-\d{3,4}|0\d{9,10}|\d{3}-\d{4})$")

MASKED = "(伏せ字: 個人情報らしいため表示しません)"


def is_secret(col, value=""):
    """この列名／値は伏せるべきか。"""
    return bool(SECRET_COL.search(str(col or "")) or SECRET_VALUE.match(str(value or "").strip()))


def mask(col, value, max_len=80):
    """列の値を表示用の文字列にする。伏せるべきなら伏せ字を返す。空なら None。"""
    s = "" if value is None else str(value).strip()
    if not s:
        return None
    if is_secret(col, s):
        return MASKED
    return s if len(s) <= max_len else s[:max_len] + "…"
