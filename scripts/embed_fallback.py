#!/usr/bin/env python3
"""tokiwa-ui.html の埋め込みフォールバックデータを軽量化する。

サーバーが注入するのと同じ db_query.build_blob(サンプルDB) を
<script id="tokiwa-data"> に埋め込む。これにより:
  - 本番運用(サーバー経由)は無変化(サーバーが実データで上書きするため)
  - Python無しのダブルクリック・プレビューは、サーバーと同一構造の
    サンプルデータ(100件+検証ペルソナ)で描画される(旧: demo 5,204件フル)

前提: 先に `python scripts/make_sample_data.py` で db/tokiwa.db を用意。
再実行しても安全(埋め込み部分だけを差し替える)。
"""
import json
import os
import re
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(BASE, "server"))
import db_query  # noqa: E402

DB = os.path.join(BASE, "db", "tokiwa.db")
HTML = os.path.join(BASE, "tokiwa-ui.html")


def main():
    if not os.path.exists(DB):
        raise SystemExit("db/tokiwa.db がありません。先に python scripts/make_sample_data.py を実行してください。")
    con = sqlite3.connect(DB)
    blob = db_query.build_blob(con)
    con.close()

    j = json.dumps(blob, ensure_ascii=False, separators=(",", ":"))
    html = open(HTML, encoding="utf-8").read()
    before = len(html)
    new = re.sub(
        r'<script id="tokiwa-data">.*?</script>',
        lambda m: '<script id="tokiwa-data">window.TOKIWA_DATA=' + j + ";</script>",
        html,
        flags=re.S,
    )
    if new == html and "window.TOKIWA_DATA=" not in html:
        raise SystemExit("マーカー <script id=\"tokiwa-data\"> が見つかりませんでした。")
    open(HTML, "w", encoding="utf-8").write(new)
    after = len(new)
    print(f"埋め込みデータを更新しました: 顧客{len(blob.get('customers', []))}件")
    print(f"  tokiwa-ui.html: {before/1024:.0f}KB → {after/1024:.0f}KB")


if __name__ == "__main__":
    main()
