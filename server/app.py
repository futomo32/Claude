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
import base64, json, mimetypes, os, re, socket, sqlite3, sys, time, uuid, urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
UI = os.path.join(BASE, "tokiwa-ui.html")
ASSETS = os.path.join(BASE, "assets")
IMAGES = os.path.join(BASE, "data", "real", "images")   # 商品写真(B-7)

_img_index = None  # 大文字小文字違いに対応するための {小文字ファイル名: 実パス} キャッシュ


def reset_img_index():
    """画像索引を無効化(次回リクエストで作り直す)。写真を新規保存した後に呼ぶ。"""
    global _img_index
    _img_index = None


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


def _decode_image_b64(data):
    """dataURL(または素のbase64)をJPEGバイト列に変換(8MB上限)。不正ならValueError。"""
    data = data or ""
    if "," in data and data[:5].lower() == "data:":
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
    except (ValueError, TypeError):
        raise ValueError("画像データが不正です")
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("画像が大きすぎます(8MBまで)")
    return raw


sys.path.insert(0, os.path.dirname(__file__))
import db_query  # noqa: E402


def connect():
    if not os.path.exists(DB):
        raise SystemExit(f"DBがありません: {DB}\n先に `python3 scripts/import_to_sqlite.py` を実行してください。")
    con = sqlite3.connect(DB, timeout=10)
    # 店内共有(複数PC同時アクセス)でも読み書きが衝突しにくいようWALモード
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.create_function("normjp", 1, db_query.normjp)  # 検索の正規化(半角全角・大小文字)をSQLで使えるように
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


def apply_role_filter(blob, role):
    """パート権限には原価情報を送らない(画面で隠すだけでなく"そもそも送らない")。
    products行の[9]=cost_price(下代)と、在庫サマリの下代合計・粗利率を落とす。"""
    if role != "part":
        return blob
    for p in blob.get("products") or []:
        if len(p) > 9:
            p[9] = None
    ss = blob.get("stockStats")
    if isinstance(ss, dict):
        ss.pop("costTotal", None)
        ss.pop("marginRate", None)
    return blob


def render_index(user):
    """UIのHTMLに、DBから組み立てたデータとログインユーザー情報を埋め込んで返す。"""
    con = connect()
    blob = apply_role_filter(db_query.build_blob_light(con), user.get("role"))  # 起動時は軽量データのみ
    sample = db_query.sample_in_stock_key(con)
    con.close()
    html = open(UI, encoding="utf-8").read()
    inject = (
        "window.TOKIWA_DATA=" + json.dumps(blob, ensure_ascii=False, separators=(",", ":")) + ";"
        "window.TOKIWA_API='/api';"
        "window.TOKIWA_SAMPLE_STOCK=" + json.dumps(sample) + ";"
        "window.TOKIWA_USER=" + json.dumps(user, ensure_ascii=False) + ";"
    )
    marker_start = '<script id="tokiwa-data">'
    marker_end = "</script>"
    i = html.index(marker_start) + len(marker_start)
    j = html.index(marker_end, i)
    return (html[:i] + inject + html[j:]).encode("utf-8")


