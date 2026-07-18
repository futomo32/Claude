# -*- coding: utf-8 -*-
"""ブラウザ初期表示データ(埋め込みblob)の大きさ診断(読み取り専用・個人情報は出さない)。

トキワは現状、起動時に「全画面ぶんのデータ」を1つのJSONにまとめてブラウザへ
一括送信する作り(server/db_query.build_blob)。サンプル100件では軽いが、実データ
(顧客2.5万・商品21万・売上20万)だと初期読み込みが重くなる恐れがある。

このツールはサーバーもブラウザも起動せず、blobを組み立ててJSONバイト数だけを測る。
どのセクションが重いか、全体で何MBかを把握し、対策(サーバー側検索・遅延読込)が
必要かどうかを早期に判断するためのもの。

  python3 scripts/check_blob_size.py

出力はサイズ・件数のみ(顧客名などの中身は一切出さない)。
"""
import json
import os
import sys
import time

BASE = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(BASE, "server"))
DB = os.path.join(BASE, "db", "tokiwa.db")


def mb(n):
    return f"{n / 1024 / 1024:.1f} MB"


def count_of(v):
    """トップレベル値の“件数”をそれらしく数える(配列は要素数、dictはキー数)。"""
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        return len(v)
    return 1


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        print("  先に実データを取り込んでから実行してください(scripts/import_csv.py)。")
        sys.exit(1)

    import sqlite3
    import db_query  # server/db_query.py

    con = sqlite3.connect(DB)
    t0 = time.time()
    blob = db_query.build_blob(con)
    build_sec = time.time() - t0
    con.close()

    # サーバーと同じ圧縮設定(空白なし)でJSON化して実バイト数を測る
    compact = dict(separators=(",", ":"), ensure_ascii=False)
    whole = json.dumps(blob, **compact).encode("utf-8")
    total = len(whole)

    print("■ 初期表示blobの大きさ診断")
    print(f"   組み立て時間: {build_sec:.2f} 秒")
    print(f"   JSON全体サイズ: {mb(total)}  ({total:,} バイト)")
    print()
    print("   セクション別(大きい順):")
    rows = []
    for key, val in blob.items():
        b = len(json.dumps(val, **compact).encode("utf-8"))
        rows.append((b, key, count_of(val)))
    rows.sort(reverse=True)
    for b, key, n in rows:
        pct = b * 100 / max(total, 1)
        print(f"     {key:<14} {mb(b):>10}  ({pct:4.1f}%)  件数 {n:,}")
    print()

    # ざっくりの目安(体感・端末性能で前後する)
    print("== 目安 ==")
    if total < 5 * 1024 * 1024:
        print("  ~5MB未満: 現行の一括送信でおおむね問題なし。")
    elif total < 20 * 1024 * 1024:
        print("  5〜20MB: 起動時に一瞬もたつく可能性。本番機で体感を確認推奨。")
    else:
        print("  20MB超: 初期読み込み・ブラウザメモリが重い恐れ大。")
        print("  → 重いセクション(通常は products / sales)を、起動時一括ではなく")
        print("     サーバー側の検索API・ページング・遅延読込に切り替える設計変更を検討。")
    print()
    print("  ※これは転送前の生JSONサイズ。実際の初期表示はこれをブラウザが")
    print("    パース&描画するため、体感はさらに端末性能に依存する。")
    print("    本番機で `トキワ起動.bat` → ブラウザで開き、実際の待ち時間も確認のこと。")


if __name__ == "__main__":
    main()
