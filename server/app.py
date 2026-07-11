#!/usr/bin/env python3
"""トキワ ローカルAPIサーバー(Python標準ライブラリのみ・追加インストール不要)。

  python3 server/app.py         # http://localhost:8760 で起動
  python3 server/app.py 9000    # ポート指定

  GET  /                → UIを配信。DBから組み立てたデータを埋め込む
  GET  /api/data        → 画面用データ(JSON)
  POST /api/checkout    → 会計を実DBに書き込む(永続化)
  GET  /api/health      → 稼働確認

正式運用(Windows単機)ではこのサーバーをローカルで起動し、ブラウザで開く構成。
将来デスクトップアプリ(Electron等)に載せ替える場合もAPIはそのまま流用できる。
"""
import json, os, sqlite3, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
UI = os.path.join(BASE, "tokiwa-ui.html")

sys.path.insert(0, os.path.dirname(__file__))
import db_query  # noqa: E402


def connect():
    if not os.path.exists(DB):
        raise SystemExit(f"DBがありません: {DB}\n先に `python3 scripts/import_to_sqlite.py` を実行してください。")
    return sqlite3.connect(DB)


def render_index():
    """UIのHTMLに、DBから組み立てたデータとAPI有効フラグを埋め込んで返す。"""
    con = connect()
    blob = db_query.build_blob(con)
    sample = db_query.sample_in_stock_key(con)
    con.close()
    html = open(UI, encoding="utf-8").read()
    inject = (
        "window.TOKIWA_DATA=" + json.dumps(blob, ensure_ascii=False, separators=(",", ":")) + ";"
        "window.TOKIWA_API='/api';"
        "window.TOKIWA_SAMPLE_STOCK=" + json.dumps(sample) + ";"
    )
    marker_start = '<script id="tokiwa-data">'
    marker_end = "</script>"
    i = html.index(marker_start) + len(marker_start)
    j = html.index(marker_end, i)
    return (html[:i] + inject + html[j:]).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # 静かに

    def do_GET(self):
        try:
            if self.path == "/" or self.path.startswith("/?"):
                return self._send(200, render_index(), "text/html; charset=utf-8")
            if self.path == "/api/health":
                return self._send(200, json.dumps({"ok": True}).encode())
            if self.path == "/api/data":
                con = connect()
                blob = db_query.build_blob(con)
                con.close()
                return self._send(200, json.dumps(blob, ensure_ascii=False).encode("utf-8"))
            self._send(404, json.dumps({"error": "not found"}).encode())
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        try:
            if self.path == "/api/checkout":
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                con = connect()
                result = db_query.checkout(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            self._send(404, json.dumps({"error": "not found"}).encode())
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8760
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"トキワ起動: http://localhost:{port}/  (Ctrl+Cで停止)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました")


if __name__ == "__main__":
    main()
