# -*- coding: utf-8 -*-
"""実データの置き場所を決める共通部品(2026-09-01 追加)。

data/real/ の中は次の形に揃えている。

    data/real/
      csv/                … 宝飾ナビの生ダンプ(114テーブル)。本番の取込元
      xlsx/               … 11台帳。答え合わせ用(取込には使わない)
      images/             … 商品写真
      削除商品番号.txt     … 在庫から消す商品番号

★ただし、xlsx を移し忘れて data/real/ 直下に置いたままでも動くようにしてある。
本番前日にフォルダの入れ違いで手が止まるのが一番まずいため、
「新しい置き場を先に見て、無ければ元の場所も見る」という順番にした。
CSV側の診断(diag_real_csv.py など)が前からこの作り方なので、それに揃えている。
"""
import glob
import os


def find_dir(base, pattern, sub):
    """<base>/<sub> に該当ファイルがあればそこを、無ければ <base> 直下を返す。

    どちらにも無いときは <base>/<sub> を返す(「ここに置いてください」と案内するため)。
    """
    nested = os.path.join(base, sub)
    if glob.glob(os.path.join(nested, pattern)):
        return nested
    if glob.glob(os.path.join(base, pattern)):
        return base
    return nested


def xlsx_dir(base):
    """11台帳(xlsx)の置き場。<base>/xlsx を優先する。"""
    return find_dir(base, "*.xlsx", "xlsx")


def csv_dir(base):
    """生ダンプ(csv)の置き場。<base>/csv を優先する。"""
    return find_dir(base, "*.csv", "csv")
