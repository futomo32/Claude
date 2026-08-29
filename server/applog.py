# -*- coding: utf-8 -*-
"""トキワの動作ログ(1日1ファイル・使い回し)。

作った理由(2026-08-29):
  レシートが出ない時、画面のお知らせが数秒で消えてしまい原因が読めなかった。
  実際の原因は「宝飾ナビの古い印刷ジョブがキューに詰まっていた」で、トキワからは
  送信成功に見えていた。**成功したかどうかと、その時どこへ送ったか**を残しておけば、
  次に同じことが起きた時に自分たちで辿れる。

置き場所:
  logs/エラー_今日.txt   … 当日ぶん。日付が変わったら自動で作り直す
  logs/エラー_前日.txt   … 作り直す時に前日ぶんをここへ退避

  ★1日で使い回す(店の指定)。ただし前日ぶんだけは残す。
  夕方に出たエラーを翌朝見ようとして消えていた、では意味がないため。
  ファイルは2つしか増えないので溜まらない。

方針:
  ・**ログが書けなくても業務は止めない**(例外は握りつぶす)。ログは補助であって本体ではない
  ・個人情報は書かない。顧客名・住所・電話は残さず、伝票番号など辿れる番号だけにする
  ・成功も残す。「送信は成功していた」と分かることが切り分けの決め手になる
"""
import datetime
import os
import threading

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, "logs")
TODAY_FILE = os.path.join(LOG_DIR, "エラー_今日.txt")
PREV_FILE = os.path.join(LOG_DIR, "エラー_前日.txt")
MAX_LINE = 500          # 1行が長すぎるとメモ帳で読めないので切る

_lock = threading.Lock()   # 複数の端末から同時に会計しても行が混ざらないように


def _rotate_if_needed(today):
    """今日のファイルが昨日以前のものなら、前日ぶんへ回して作り直す。"""
    if not os.path.exists(TODAY_FILE):
        return
    try:
        written = datetime.date.fromtimestamp(os.path.getmtime(TODAY_FILE))
    except OSError:
        return
    if written >= today:
        return
    try:
        if os.path.exists(PREV_FILE):
            os.remove(PREV_FILE)
        os.replace(TODAY_FILE, PREV_FILE)
    except OSError:
        pass   # 回せなくても続行する(そのまま追記されるだけ)


def write(category, message):
    """1行記録する。category は [機器] [起動] [エラー] のような短い分類。"""
    now = datetime.datetime.now()
    text = str(message).replace("\n", " ").replace("\r", " ")[:MAX_LINE]
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with _lock:
            _rotate_if_needed(now.date())
            new = not os.path.exists(TODAY_FILE)
            with open(TODAY_FILE, "a", encoding="utf-8") as f:
                if new:
                    # メモ帳で開いた時に文字化けしないよう、作った時だけBOMを付ける
                    f.write("﻿")
                    f.write(f"# トキワ 動作ログ {now:%Y-%m-%d}"
                            "(このファイルは日付が変わると作り直されます。前日ぶんは"
                            " エラー_前日.txt にあります)\n")
                f.write(f"{now:%Y-%m-%d %H:%M:%S}  [{category}] {text}\n")
    except OSError:
        pass   # ★ログが書けないことで会計を止めない


def tail(lines=20):
    """直近の記録を新しい順で返す(設定画面に出す用)。読めなければ空。"""
    try:
        with open(TODAY_FILE, "r", encoding="utf-8") as f:
            rows = [ln.rstrip("\n") for ln in f if ln.strip() and not ln.lstrip("﻿").startswith("#")]
        return list(reversed(rows[-int(lines):]))
    except OSError:
        return []
