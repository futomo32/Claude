#!/usr/bin/env python3
"""トキワ ローカルAPIサーバー(Python標準ライブラリのみ・追加インストール不要)。

  python3 server/app.py         # http://localhost:8760 で起動
  python3 server/app.py 9000    # ポート指定

  GET  /                → UIを配信。DBから組み立てたデータを埋め込む
  GET  /api/data        → 画面用データ(JSON)
  POST /api/checkout    → 会計を実DBに書き込む(永続化)
  POST /api/receivable_payment → 売掛入金を記録(残高を減らし入金履歴に1行追加)
  POST /api/family      → 家族を追加(A自由入力 / B登録済み顧客と双方向リンク)
  GET  /api/health      → 稼働確認

正式運用(Windows単機)ではこのサーバーをローカルで起動し、ブラウザで開く構成。
将来デスクトップアプリ(Electron等)に載せ替える場合もAPIはそのまま流用できる。
"""
import json, mimetypes, os, re, socket, sqlite3, sys, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
UI = os.path.join(BASE, "tokiwa-ui.html")
ASSETS = os.path.join(BASE, "assets")
IMAGES = os.path.join(BASE, "data", "real", "images")   # 商品写真(B-7)

_img_index = None  # 大文字小文字違いに対応するための {小文字ファイル名: 実パス} キャッシュ


def image_path(fname):
    """商品写真のパスを返す(無ければNone)。まず完全一致、ダメなら大文字小文字を無視して照合。"""
    global _img_index
    fname = os.path.basename(fname or "")
    if not fname:
        return None
    p = os.path.join(IMAGES, fname)
    if os.path.isfile(p):
        return p
    if _img_index is None:
        # サブフォルダも含めて索引化(大文字小文字も無視)。check_images.py と同じ探し方。
        _img_index = {}
        if os.path.isdir(IMAGES):
            for root, _dirs, fnames in os.walk(IMAGES):
                for fn in fnames:
                    _img_index.setdefault(fn.lower(), os.path.join(root, fn))
    return _img_index.get(fname.lower())

sys.path.insert(0, os.path.dirname(__file__))
import db_query  # noqa: E402


def connect():
    if not os.path.exists(DB):
        raise SystemExit(f"DBがありません: {DB}\n先に `python3 scripts/import_to_sqlite.py` を実行してください。")
    con = sqlite3.connect(DB, timeout=10)
    # 店内共有(複数PC同時アクセス)でも読み書きが衝突しにくいようWALモード
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    db_query.ensure_schema(con)  # pull後にmigrate忘れでも動くよう不足列を自動補完
    return con