def render_login():
    """ログイン画面(未ログイン時に配信)。ユーザーを選び、パスワードを入力する。
    パスワード未設定のユーザーは、初回に入力したものがそのままパスワードとして設定される。"""
    con = connect()
    users = db_query.list_login_users(con)
    con.close()
    options = "".join(
        f'<option value="{u["id"]}" data-haspw="{1 if u["has_pw"] else 0}">{u["name"]}</option>'
        for u in users)
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>トキワ ログイン</title>
<style>
  body {{ font-family: "Hiragino Sans", "Yu Gothic UI", sans-serif; background: #f4f2ee;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .box {{ background: #fff; border: 1px solid #ddd6cc; border-radius: 12px; padding: 2rem;
          width: min(360px, 90vw); box-shadow: 0 6px 24px rgba(60,50,30,0.08); }}
  h1 {{ font-size: 1.1rem; margin: 0 0 1.2rem; color: #4a4237; text-align: center; }}
  label {{ display: block; font-size: 0.8rem; color: #7a7264; margin: 0.8rem 0 0.25rem; }}
  select, input {{ width: 100%; box-sizing: border-box; font-size: 1rem; padding: 0.55em 0.7em;
                   border: 1px solid #ccc4b8; border-radius: 8px; background: #fff; }}
  button {{ width: 100%; margin-top: 1.2rem; font-size: 1rem; padding: 0.65em; border: 0;
            border-radius: 8px; background: #8a6d3b; color: #fff; cursor: pointer; }}
  button:disabled {{ opacity: 0.6; }}
  .err {{ color: #b3261e; font-size: 0.85rem; margin: 0.8rem 0 0; display: none; }}
  .hint {{ color: #7a7264; font-size: 0.78rem; margin: 0.4rem 0 0; }}
  .logo {{ display: block; margin: 0 auto 0.8rem; max-height: 64px; }}
</style></head><body>
<form class="box" onsubmit="return doLogin(event)">
  <img class="logo" src="/assets/logo.png" alt="" onerror="this.remove()">
  <h1>トキワ にログイン</h1>
  <label>ユーザー</label>
  <select id="uid" onchange="updateHint()">{options}</select>
  <label>パスワード</label>
  <input id="pw" type="password" autocomplete="current-password" required minlength="1" autofocus>
  <p class="hint" id="hint"></p>
  <p class="err" id="err"></p>
  <button id="btn" type="submit">ログイン</button>
</form>
<script>
  function updateHint() {{
    var o = document.getElementById("uid").selectedOptions[0];
    document.getElementById("hint").textContent = (o && o.dataset.haspw === "0")
      ? "このユーザーはパスワード未設定です。ここで決めたパスワード(4文字以上)がそのまま設定されます。" : "";
  }}
  updateHint();
  function doLogin(e) {{
    e.preventDefault();
    var btn = document.getElementById("btn"), err = document.getElementById("err");
    btn.disabled = true; err.style.display = "none";
    fetch("/api/login", {{ method: "POST", headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ user_id: document.getElementById("uid").value,
                              password: document.getElementById("pw").value }}) }})
      .then(function (r) {{ return r.json(); }})
      .then(function (res) {{
        if (res.error) throw new Error(res.error);
        location.reload();
      }})
      .catch(function (ex) {{
        btn.disabled = false;
        err.textContent = ex.message || "ログインに失敗しました";
        err.style.display = "block";
      }});
    return false;
  }}
</script></body></html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # 静かに

    # ── ログインセッション(アクセス制御④) ──
    def _session_token(self):
        """Cookieからセッショントークンを取り出す。"""
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "tokiwa_session":
                return v
        return None

    def _current_user(self):
        """ログイン中のユーザー {id,name,role} を返す(未ログインはNone)。"""
        token = self._session_token()
        if not token:
            return None
        con = connect()
        try:
            return db_query.session_user(con, token)
        finally:
            con.close()

    def _deny(self, msg="この操作を行う権限がありません", code=403):
        return self._send(code, json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        try:
            path = self.path.split("?", 1)[0]  # クエリを除いた経路で判定
            if path == "/api/health":
                return self._send(200, json.dumps({"ok": True}).encode())
            if path.startswith("/assets/"):
                # ロゴはログイン画面でも使うため認証不要(静的ファイルのみ)
                pass
            else:
                user = self._current_user()
                if path == "/":
                    if not user:
                        return self._send(200, render_login(), "text/html; charset=utf-8")
                    return self._send(200, render_index(user), "text/html; charset=utf-8")
                if not user:
                    return self._deny("ログインしてください(ページを再読み込みするとログイン画面が出ます)", 401)
                role = user.get("role")
                if path == "/api/app_users":
                    if role != "admin":
                        return self._deny()
                    con = connect()
                    result = {"users": db_query.list_app_users(con)}
                    con.close()
                    return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
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
                blob = apply_role_filter(db_query.build_blob(con), role)
                con.close()
                return self._send(200, json.dumps(blob, ensure_ascii=False).encode("utf-8"))
            if path in ("/api/customer_detail", "/api/products", "/api/product_categories",
                        "/api/product_suppliers", "/api/product_brands", "/api/supplier_master", "/api/staff",
                        "/api/staff_junk", "/api/masters", "/api/master", "/api/photo_pool",
                        "/api/product", "/api/daily_sales", "/api/slip_lines", "/api/documents",
                        "/api/customer_ranking", "/api/prescription_search", "/api/rank_preview",
                        "/api/rank_rules", "/api/receivables_summary", "/api/stock_stats",
                        "/api/search_options", "/api/detailed_search", "/api/stocktake_summary"):
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
                            con, q1("q"), q1("cat"), q1("state"), q1("supplier"), q1("genre"),
                            q1("sort", "no"), q1("order", "desc"),
                            q1("limit", "50"), q1("offset", "0"))
                    elif path == "/api/product_categories":
                        result = {"categories": db_query.product_categories(con)}
                    elif path == "/api/product_suppliers":
                        result = {"suppliers": db_query.product_suppliers(con)}
                    elif path == "/api/product_brands":
                        result = {"brands": db_query.product_brands(con)}
                    elif path == "/api/supplier_master":
                        result = {"suppliers": db_query.list_supplier_master(con)}
                    elif path == "/api/staff":
                        result = {"staff": db_query.list_staff(con)}
                    elif path == "/api/staff_junk":
                        result = {"junk": db_query.list_junk_staff(con)}
                    elif path == "/api/photo_pool":
                        result = {"pool": db_query.list_photo_pool(con)}
                    elif path == "/api/product":
                        result = db_query.get_product(con, q1("key"))
                    elif path == "/api/customer_ranking":
                        result = {"rows": db_query.customer_ranking(
                            con, q1("from"), q1("to"), q1("kind"), q1("limit", "100"),
                            q1("exclude", "1") != "0")}
                    elif path == "/api/prescription_search":
                        result = {"rows": db_query.prescription_search(
                            con, q1("from"), q1("to"), q1("purpose"), q1("misassign") == "1")}
                    elif path == "/api/rank_preview":
                        result = db_query.compute_rank_updates(
                            con, q1("kind"), q1("from"), q1("to"), q1("bottom") == "1")
                    elif path == "/api/rank_rules":
                        result = {"rules": db_query.get_rank_rules(con)}
                    elif path == "/api/receivables_summary":
                        result = db_query.receivable_summary(con)
                    elif path == "/api/stock_stats":
                        # 在庫サマリの取り直し(会計確定・返品後にタイルを最新化)。パートには原価を送らない
                        ss = db_query.stock_stats(con)
                        if role == "part":
                            ss.pop("costTotal", None)
                            ss.pop("marginRate", None)
                        result = {"stockStats": ss}
                    elif path == "/api/stocktake_summary":
                        result = db_query.stocktake_summary(con)
                    elif path == "/api/search_options":
                        result = db_query.search_options(con)
                    elif path == "/api/detailed_search":
                        # 詳細検索(顧客属性＋購入商品＋処方箋のAND)。全パラメータをそのまま渡す
                        result = db_query.detailed_customer_search(
                            con, {k: v[0] for k, v in qs.items()})
                    elif path == "/api/masters":
                        result = {"masters": db_query.master_types()}
                    elif path == "/api/master":
                        result = db_query.list_master_items(con, q1("type"))
                    elif path == "/api/daily_sales":
                        result = {"lines": db_query.daily_sales(con, q1("date"))}
                    elif path == "/api/documents":
                        result = {"documents": db_query.list_documents(con, q1("limit", "100"))}
                    else:  # /api/slip_lines
                        result = {"lines": db_query.slip_lines(con, q1("from"), q1("to"), q1("staff"))}
                finally:
                    con.close()
                if role == "part":
                    # パートには原価(下代)を送らない(サーバー側で強制。UI非表示は補助)
                    if path == "/api/products":
                        for row in result.get("rows") or []:
                            if len(row) > 9:
                                row[9] = None
                    elif path == "/api/product" and isinstance(result, dict):
                        result.pop("cost_price", None)
                        result.pop("fucho", None)  # 符丁は下代そのものなのでパートには送らない
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

    # パート権限では使えない操作(原価に触れる・商品/マスタを書き換える系)。
    # サーバー側で強制する(UIのボタン非表示は補助にすぎない)。docs/access-control.md 参照。
    PART_DENIED_POSTS = {
        "/api/product", "/api/product_update", "/api/product_delete",
        "/api/product_image", "/api/product_image_clear",
        "/api/photo_pool", "/api/photo_pool_assign", "/api/photo_pool_delete",
        "/api/supplier_genre", "/api/supplier_fucho", "/api/master_item", "/api/rank_apply", "/api/rank_rules",
        "/api/stocktake_scan", "/api/stocktake_reset",
    }
    # 管理者のみの操作(担当者マスタ・ログインユーザー管理)
    ADMIN_ONLY_POSTS = {"/api/staff", "/api/app_user"}

    def do_POST(self):
        try:
            path = self.path.split("?", 1)[0]  # クエリを除いた経路で判定
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            # ── 認証不要: ログイン/ログアウト ──
            if path == "/api/login":
                con = connect()
                try:
                    result = db_query.login_user(con, payload.get("user_id"), payload.get("password"))
                except ValueError as e:
                    return self._send(401, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
                finally:
                    con.close()
                body = json.dumps({"ok": True, "first_time": result["first_time"],
                                   "user": result["user"]}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie",
                                 f"tokiwa_session={result['token']}; Path=/; HttpOnly; SameSite=Lax; Max-Age=5184000")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/logout":
                con = connect()
                db_query.logout_user(con, self._session_token())
                con.close()
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "tokiwa_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # ── ここから先はログイン必須 ──
            user = self._current_user()
            if not user:
                return self._deny("ログインしてください(ページを再読み込みするとログイン画面が出ます)", 401)
            role = user.get("role")
            if role == "part" and path in self.PART_DENIED_POSTS:
                return self._deny("この操作はパート権限では行えません")
            if path in self.ADMIN_ONLY_POSTS and role != "admin":
                return self._deny("この操作は管理者のみ行えます")
            if path == "/api/app_user":
                con = connect()
                result = db_query.save_app_user(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/checkout":
                con = connect()
                result = db_query.checkout(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/void_line":
                con = connect()
                result = db_query.void_sale_line(con, payload.get("line_id"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/void_slip":
                con = connect()
                result = db_query.void_sale_slip(con, payload.get("slip_id"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/rank_apply":
                con = connect()
                result = db_query.apply_rank_updates(con, payload.get("kind") or "",
                                                     payload.get("from") or "", payload.get("to") or "",
                                                     bool(payload.get("include_bottom")))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/cash_movement":
                con = connect()
                result = db_query.add_cash_movement(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/receivable_add":
                con = connect()
                result = db_query.add_receivable(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/receivable_update":
                con = connect()
                result = db_query.update_receivable(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/receivable_delete":
                con = connect()
                result = db_query.delete_receivable(con, payload.get("id"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/rank_rules":
                con = connect()
                result = db_query.set_rank_rules(con, payload.get("rules") or [])
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
            if path == "/api/family_update":
                con = connect()
                result = db_query.update_family(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/family_delete":
                con = connect()
                result = db_query.delete_family(con, payload.get("id"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/stocktake_scan":
                con = connect()
                result = db_query.stocktake_scan(con, payload.get("product_no"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/stocktake_reset":
                con = connect()
                result = db_query.stocktake_reset(con)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/document":
                con = connect()
                result = db_query.save_document(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/supplier_genre":
                con = connect()
                result = db_query.set_supplier_genre(con, payload.get("name"), payload.get("genre"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/supplier_fucho":
                con = connect()
                result = db_query.set_supplier_fucho(con, payload.get("name"), payload.get("head"))
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/consignment_add":
                # 受託品をレジに通すための商品作成(催事)。原価は出さないためパートも可(会計操作の一部)
                con = connect()
                result = db_query.add_consignment(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/staff":
                con = connect()
                result = db_query.save_staff(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/master_item":
                con = connect()
                result = db_query.save_master_item(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/product_image":
                # 商品写真の登録: ブラウザでリサイズ済みのJPEG(dataURL)を受け取り保存する
                pk = str(payload.get("product_key") or "").strip()
                data = payload.get("image") or ""
                if not pk or not data:
                    raise ValueError("商品と画像を指定してください")
                raw = _decode_image_b64(data)
                safe = re.sub(r"[^A-Za-z0-9_-]", "_", pk)
                fname = f"{safe}_{int(time.time())}.jpg"
                os.makedirs(IMAGES, exist_ok=True)
                with open(os.path.join(IMAGES, fname), "wb") as f:
                    f.write(raw)
                reset_img_index()  # 新ファイルを索引に載せ直す
                con = connect()
                result = db_query.set_product_image(con, pk, fname)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/product_image_clear":
                # 商品写真の取り消し(間違って登録した写真を外す)。実ファイルも削除する。
                pk = str(payload.get("product_key") or "").strip()
                if not pk:
                    raise ValueError("商品が指定されていません")
                con = connect()
                result = db_query.clear_product_image(con, pk)
                con.close()
                old_file = result.get("removed_file")
                if old_file:
                    fpath = image_path(old_file)
                    if fpath and os.path.isfile(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                    reset_img_index()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/photo_pool":
                # 写真プールへの一括アップロード: まとめて撮った複数枚を、商品登録前に
                # 先に保存しておく(商品登録・修正の時にここから選んで紐づける)。
                images = payload.get("images") or []
                if not isinstance(images, list) or not images:
                    raise ValueError("画像を指定してください")
                if len(images) > 40:
                    raise ValueError("一度にアップロードできるのは40枚までです")
                os.makedirs(IMAGES, exist_ok=True)
                con = connect()
                added = []
                for data in images:
                    raw = _decode_image_b64(data)
                    fname = f"pool_{uuid.uuid4().hex}.jpg"
                    with open(os.path.join(IMAGES, fname), "wb") as f:
                        f.write(raw)
                    pid = db_query.add_photo_pool_entry(con, fname)
                    added.append({"id": pid, "filename": fname})
                con.close()
                reset_img_index()
                return self._send(200, json.dumps({"added": added}, ensure_ascii=False).encode("utf-8"))
            if path == "/api/photo_pool_assign":
                # プールの1枚を商品に割り当て(image_fileに設定してプールから外す)
                pool_id = payload.get("pool_id")
                pk = str(payload.get("product_key") or "").strip()
                if not pool_id or not pk:
                    raise ValueError("写真と商品を指定してください")
                con = connect()
                result = db_query.assign_photo_pool(con, pool_id, pk)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/photo_pool_delete":
                # プールから1枚を除外(使わない写真の整理。実ファイルも削除)
                pool_id = payload.get("pool_id")
                if not pool_id:
                    raise ValueError("写真を指定してください")
                con = connect()
                fname = db_query.delete_photo_pool_row(con, pool_id)
                con.close()
                fpath = image_path(fname)
                if fpath and os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
                reset_img_index()
                return self._send(200, json.dumps({"deleted": pool_id}, ensure_ascii=False).encode("utf-8"))
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
            if path == "/api/product_update":
                con = connect()
                result = db_query.update_product(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/product_delete":
                # 商品の削除(誤登録の訂正。B-7)。販売履歴があれば db_query 側で拒否される。
                pk = str(payload.get("product_key") or "").strip()
                if not pk:
                    raise ValueError("商品が指定されていません")
                con = connect()
                result = db_query.delete_product(con, pk)
                con.close()
                image_file = result.get("image_file")
                if image_file:
                    fpath = image_path(image_file)
                    if fpath and os.path.isfile(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                    reset_img_index()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/repair":
                con = connect()
                result = db_query.add_repair(con, payload)
                con.close()
                return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if path == "/api/repair_photo":
                # 修理お預かり品の写真登録(ブラウザでリサイズ済みJPEGのdataURLを複数受け取り保存)。B-6
                rid = payload.get("repair_id")
                images = payload.get("images") or []
                if not rid or not isinstance(images, list) or not images:
                    raise ValueError("修理伝票と画像を指定してください")
                if len(images) > 20:
                    raise ValueError("一度にアップロードできるのは20枚までです")
                os.makedirs(IMAGES, exist_ok=True)
                saved = []
                for data in images:
                    raw = _decode_image_b64(data)
                    fname = f"repair_{int(rid)}_{uuid.uuid4().hex}.jpg"
                    with open(os.path.join(IMAGES, fname), "wb") as f:
                        f.write(raw)
                    saved.append(fname)
                reset_img_index()
                con = connect()
                result = db_query.add_repair_photos(con, rid, saved)
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