def lan_ip():
    """このPCの店内LAN上のIPアドレスを推測する(外部送信はしない)。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.255.255", 1))  # 実際には送信されない(UDPのconnectは経路決定のみ)
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:  # noqa: BLE001
            return None


def render_index(remote=False):
    """UIのHTMLに、DBから組み立てたデータとAPI有効フラグを埋め込んで返す。
    remote=True(他PCからのアクセス)ではレジ機能をUI側で無効化するフラグを埋め込む。"""
    con = connect()
    blob = db_query.build_blob_light(con)  # 起動時は軽量データのみ(明細は遅延取得)
    sample = db_query.sample_in_stock_key(con)
    con.close()
    html = open(UI, encoding="utf-8").read()
    inject = (
        "window.TOKIWA_DATA=" + json.dumps(blob, ensure_ascii=False, separators=(",", ":")) + ";"
        "window.TOKIWA_API='/api';"
        "window.TOKIWA_SAMPLE_STOCK=" + json.dumps(sample) + ";"
        "window.TOKIWA_REMOTE=" + ("true" if remote else "false") + ";"
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

    def _is_remote(self):
        """本番機(サーバーを動かしているPC)以外からのアクセスか。
        テスト用に ?remote=1 でも再現できる(UI表示の切替のみで安全)。"""
        if "remote=1" in self.path:
            return True
        return self.client_address[0] not in ("127.0.0.1", "::1", "localhost")

    def do_GET(self):
        try:
            path = self.path.split("?", 1)[0]  # クエリを除いた経路で判定
            if path == "/":
                return self._send(200, render_index(remote=self._is_remote()), "text/html; charset=utf-8")
            if path == "/api/health":
                return self._send(200, json.dumps({"ok": True}).encode())
            if path.startswith("/assets/"):
                # ロゴ等の静的ファイル配信(帳票ヘッダ表示用)。フォルダ外は不可
                fname = os.path.basename(path)
                fpath = os.path.join(ASSETS, fname)
                if fname != path[len("/assets/"):] or not os.path.isfile(fpath):
                    return self._send(404, json.dumps({"error": "not found"}).encode())
                ctype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
                with open(fpath, "rb") as f:
                    return self._send(200, f.read(), ctype)
            if path == "/product_image":
                # 商品写真の配信(data/real/images/ 内のみ。ファイル名のみ受け付けフォルダ外は不可)
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                fpath = image_path((qs.get("file") or [""])[0])
                if not fpath or not os.path.isfile(fpath):
                    return self._send(404, json.dumps({"error": "not found"}).encode())
                ctype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
                with open(fpath, "rb") as f:
                    return self._send(200, f.read(), ctype)
            if path == "/api/data":
                con = connect()
                blob = db_query.build_blob(con)
                con.close()
                return self._send(200, json.dumps(blob, ensure_ascii=False).encode("utf-8"))
            if path in ("/api/customer_detail", "/api/products", "/api/product_categories",
                        "/api/product_suppliers", "/api/daily_sales", "/api/slip_lines",
                        "/api/documents"):
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")

                def q1(name, default=""):
                    v = qs.get(name)
                    return v[0] if v else default

                con = connect()
                try:
                    if path == "/api/customer_detail":
                        result = db_query.customer_detail(con, q1("id"))
                    elif path == "/api/products":
                        result = db_query.search_products(
                            con, q1("q"), q1("cat"), q1("state"), q1("supplier"),
                            q1("limit", "50"), q1("offset", "0"))
                    elif path == "/api/product_categories":
                        result = {"categories": db_query.product_categories(con)}
                    elif path == "/api/product_suppliers":
                        result = {"suppliers": db_query.product_suppliers(con)}
                    elif path == "/api/daily_sales":
                        result = {"lines": db_query.daily_sales(con, q1("date"))}
                    elif path == "/api/documents":
                        result = {"documents": db_query.list_documents(con, q1("limit", "100"))}
                    else:  # /api/slip_lines
                        result = {"lines": db_query.slip_lines(con, q1("from"), q1("to"), q1("staff"))}
                finally:
                    con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/postal":
                # 郵便番号→住所検索(zipcloudへの中継)。オフライン時はエラーを返すだけ
                zipc = re.sub(r"[^0-9]", "", self.path.split("zip=")[-1])
                if len(zipc) != 7:
                    return self._send(400, json.dumps({"error": "郵便番号は7桁で入力してください"}, ensure_ascii=False).encode("utf-8"))
                try:
                    with urllib.request.urlopen(
                            "https://zipcloud.ibsnet.co.jp/api/search?zipcode=" + zipc, timeout=5) as r:
                        data = json.load(r)
                    res = (data.get("results") or [None])[0]
                    if not res:
                        return self._send(404, json.dumps({"error": "該当する住所が見つかりません"}, ensure_ascii=False).encode("utf-8"))
                    addr = (res.get("address1") or "") + (res.get("address2") or "") + (res.get("address3") or "")
                    return self._send(200, json.dumps({"address": addr}, ensure_ascii=False).encode("utf-8"))
                except Exception:  # noqa: BLE001
                    return self._send(502, json.dumps({"error": "住所検索に接続できません(オフライン?)。手入力してください"}, ensure_ascii=False).encode("utf-8"))
            self._send(404, json.dumps({"error": "not found"}).encode())
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        try:
            path = self.path.split("?", 1)[0]  # クエリを除いた経路で判定
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/checkout":
                if self._is_remote():
                    # レジ(会計)は機器のある本番機のみ。他PCからは閲覧・登録のみ
                    return self._send(403, json.dumps(
                        {"error": "レジ(会計)は本体レジPCでのみ操作できます"}, ensure_ascii=False).encode("utf-8"))
                con = connect()
                result = db_query.checkout(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/customer":
                con = connect()
                result = db_query.upsert_customer(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/family":
                con = connect()
                result = db_query.add_family(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/document":
                con = connect()
                result = db_query.save_document(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/prescription":
                con = connect()
                result = db_query.add_prescription(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/product":
                con = connect()
                result = db_query.add_product(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/repair":
                con = connect()
                result = db_query.add_repair(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/repair_status":
                con = connect()
                result = db_query.update_repair_status(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/receivable_payment":
                con = connect()
                result = db_query.add_receivable_payment(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            self._send(404, json.dumps({"error": "not found"}).encode())
        except ValueError as e:
            self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))


def main():
    # 引数: 数字=ポート / "lan"=店内共有モード(他PCからアクセス可)。順不同
    port = 8760
    lan = False
    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)
        elif a.lower() in ("lan", "share", "kyoyu"):
            lan = True
    host = "0.0.0.0" if lan else "127.0.0.1"
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"トキワ起動: http://localhost:{port}/")
    if lan:
        ip = lan_ip()
        print("【店内共有モード】他のPCからは下のURLで開けます:")
        print(f"  http://{ip or 'このPCのIPアドレス'}:{port}/")
        print("  ※他PCではレジ(会計)は使えません(閲覧・顧客登録・商品登録のみ)")
        print("  ※初回はWindowsファイアウォールの許可画面が出たら「アクセスを許可」してください")
    else:
        print("  → このPC専用です。他のPCから使う場合は「店内共有で起動.bat」を使ってください。")
    print("  → 停止は Ctrl+C。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました")


if __name__ == "__main__":
    main()
