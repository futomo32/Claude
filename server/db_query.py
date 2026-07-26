"""tokiwa.db から画面用データ(TOKIWA_DATA と同一形状)を組み立て、会計を書き込む。

UIの描画コードを変えずに済むよう、埋め込み版と同じ配列の並びで返す。
"""
import hashlib, json, re, secrets, sqlite3, datetime, unicodedata

GLASS_PAT = re.compile(r"メガネ|眼鏡|レンズ|フレーム|ﾒｶﾞﾈ|ﾚﾝｽﾞ|ﾌﾚｰﾑ")


def normjp(s):
    """検索照合用の正規化(1か所に集約)。全角/半角・半角カナ/全角カナ・大文字/小文字の
    違いを吸収する。NFKC(全角英数→半角・半角カナ→全角カナ等)＋casefold(大小文字)。
    ここを直せば、これを使う全項目の照合ルールが一斉に変わる。SQLiteにも関数登録して使う。"""
    if s is None:
        return None
    return unicodedata.normalize("NFKC", str(s)).casefold()


def norm_code(s):
    """バーコード/商品番号の照合用に幅を正規化する。スキャナやレジの入力欄が全角(かな)
    モードだと数字が全角(２０５…)で入るため、NFKC で全角英数・全角ハイフン等を半角へ揃える。
    商品番号は英字(R-5000 等)の大小を区別する必要があるので casefold はしない(幅だけ揃える)。"""
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s)).strip()
FRAME_PAT = re.compile(r"フレーム|ﾌﾚｰﾑ|frame", re.I)
LENS_PAT = re.compile(r"レンズ|ﾚﾝｽﾞ|lens|非球面|累進", re.I)


def _rx_misassign(stored_flag, lens_name, frame_name):
    """処方箋の宝飾誤登録フラグを表示用に補正する(②即効の補正)。
    レンズ名/フレーム名に「メガネ・眼鏡・レンズ・フレーム」を含むものは正当なメガネ品なので
    誤登録扱いにしない(取込時の判定漏れ=全角レンズ等による誤検知を、再取込前でも消す)。"""
    if not stored_flag:
        return False
    for nm in (lens_name, frame_name):
        if nm and GLASS_PAT.search(str(nm)):
            return False
    return True

# 旧・宝飾ナビ由来のゴミ担当名(担当者フィールドにランク/DM/ライオンズ等を無理やり
# 詰め込んだ複合タグ)を判定する。例:「Aランク：三輪」「Ｌ○○」「ライオンズ」。
# レジ会計担当のワンタップ表示から外す/一括整理の対象にする。
_JUNK_STAFF_PAT = re.compile(r"ランク|ライオンズ|Ｌｉｏｎｓ|Lions|ＤＭ|[：:]")


def _is_junk_staff_name(name):
    """担当者名が旧タグ(本物の店員でない)っぽいかを判定する。"""
    if not name:
        return False
    return bool(_JUNK_STAFF_PAT.search(str(name)))


def glass_kind(*texts):
    """フレーム/レンズの別を判定(分類名や品名から)"""
    s = " ".join(t for t in texts if t)
    if FRAME_PAT.search(s):
        return "frame"
    if LENS_PAT.search(s):
        return "lens"
    return ""



def ensure_schema(con):
    """後付けした列がDBに無ければ自動で足す(冪等)。pull直後にmigrate_dbを忘れても
    サーバーが動くための保険。列不足でクエリが落ちて『在庫0件』等になるのを防ぐ。"""
    # 仕入先マスタ(分類フラグ付き)。無ければ作る
    con.execute("""CREATE TABLE IF NOT EXISTS supplier_master (
        name  TEXT PRIMARY KEY,   -- 仕入先名(products.supplier と一致)
        genre TEXT,                -- 商品ジャンル: 宝石/メガネ/時計/その他(未設定はNULL)
        fucho_head TEXT            -- 符丁の頭(メーカー符丁カナ)。漢字名でも正しく出すため名前と別管理
    )""")
    # 汎用マスタ(商品分類・保管場所・支払方法など「名前の一覧」型を1テーブルで管理)
    con.execute("""CREATE TABLE IF NOT EXISTS master_items (
        master_type TEXT NOT NULL,   -- category / location / pay_method ...
        name        TEXT NOT NULL,
        PRIMARY KEY (master_type, name)
    )""")
    # 写真プール: まとめて撮影した未割当の商品写真(商品登録前に一括アップロードしておき、
    # 商品登録・修正の時にここから選んで紐づける)。割り当てたら行を消す(ファイルは残す)。
    con.execute("""CREATE TABLE IF NOT EXISTS photo_pool (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        filename    TEXT NOT NULL,
        uploaded_at TEXT
    )""")
    # レジ入出金: 顧客の買い物と無関係な現金の出入り(代引手数料・収入印紙・両替・経費等)。
    # amountは +入金 / -出金。日報のレジ締め金額・入出金合計に反映する。顧客IDは持たない。
    con.execute("""CREATE TABLE IF NOT EXISTS cash_movements (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT,                -- 区分(経費/両替/代引手数料/収入印紙/その他)
        amount      INTEGER NOT NULL,    -- +入金 / -出金
        note        TEXT,
        staff_name  TEXT,
        occurred_at TEXT                 -- 発生日 YYYY-MM-DD
    )""")
    # アプリ設定(キー・バリュー)。顧客ランク基準などをJSONで保存する。
    con.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )""")
    # 棚卸し(実地在庫の照合)。現物を確認した商品を記録し、在庫台帳との差異を出す。
    con.execute("""CREATE TABLE IF NOT EXISTS stocktake_checks (
        product_key TEXT PRIMARY KEY,
        checked_at  TEXT
    )""")
    # ログインユーザー(ロール別アクセス制御④)。schema.sql と同形。無いDBでも動くように。
    con.execute("""CREATE TABLE IF NOT EXISTS app_users (
        user_id      TEXT PRIMARY KEY,
        store_code   TEXT,
        display_name TEXT,
        role         TEXT NOT NULL DEFAULT 'staff',  -- admin=管理者/staff=社員/part=パート
        pass_hash    TEXT,                            -- NULL=未設定(初回ログイン時に本人が設定)
        active       INTEGER NOT NULL DEFAULT 1
    )""")
    # ログインセッション(トークン→ユーザー)。サーバー再起動してもログイン状態が残るようDBに置く。
    con.execute("""CREATE TABLE IF NOT EXISTS app_sessions (
        token      TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        created_at TEXT
    )""")
    # ユーザーが1人もいなければ初期管理者を作る(パスワードは初回ログイン時に設定)
    if not con.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
        con.execute("INSERT INTO app_users(user_id, display_name, role) VALUES ('admin', '管理者', 'admin')")
        con.commit()

    def cols(t):
        try:
            return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        except sqlite3.Error:
            return set()
    adds = [
        ("products", "image_file", "TEXT"),
        ("products", "brand", "TEXT"),
        ("products", "metal", "TEXT"),
        ("sale_lines", "voided", "INTEGER DEFAULT 0"),
        ("sale_lines", "voided_at", "TEXT"),
        ("sales_slips", "voided", "INTEGER DEFAULT 0"),
        ("customers", "district", "TEXT"),
        ("customers", "exclude_stats", "INTEGER DEFAULT 0"),
        ("customers", "tel2", "TEXT"), ("customers", "note", "TEXT"),
        ("customers", "postal", "TEXT"), ("customers", "address2", "TEXT"),
        ("customers", "email", "TEXT"),
        ("customer_families", "linked_customer_id", "TEXT"),
        ("receivable_entries", "method", "TEXT"),  # 売掛入金の支払方法(現金/銀行振込/カード/その他。空=現金扱い)
        ("repairs", "photo_files", "TEXT"),  # 修理お預かり品の写真ファイル名(カンマ区切り。B-6)
        ("products", "fucho", "TEXT"),  # 符丁(下代を隠す店内符牒。仕入先頭文字＋数字部)。パートには送らない
        ("supplier_master", "fucho_head", "TEXT"),  # 仕入先ごとの符丁頭カナ(漢字名対策)
        ("products", "is_consignment", "INTEGER DEFAULT 0"),  # 受託品フラグ(売上になっても残す。後日精算の識別用)
        ("products", "consign_settled", "INTEGER DEFAULT 0"),  # 受託の後日精算(原価入力)が済んだか
        ("prescriptions", "frame_type", "TEXT"),  # フレームの種類(セル/メタル/ツーポ/ナイロール)
        ("products", "ring_fingers", "TEXT"),  # はめる指(複数可。カンマ区切り)
        ("products", "ring_size", "TEXT"),     # リングサイズ(フリー入力。#10.5 や 12号 等)
    ]
    changed = False
    for table, col, decl in adds:
        c = cols(table)
        if c and col not in c:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                changed = True
            except sqlite3.Error:
                pass
    # staff.is_register(レジ会計担当としてワンタップバーに出すか)。デフォルトは
    # 0(非表示)。宝飾ナビ由来の担当者は数百件規模になりがちで、全員表示→不要な
    # ものだけ手動でOFFにする方式だとクリック数が膨大になるため、逆に全員非表示から
    # 必要な人だけマスタ画面でONにする運用にする(実店舗は数人〜十数人のため負担が少ない)。
    scols = cols("staff")
    if scols and "is_register" not in scols:
        try:
            con.execute("ALTER TABLE staff ADD COLUMN is_register INTEGER DEFAULT 0")
            changed = True
        except sqlite3.Error:
            pass
    if changed:
        con.commit()


def stock_stats(con):
    """在庫サマリ(状態=在庫の商品のみ)。上代=list_price(税込)、下代=cost_price(税別)。
    粗利率 = (1 - 下代×(1+消費税率) / 上代) × 100 … 下代を税込換算して上代(税込)と比較。
    ※消費税率は当面10%固定。会計確定・返品でリアルタイムに変わるので、UIからも取り直せる。"""
    con.row_factory = sqlite3.Row
    TAX_RATE = 0.10
    srow = con.execute("""SELECT COUNT(*) c, COALESCE(SUM(list_price),0) lt, COALESCE(SUM(cost_price),0) ct
                          FROM products WHERE state='在庫'""").fetchone()
    s_count, s_list, s_cost = srow["c"], srow["lt"] or 0, srow["ct"] or 0
    s_margin = round((1 - (s_cost * (1 + TAX_RATE)) / s_list) * 100, 1) if s_list else 0
    return {"count": s_count, "listTotal": s_list, "costTotal": s_cost,
            "marginRate": s_margin, "taxRate": TAX_RATE}


def stocktake_scan(con, product_no):
    """棚卸しのスキャン: 商品番号で在庫品を1点、現物確認済みにする(棚卸台帳に記録)。
    ・在庫状態の同番号のうち、まだ未確認の1点を確認済みにする(同番号が複数あれば繰り返しスキャンで順に)。
    ・在庫状態でない番号(売却済み等)は警告を返す。存在しない番号はエラー。
    ・同じ品番の在庫が複数ある場合(移行データに少数あり)は same_no / remaining を返し、
      「同番号がもう何点あるか」を画面に出せるようにする(現物を1点ずつスキャンすれば全部消える)。"""
    con.row_factory = sqlite3.Row
    no = str(product_no or "").strip()
    if not no:
        raise ValueError("商品番号を入力してください")
    where, wargs = _resolve_code_conditions(no)  # バーコードは品番(先頭5桁)等で照合
    rows = con.execute(
        f"SELECT product_key, product_no, name, state, location, list_price "
        f"FROM products WHERE {where}", wargs).fetchall()
    if not rows:
        return {"result": "not_found", "product_no": no, "message": "その商品番号は台帳にありません"}
    instock = [r for r in rows if r["state"] == "在庫"]
    if not instock:
        return {"result": "not_instock", "product_no": no, "name": rows[0]["name"],
                "message": "この番号は在庫状態ではありません(売却済み等)"}
    checked_keys = {r[0] for r in con.execute(
        "SELECT product_key FROM stocktake_checks WHERE product_key IN (%s)" %
        ",".join("?" * len(instock)), [r["product_key"] for r in instock])}
    target = next((r for r in instock if r["product_key"] not in checked_keys), None)
    if not target:
        return {"result": "already", "product_no": no, "name": instock[0]["name"],
                "message": "この番号の在庫は全て確認済みです"}
    con.execute("INSERT OR REPLACE INTO stocktake_checks(product_key, checked_at) VALUES (?, datetime('now','localtime'))",
                (target["product_key"],))
    # 開始日時が未設定なら、最初のスキャンで記録(リセットせず使い始めた場合の保険)
    if not _stocktake_started(con):
        _set_setting(con, "stocktake_started_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    con.commit()
    # 同じ品番の在庫が他にもある場合、残りの未確認点数を返す(現物を1点ずつスキャンすれば消える)
    remaining = sum(1 for r in instock
                    if r["product_key"] != target["product_key"] and r["product_key"] not in checked_keys)
    return {"result": "ok", "product_no": target["product_no"] or no, "name": target["name"],
            "location": target["location"], "product_key": target["product_key"],
            "list_price": target["list_price"], "same_no": len(instock), "remaining": remaining}


def _set_setting(con, key, value):
    con.execute("INSERT INTO app_settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _stocktake_started(con):
    row = con.execute("SELECT value FROM app_settings WHERE key='stocktake_started_at'").fetchone()
    return row[0] if row and row[0] else None


def stocktake_summary(con):
    """棚卸しの進捗と差異。確認済み点数 / 在庫総点数 / 未確認(在庫台帳にあるが現物未確認=紛失疑い)一覧 / 開始日時。"""
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) FROM products WHERE state='在庫'").fetchone()[0]
    checked = con.execute("""SELECT COUNT(*) FROM stocktake_checks s
                             JOIN products p ON p.product_key=s.product_key AND p.state='在庫'""").fetchone()[0]
    unchecked = []
    for r in con.execute("""SELECT product_no, name, location, list_price
                            FROM products p WHERE p.state='在庫'
                              AND p.product_key NOT IN (SELECT product_key FROM stocktake_checks)
                            ORDER BY product_no"""):
        unchecked.append({"product_no": r["product_no"], "name": r["name"],
                          "location": r["location"], "list_price": r["list_price"]})
    # 確認が1件も無ければ「未開始」扱い(開始日時は表示しない)
    started_at = _stocktake_started(con) if checked > 0 else None
    return {"total": total, "checked": checked, "unchecked": unchecked,
            "unchecked_count": len(unchecked), "started_at": started_at}


def stocktake_reset(con):
    """棚卸しの確認記録を全消去(新しい棚卸しを始める)。開始日時も引き直す。"""
    con.execute("DELETE FROM stocktake_checks")
    _set_setting(con, "stocktake_started_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    con.commit()
    return {"ok": True}


def build_blob(con):
    """全画面ぶんのデータを1つのdictにまとめて返す(埋め込み版と同一形状)。"""
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 売上合算(累計・2026年度・最終購入日)を明細から算出
    totals, y2026, last_buy = {}, {}, {}
    for r in cur.execute("""
        SELECT s.customer_id cid, SUM(l.amount) tot,
               SUM(CASE WHEN s.sold_at LIKE '2026%' THEN l.amount ELSE 0 END) y26,
               MAX(s.sold_at) last
        FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
        WHERE s.customer_id IS NOT NULL AND l.amount IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
        GROUP BY s.customer_id"""):
        totals[r["cid"]] = r["tot"] or 0
        y2026[r["cid"]] = r["y26"] or 0
        last_buy[r["cid"]] = r["last"]

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day,
                                   is_test,note,postal,address2,tel2,email,rank,dm_ok,district,exclude_stats
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y2026.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),   # 11=テスト印 12=用途 13=最終購入日
            r["postal"], r["address2"],                    # 14=郵便番号 15=建物名等
            r["tel2"], r["email"],                         # 16=携帯電話(TEL2) 17=eメール
            r["rank"], r["dm_ok"], r["district"], r["exclude_stats"],  # 18=ランク 19=DM 20=地区 21=集計対象外
        ])

    def group(sql, key_idx=0):
        d = {}
        for row in cur.execute(sql):
            vals = list(row)
            d.setdefault(str(vals[key_idx]), []).append(vals[1:])
        return d

    sales = group("""SELECT s.customer_id, s.sold_at, COALESCE(l.free_name, p.name), l.info,
                            l.amount, s.pay_method, s.staff_name, p.product_no
                     FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
                     LEFT JOIN products p ON l.product_key = p.product_key
                     WHERE s.customer_id IS NOT NULL
                           AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
                     ORDER BY s.sold_at DESC""")

    families = group("""SELECT customer_id, name, relation, gender, birthday, linked_customer_id, id
                        FROM customer_families ORDER BY id""")

    urikake = group("""SELECT customer_id, id, product_name, bought_at, down_payment, balance, last_paid_at
                       FROM receivables ORDER BY bought_at DESC, id DESC""")
    urikake_hist = group("""SELECT customer_id, entry_date, entry_type, product_name, amount, paid, method
                            FROM receivable_entries ORDER BY entry_date DESC""")

    point_tx = group("""SELECT customer_id, occurred_at, tx_type, add_points, use_points, balance
                        FROM point_transactions ORDER BY occurred_at DESC""")
    points = {str(r["customer_id"]): r["balance"]
              for r in cur.execute("SELECT customer_id, balance FROM point_balances")}

    approach = group("""SELECT customer_id, approach_date, kind, title, staff_name
                        FROM approach_history ORDER BY approach_date DESC""")

    rx = {}
    for r in cur.execute("SELECT * FROM prescriptions ORDER BY id DESC"):
        name_l, name_f = r["lens_name"], r["frame_name"]
        # 誤登録判定は取込時に商品分類で確定済み(jewelry_misassign)の値のみを使う。
        # 商品名の文字列に対する正規表現の再判定はPT/SV等の短い断片で誤検知するため行わない。
        misassign = bool(r["jewelry_misassign"])
        rx.setdefault(str(r["customer_id"]), []).append({
            "id": r["id"], "rx_no": r["rx_no"], "purpose": r["purpose"],
            "lens_name": name_l, "frame_name": name_f,
            "lens_price": r["lens_price"], "frame_price": r["frame_price"], "total": r["total_sell"],
            "misassign": misassign, "sale_line_id": r["sale_line_id"],
            "sph_r": r["sph_r"], "sph_l": r["sph_l"], "cyl_r": r["cyl_r"], "cyl_l": r["cyl_l"],
            "ax_r": r["ax_r"], "ax_l": r["ax_l"], "pri_r": r["pri_r"], "pri_l": r["pri_l"],
            "base_r": r["base_r"], "base_l": r["base_l"],
            "pri2_r": r["pri2_r"], "pri2_l": r["pri2_l"], "base2_r": r["base2_r"], "base2_l": r["base2_l"],
            "add_r": r["add_r"], "add_l": r["add_l"],
            "pd_far_both": r["pd_far_both"], "pd_far_r": r["pd_far_r"], "pd_far_l": r["pd_far_l"],
            "pd_near_both": r["pd_near_both"], "pd_near_r": r["pd_near_r"], "pd_near_l": r["pd_near_l"],
            "naked_both": r["naked_both"], "naked_r": r["naked_r"], "naked_l": r["naked_l"],
            "corrected_both": r["corrected_both"], "corrected_r": r["corrected_r"], "corrected_l": r["corrected_l"],
            "handler": r["handler"], "rx_date": r["rx_date"],
        })

    # 処方箋に未紐付けの「メガネ関連の購入明細」(処方箋追加時に選べる候補)
    linked = set(r[0] for r in cur.execute(
        "SELECT sale_line_id FROM prescriptions WHERE sale_line_id IS NOT NULL"))
    rx_candidates = {}
    for r in cur.execute("""
        SELECT s.customer_id cid, l.line_id, s.sold_at, l.amount,
               COALESCE(l.free_name, p.name) nm, p.is_glasses g, p.category cat
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0"""):
        nm = r["nm"] or ""
        is_glass = r["g"] == 1 or bool(GLASS_PAT.search(nm))
        if is_glass and r["line_id"] not in linked:
            rx_candidates.setdefault(str(r["cid"]), []).append(
                [r["line_id"], r["sold_at"], nm, r["amount"], glass_kind(r["cat"], nm)])

    products = []
    for r in cur.execute("""SELECT product_no,name,category,list_price,state,location,
                                   center_stone,center_carat,product_key,image_file,cost_price,supplier
                            FROM products ORDER BY product_no"""):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        products.append([r["product_no"], r["name"], r["category"], r["list_price"],
                         r["state"], r["location"], stone or None, r["product_key"], r["image_file"],
                         r["cost_price"], r["supplier"]])

    repairs = []
    for r in cur.execute("""SELECT id,repair_no,customer_id,item_name,issue,estimate,
                                   received_at,promised_at,status,completed_at,staff_name,note,photo_files
                            FROM repairs ORDER BY id DESC"""):
        repairs.append({
            "id": r["id"], "repair_no": r["repair_no"], "customer_id": r["customer_id"],
            "item_name": r["item_name"], "issue": r["issue"], "estimate": r["estimate"],
            "received_at": r["received_at"], "promised_at": r["promised_at"],
            "status": r["status"], "completed_at": r["completed_at"],
            "staff_name": r["staff_name"], "note": r["note"],
            "photos": [x for x in (r["photo_files"] or "").split(",") if x],
        })

    # 在庫サマリ(状態=在庫の商品のみ)。会計確定・返品でリアルタイムに変わるため /api/stock_stats でも取り直せる。
    stock_summary = stock_stats(con)

    # 支払方法の内訳(フラット配列)。日報等で「支払方法別の実額」を正確に集計するために使う
    # (1会計が複数方法に分かれる場合、明細1行ごとの支払方法は代表ラベルに過ぎないため)
    tenders = []
    for r in cur.execute("""SELECT s.sold_at, sp.method, sp.amount, s.customer_id
                            FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
                            WHERE COALESCE(s.voided,0)=0
                            ORDER BY s.sold_at DESC"""):
        tenders.append([r["sold_at"], r["method"], r["amount"], str(r["customer_id"])])

    return dict(customers=customers, sales=sales, families=families, points=points,
                pointTx=point_tx, urikake=urikake, urikakeHist=urikake_hist,
                approach=approach, rx=rx, rxCandidates=rx_candidates, products=products,
                repairs=repairs, tenders=tenders, stockStats=stock_summary)


def build_blob_light(con):
    """起動時にブラウザへ渡す軽量データ。重い明細(売上/処方箋/処方箋候補/ポイント履歴/
    アプローチ/商品)は含めず、顧客一覧と小さな集計だけを返す(全データ一括送信=60MB超を回避)。
    重い明細は必要時に取得する:
      顧客詳細 → /api/customer_detail  / 商品 → /api/products
      日報・期間集計 → /api/daily_sales, /api/slip_lines
    """
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 一覧表示に要る集計値(累計・当年度・最終購入日)は明細から先に算出しておく
    totals, y_cur, last_buy = {}, {}, {}
    cur_year = str(datetime.date.today().year)
    for r in cur.execute("""
        SELECT s.customer_id cid, SUM(l.amount) tot,
               SUM(CASE WHEN s.sold_at LIKE ? THEN l.amount ELSE 0 END) yc,
               MAX(s.sold_at) last
        FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
        WHERE s.customer_id IS NOT NULL AND l.amount IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
        GROUP BY s.customer_id""", (cur_year + "%",)):
        totals[r["cid"]] = r["tot"] or 0
        y_cur[r["cid"]] = r["yc"] or 0
        last_buy[r["cid"]] = r["last"]

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day,
                                   is_test,note,postal,address2,tel2,email,rank,dm_ok,district,exclude_stats
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y_cur.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),
            r["postal"], r["address2"], r["tel2"], r["email"],
            r["rank"], r["dm_ok"], r["district"], r["exclude_stats"],  # 18=ランク 19=DM 20=地区 21=集計対象外
        ])

    def group(sql, key_idx=0):
        d = {}
        for row in cur.execute(sql):
            vals = list(row)
            d.setdefault(str(vals[key_idx]), []).append(vals[1:])
        return d

    # 顧客詳細で使うが小さい(合計0.5MB程度)ものと、日報/売掛集計で全件走査するものは
    # 起動時に持っておく(遅延化しても効果が薄く、集計側の作り直しが増えるため)
    families = group("""SELECT customer_id, name, relation, gender, birthday, linked_customer_id, id
                        FROM customer_families ORDER BY id""")
    urikake = group("""SELECT customer_id, id, product_name, bought_at, down_payment, balance, last_paid_at
                       FROM receivables ORDER BY bought_at DESC, id DESC""")
    urikake_hist = group("""SELECT customer_id, entry_date, entry_type, product_name, amount, paid, method
                            FROM receivable_entries ORDER BY entry_date DESC""")
    points = {str(r["customer_id"]): r["balance"]
              for r in cur.execute("SELECT customer_id, balance FROM point_balances")}

    repairs = []
    for r in cur.execute("""SELECT id,repair_no,customer_id,item_name,issue,estimate,
                                   received_at,promised_at,status,completed_at,staff_name,note,photo_files
                            FROM repairs ORDER BY id DESC"""):
        repairs.append({
            "id": r["id"], "repair_no": r["repair_no"], "customer_id": r["customer_id"],
            "item_name": r["item_name"], "issue": r["issue"], "estimate": r["estimate"],
            "received_at": r["received_at"], "promised_at": r["promised_at"],
            "status": r["status"], "completed_at": r["completed_at"],
            "staff_name": r["staff_name"], "note": r["note"],
            "photos": [x for x in (r["photo_files"] or "").split(",") if x],
        })

    stock_summary = stock_stats(con)

    tenders = []
    for r in cur.execute("""SELECT s.sold_at, sp.method, sp.amount, s.customer_id
                            FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
                            WHERE COALESCE(s.voided,0)=0
                            ORDER BY s.sold_at DESC"""):
        tenders.append([r["sold_at"], r["method"], r["amount"], str(r["customer_id"])])

    # 担当者(有効なもの)。各画面の担当者プルダウンをマスタ連動にするため。
    # staffテーブルが空なら顧客の担当者名から拾ってフォールバック(サンプルDB等)
    staff = [r["name"] for r in cur.execute("SELECT name FROM staff WHERE active=1 ORDER BY name")]
    if not staff:
        staff = [r["staff_name"] for r in cur.execute(
            "SELECT DISTINCT staff_name FROM customers WHERE staff_name IS NOT NULL AND staff_name<>'' ORDER BY staff_name")]
    # レジ会計担当のワンタップバーに出す担当者(is_register=1 の有効な人だけ。デフォルトOFF)。
    # 並び順は担当者番号(staff_code)順。番号の無い人は末尾に名前順で。
    # 誰も設定していない(全部OFF)場合に限り staff 全体にフォールバック(会計不能を防ぐ安全策)。
    register_staff = [r["name"] for r in cur.execute(
        "SELECT name FROM staff WHERE active=1 AND COALESCE(is_register,0)=1 "
        "ORDER BY (staff_code IS NULL OR staff_code=''), CAST(staff_code AS INTEGER), name")]
    if not register_staff:
        register_staff = staff
    # 担当者の「番号」入力(コード検索)用。有効な担当者のcode/nameペア
    staff_codes = [[r["staff_code"], r["name"]] for r in cur.execute(
        "SELECT staff_code, name FROM staff WHERE active=1")]

    return dict(customers=customers, families=families, points=points,
                urikake=urikake, urikakeHist=urikake_hist,
                repairs=repairs, tenders=tenders, stockStats=stock_summary, staff=staff,
                registerStaff=register_staff, staffCodes=staff_codes,
                cashMovements=list_cash_movements(con),
                lite=True)  # lite=True で「明細は遅延取得」とUIに知らせる


def _col(r, key, default=None):
    """sqlite3.Row から列を安全に取り出す(古いDBに新しい列が無い場合は default)。
    ensure_schema で列を足す前のDBや、SELECT に含めていない場合でも落ちないようにする。"""
    try:
        return r[key]
    except (IndexError, KeyError):
        return default


def _rx_row(r):
    """prescriptions の1行を画面用dictに変換(build_blob と customer_detail で共用)。"""
    return {
        "id": r["id"], "rx_no": r["rx_no"], "purpose": r["purpose"],
        "lens_name": r["lens_name"], "frame_name": r["frame_name"],
        "frame_type": _col(r, "frame_type"),  # セル/メタル/ツーポ/ナイロール
        "lens_price": r["lens_price"], "frame_price": r["frame_price"], "total": r["total_sell"],
        "misassign": _rx_misassign(r["jewelry_misassign"], r["lens_name"], r["frame_name"]),
        "sale_line_id": r["sale_line_id"],
        "sph_r": r["sph_r"], "sph_l": r["sph_l"], "cyl_r": r["cyl_r"], "cyl_l": r["cyl_l"],
        "ax_r": r["ax_r"], "ax_l": r["ax_l"], "pri_r": r["pri_r"], "pri_l": r["pri_l"],
        "base_r": r["base_r"], "base_l": r["base_l"],
        "pri2_r": r["pri2_r"], "pri2_l": r["pri2_l"], "base2_r": r["base2_r"], "base2_l": r["base2_l"],
        "add_r": r["add_r"], "add_l": r["add_l"],
        "pd_far_both": r["pd_far_both"], "pd_far_r": r["pd_far_r"], "pd_far_l": r["pd_far_l"],
        "pd_near_both": r["pd_near_both"], "pd_near_r": r["pd_near_r"], "pd_near_l": r["pd_near_l"],
        "naked_both": r["naked_both"], "naked_r": r["naked_r"], "naked_l": r["naked_l"],
        "corrected_both": r["corrected_both"], "corrected_r": r["corrected_r"], "corrected_l": r["corrected_l"],
        "handler": r["handler"], "rx_date": r["rx_date"],
    }


def pay_fallback(pay_method, credit_kind=None):
    """支払方法の表示文字列を作る。移行データは「掛売区分」が空のことが多く、そのまま出すと
    購入履歴の支払が「—」になってしまう。宝飾ナビの運用では
      掛売区分あり→その区分 / クレジット種別あり→クレジット / どちらも空→現金
    なので、この順で埋める(日報の `pay_method or "現金"` と表示を揃える)。"""
    pm = str(pay_method or "").strip()
    ck = str(credit_kind or "").strip()
    if pm and ck and ck not in pm:
        return f"{pm}({ck})"
    if pm:
        return pm
    if ck:
        return f"クレジット({ck})" if ck != "クレジット" else ck
    return "現金"


def slip_pay_texts(con, where_sql="", args=()):
    """伝票ごとの支払表示 {slip_id: "現金 ¥50,000 / クレジット ¥50,000"} を返す。
    現金＋クレジットの併用払いは sale_payments に内訳が入っているので、
    2種類以上あるときだけ金額つきで並べる(1種類なら金額は伝票合計と同じなので方法だけ)。"""
    rows = con.execute(
        "SELECT sp.slip_id, sp.method, sp.amount FROM sale_payments sp "
        "JOIN sales_slips s ON s.slip_id = sp.slip_id " + where_sql +
        " ORDER BY sp.slip_id, sp.id", args).fetchall()
    by_slip = {}
    for r in rows:
        by_slip.setdefault(r["slip_id"], []).append((r["method"] or "現金", int(r["amount"] or 0)))
    out = {}
    for sid, parts in by_slip.items():
        parts = [(m, a) for m, a in parts if a]
        if len(parts) > 1:
            out[sid] = " / ".join(f"{m} ¥{a:,}" for m, a in parts)
        elif parts:
            out[sid] = parts[0][0]
    return out


def customer_detail(con, cid):
    """1顧客ぶんの重い明細(売上/処方箋/処方箋候補/ポイント履歴/アプローチ)を返す。
    顧客詳細を開いた時にだけ呼ぶ(遅延取得)。UIの D.sales[id] 等と同じ形状。"""
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cid = str(cid)

    # 品名: 処方箋(メガネ)が紐づく明細は、処方箋のレンズ名/フレーム名を優先して表示する。
    # (レジで「メガネレンズ」等の仮名で会計→処方箋で正式名に直しても購入一覧に反映される。
    #  移行データのように過去に紐付いた分もこの表示で正しい名前になる)
    sales = [list(r) for r in cur.execute("""
        SELECT s.sold_at,
               COALESCE((SELECT COALESCE(NULLIF(rx.lens_name,''), NULLIF(rx.frame_name,''))
                         FROM prescriptions rx WHERE rx.sale_line_id = l.line_id LIMIT 1),
                        l.free_name, p.name) AS disp_name,
               l.info, l.amount, s.pay_method, s.staff_name, p.product_no, l.line_id, s.slip_id,
               s.credit_kind, p.image_file
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ?
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
        ORDER BY s.sold_at DESC""", (cid,))]

    # 支払表示を埋める(移行データの空欄対策＋現金/クレジット併用の内訳)。
    # 行の並びは [0]買上日 [1]品名 [2]商品情報 [3]金額 [4]支払 [5]担当 [6]商品番号
    #            [7]line_id [8]slip_id [9]credit_kind [10]画像 → [4]を表示用に置き換え、
    # [9]は画像ファイル名に詰め替えてUIへ渡す(UIの列番号を増やさない)。
    pay_texts = slip_pay_texts(con, "WHERE s.customer_id = ?", (cid,))
    for row in sales:
        row[4] = pay_texts.get(row[8]) or pay_fallback(row[4], row[9])
        row[9] = row.pop(10)  # [9]=商品画像(サムネイル用)

    # 取消(返品)済みの明細。監査ログとして「取消済みも表示」トグルON時のみ画面に出す。
    # 形状は sales と同じ並び＋末尾に取消日(voided_at)。
    sales_voided = [list(r) for r in cur.execute("""
        SELECT s.sold_at, COALESCE(l.free_name, p.name) AS disp_name,
               l.info, l.amount, s.pay_method, s.staff_name, p.product_no, l.line_id, s.slip_id,
               l.voided_at, s.credit_kind
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ? AND (COALESCE(l.voided,0)=1 OR COALESCE(s.voided,0)=1)
        ORDER BY s.sold_at DESC""", (cid,))]
    for row in sales_voided:  # 取消済み一覧も支払の表示を揃える([9]=取消日は維持)
        row[4] = pay_texts.get(row[8]) or pay_fallback(row[4], row.pop())

    point_tx = [list(r) for r in cur.execute("""
        SELECT occurred_at, tx_type, add_points, use_points, balance
        FROM point_transactions WHERE customer_id = ? ORDER BY occurred_at DESC""", (cid,))]

    approach = [list(r) for r in cur.execute("""
        SELECT approach_date, kind, title, staff_name
        FROM approach_history WHERE customer_id = ? ORDER BY approach_date DESC""", (cid,))]

    rx = [_rx_row(r) for r in cur.execute(
        "SELECT * FROM prescriptions WHERE customer_id = ? ORDER BY id DESC", (cid,))]

    linked = set(r[0] for r in cur.execute(
        "SELECT sale_line_id FROM prescriptions WHERE customer_id = ? AND sale_line_id IS NOT NULL", (cid,)))
    rx_candidates = []
    for r in cur.execute("""
        SELECT l.line_id, s.sold_at, l.amount,
               COALESCE(l.free_name, p.name) nm, p.is_glasses g, p.category cat
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ?
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0""", (cid,)):
        nm = r["nm"] or ""
        is_glass = r["g"] == 1 or bool(GLASS_PAT.search(nm))
        if is_glass and r["line_id"] not in linked:
            rx_candidates.append([r["line_id"], r["sold_at"], nm, r["amount"], glass_kind(r["cat"], nm)])

    return {"sales": sales, "salesVoided": sales_voided, "rx": rx, "rxCandidates": rx_candidates,
            "pointTx": point_tx, "approach": approach}


# 在庫一覧の並び替えで指定できる列(キー→実カラム。ホワイトリストでSQLインジェクション防止)
PRODUCT_SORT_COLS = {"no": "product_no", "name": "name", "cat": "category",
                     "list": "list_price", "cost": "cost_price", "state": "state",
                     "loc": "location", "supplier": "supplier"}


def _ean13_base(code):
    """スキャン値が EAN-13(13桁の数字・チェックデジット一致)なら、商品識別に使う
    先頭10桁を返す。宝飾ナビのタグは 管理番号の先頭4区画(XXXXX-Y-ZZ-WW=10桁)＋'00'＋
    チェックデジット の EAN-13。末尾区画(VVV)はバーコードに入らないため先頭10桁で照合する。
    手入力の商品番号(R-5000 / 17543-1-01-20-130 等)は EAN-13 でないので None を返す。
    スキャナが全角数字(２０５…)で入力しても照合できるよう先に幅を半角へ正規化する。"""
    s = norm_code(code)
    if len(s) != 13 or not s.isdigit():
        return None
    digs = [int(c) for c in s]
    chk = (10 - sum(d * (3 if i % 2 else 1) for i, d in enumerate(digs[:12])) % 10) % 10
    if chk != digs[12]:
        return None
    return s[:10]


def _resolve_code_conditions(code):
    """スキャン/入力値から products.product_no 照合用の (whereSQL, args) を返す。
    EAN-13 バーコードなら次の3通りに当てる(全角モードで入力されても半角化して照合)。
      ① 先頭5桁 = 品番。実データの商品番号は5桁の品番(例 20556)なので、これが本線。
      ② 先頭10桁で前方一致。商品番号にフル管理番号(20556-1-02-23-130)が入っている場合の保険。
      ③ 13桁そのまま。バーコードの数字を商品番号にしている場合の保険。
    ※バーコードには管理番号の末尾区画(VVV)が入らないため、同じ品番の在庫が複数あると
      バーコードだけでは個体を特定できない(呼び出し側で候補から選ぶ)。"""
    raw = norm_code(code)
    base = _ean13_base(raw)
    if base:
        return ("(product_no = ? OR product_no = ? OR REPLACE(product_no,'-','') LIKE ?)",
                [raw, base[:5], base + "%"])
    return ("product_no = ?", [raw])


def search_products(con, q="", cat="", state="", supplier="", genre="", sort="no", order="desc", limit=50, offset=0):
    """商品検索(在庫一覧・レジの商品ピッカー用)。全商品(21万件)を送らずサーバーで絞り込む。
    戻り値 {rows:[...], total:N}。rows は
      [商品番号,品名,分類,上代,状態,置場,石,商品キー,画像,下代,仕入先]。
    末尾寄りの商品キー(product_key)はレジで在庫引落・購入履歴の紐付けに使う内部キー。
    sort/order で並び替え(サーバー側。ページングと整合させるため)。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    where, args = [], []
    if q:
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        qn = norm_code(q)                       # 全角(かな)入力を半角化した品番/バーコード照合用
        liken = "%" + qn.replace("%", "").replace("_", "") + "%"
        base = _ean13_base(q)  # バーコード(EAN-13)なら品番(先頭5桁)と管理番号(先頭10桁)で照合
        if base:
            where.append("(product_no LIKE ? OR name LIKE ? OR product_no = ? "
                         "OR REPLACE(product_no,'-','') LIKE ?)")
            args += [liken, like, base[:5], base + "%"]
        else:
            where.append("(product_no LIKE ? OR product_no LIKE ? OR name LIKE ?)")
            args += [like, liken, like]
    if cat:
        where.append("category = ?"); args.append(cat)
    if state:
        where.append("state = ?"); args.append(state)
    if supplier:
        where.append("supplier = ?"); args.append(supplier)
    if genre:
        # 仕入先ジャンルで絞り込み(仕入先マスタで該当ジャンルに設定された仕入先の商品のみ)
        where.append("supplier IN (SELECT name FROM supplier_master WHERE genre = ?)")
        args.append(genre)
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    col = PRODUCT_SORT_COLS.get(sort, "product_no")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    order_sql = f" ORDER BY {col} {direction}, product_no"  # col/directionは固定候補のみで安全
    total = con.execute("SELECT COUNT(*) FROM products" + wsql, args).fetchone()[0]
    rows = []
    for r in con.execute(
            "SELECT product_no,name,category,list_price,cost_price,state,location,"
            "center_stone,center_carat,supplier,product_key,image_file,brand,metal "
            "FROM products" + wsql + order_sql + " LIMIT ? OFFSET ?", args + [limit, offset]):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        rows.append([r["product_no"], r["name"], r["category"], r["list_price"],
                     r["state"], r["location"], stone or None, r["product_key"], r["image_file"],
                     r["cost_price"], r["supplier"], r["brand"], r["metal"]])  # [11]=ブランド [12]=地金
    return {"rows": rows, "total": total}


def product_categories(con):
    """商品分類の一覧(在庫一覧の絞り込みプルダウン用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category<>'' ORDER BY category")]


def product_suppliers(con):
    """仕入先の一覧(在庫一覧・レジの商品ピッカーの絞り込みプルダウン用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT supplier FROM products WHERE supplier IS NOT NULL AND supplier<>'' ORDER BY supplier")]


SUPPLIER_GENRES = ("宝石", "メガネ", "時計", "その他")


def sync_supplier_master(con):
    """商品に登場する仕入先名を仕入先マスタに取り込む(未登録のみ・分類はNULL)。"""
    con.execute("""INSERT OR IGNORE INTO supplier_master(name, genre)
                   SELECT DISTINCT supplier, NULL FROM products
                   WHERE supplier IS NOT NULL AND supplier<>''""")
    con.commit()


def list_supplier_master(con):
    """仕入先マスタ一覧(分類割り当て画面用)。名前・ジャンル・商品件数・在庫数を返す。
    在庫数は state='在庫' の商品のみを数える(現在店頭にある枠)。並び替えはUI側で行う。"""
    sync_supplier_master(con)
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("""SELECT m.name, m.genre, m.fucho_head,
                                   (SELECT COUNT(*) FROM products p WHERE p.supplier = m.name) cnt,
                                   (SELECT COUNT(*) FROM products p WHERE p.supplier = m.name AND p.state='在庫') stock
                            FROM supplier_master m ORDER BY m.name"""):
        rows.append({"name": r["name"], "genre": r["genre"], "fucho_head": r["fucho_head"],
                     "count": r["cnt"], "stock": r["stock"]})
    return rows


def product_brands(con):
    """商品に登場するブランド名の一覧(登録・修正フォームの入力候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand<>'' ORDER BY brand")]


def product_metals(con):
    """商品に登場する地金の一覧(重複除去。詳細検索の候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT metal FROM products WHERE metal IS NOT NULL AND metal<>'' ORDER BY metal")]


def product_stones(con):
    """商品に登場する中石(石種)の一覧(重複除去。詳細検索の候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT center_stone FROM products WHERE center_stone IS NOT NULL AND center_stone<>'' ORDER BY center_stone")]


def prescription_purposes(con):
    """処方箋に登場する用途の一覧(重複除去。詳細検索の候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT purpose FROM prescriptions WHERE purpose IS NOT NULL AND purpose<>'' ORDER BY purpose")]


def search_options(con):
    """詳細検索フォームのプルダウン候補をまとめて返す(重複除去済み)。"""
    return {"categories": product_categories(con), "brands": product_brands(con),
            "metals": product_metals(con), "stones": product_stones(con),
            "suppliers": product_suppliers(con), "purposes": prescription_purposes(con)}


def set_supplier_genre(con, name, genre):
    """仕入先のジャンルを設定/変更する。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("仕入先が指定されていません")
    genre = (genre or "").strip() or None
    if genre is not None and genre not in SUPPLIER_GENRES:
        raise ValueError("不正なジャンルです")
    con.execute("""INSERT INTO supplier_master(name, genre) VALUES(?,?)
                   ON CONFLICT(name) DO UPDATE SET genre=excluded.genre""", (name, genre))
    con.commit()
    return {"name": name, "genre": genre}


def supplier_fucho_head(con, name):
    """仕入先の符丁文字(メーカー頭カナ)を返す。未登録は ''。符丁の1文字目に使う。"""
    name = str(name or "").strip()
    if not name:
        return ""
    r = con.execute("SELECT fucho_head FROM supplier_master WHERE name=?", (name,)).fetchone()
    return (r[0] or "") if r else ""


def set_supplier_fucho(con, name, head):
    """仕入先の符丁文字(メーカー頭カナ)を設定/変更する。空で解除。
    濁点付きカナ(半角だと2文字)も許容するため2文字まで受ける。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("仕入先が指定されていません")
    head = str(head or "").strip()[:2] or None
    con.execute("""INSERT INTO supplier_master(name, fucho_head) VALUES(?,?)
                   ON CONFLICT(name) DO UPDATE SET fucho_head=excluded.fucho_head""", (name, head))
    con.commit()
    return {"name": name, "fucho_head": head}


def sale_kind4(is_glasses, category, place):
    """売上を4分類(催事/メガネ/時計/店頭)に振り分ける(B-9)。
    優先順: (1)催事=購入場所が店頭以外 → (2)メガネ=is_glasses → (3)時計=分類に「時計」
    → (4)店頭=残り。店の目視集計に合わせ、催事(店外イベント)を最優先で切り出す。
    ※分類ルールは実データの購入場所コードの実態を見て今後調整可。"""
    pl = str(place or "").strip()
    if pl and pl not in ("店頭", "本店", "01", "0", "店内"):
        return "催事"
    if is_glasses:
        return "メガネ"
    if "時計" in str(category or ""):
        return "時計"
    return "店頭"


def daily_sales(con, date):
    """指定日のレジ売上明細(日報・ホームタイル用)。全売上をブラウザに持たずサーバーで集計。"""
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("""
        SELECT s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.info, l.amount, s.pay_method, s.staff_name,
               p.is_glasses ig, p.category cat, s.place place
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sold_at = ? AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0""", (str(date),)):
        out.append({"cid": r["cid"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "info": r["info"], "amount": r["amount"] or 0,
                    "pay": r["pay_method"] or "現金", "staff": r["staff_name"],
                    "kind4": sale_kind4(r["ig"], r["cat"], r["place"])})
    return out


def slip_lines(con, frm, to, staff=""):
    """期間の売上伝票明細(売上集計・CSV用)。サーバー側で期間・担当者で絞り込む。"""
    con.row_factory = sqlite3.Row
    args = [str(frm), str(to)]
    staffsql = ""
    if staff:
        staffsql = " AND s.staff_name = ?"
        args.append(staff)
    out = []
    for r in con.execute("""
        SELECT s.sold_at, s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.amount, s.pay_method, s.staff_name,
               p.is_glasses ig, p.category cat, s.place place
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sold_at >= ? AND s.sold_at <= ?
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0""" + staffsql + """
        ORDER BY s.sold_at""", args):
        out.append({"date": r["sold_at"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "amount": r["amount"] or 0, "pay": r["pay_method"] or "", "staff": r["staff_name"],
                    "kind4": sale_kind4(r["ig"], r["cat"], r["place"])})
    return out


def customer_ranking(con, frm="", to="", kind="", limit=100, exclude=True):
    """購入額の顧客ランキング(B-4)。期間・対象カテゴリで絞り込み、合計購入額の多い順に返す。
      frm/to  … 販売日の期間(空なら全期間=累計)
      kind    … "" 全て / "メガネ"=メガネ商品のみ / "宝飾"=メガネ以外
      exclude … True で「集計対象外(ななし等)」と検証ペルソナを除外(既定)
    戻り値: [{customer_id,name,rank,total,count}] を total 降順で。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 100
    where = ["s.customer_id IS NOT NULL", "l.amount IS NOT NULL",
             "COALESCE(l.voided,0)=0", "COALESCE(s.voided,0)=0"]
    args = []
    if frm:
        where.append("s.sold_at >= ?"); args.append(str(frm))
    if to:
        where.append("s.sold_at <= ?"); args.append(str(to))
    if kind == "メガネ":
        where.append("p.is_glasses = 1")
    elif kind == "宝飾":
        where.append("COALESCE(p.is_glasses,0) = 0")
    if exclude:
        where.append("COALESCE(c.exclude_stats,0) = 0 AND COALESCE(c.is_test,0) = 0")
    sql = ("""SELECT s.customer_id cid, c.name cname, c.rank rank,
                     SUM(l.amount) total, COUNT(*) cnt
              FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
              LEFT JOIN products p ON l.product_key = p.product_key
              LEFT JOIN customers c ON c.customer_id = s.customer_id
              WHERE """ + " AND ".join(where) +
           " GROUP BY s.customer_id ORDER BY total DESC LIMIT ?")
    out = []
    for r in con.execute(sql, args + [limit]):
        out.append({"customer_id": r["cid"], "name": r["cname"] or r["cid"],
                    "rank": r["rank"], "total": r["total"] or 0, "count": r["cnt"]})
    return out


def prescription_search(con, frm="", to="", purpose="", misassign_only=False):
    """メガネ処方箋の横断検索(B-4)。顧客をまたいで処方箋を期間・用途で絞り込む。
    行から元の顧客詳細へ遷移できるよう customer_id と顧客名も返す。"""
    con.row_factory = sqlite3.Row
    where, args = ["1=1"], []
    if frm:
        where.append("rx.rx_date >= ?"); args.append(str(frm))
    if to:
        where.append("rx.rx_date <= ?"); args.append(str(to))
    if purpose:
        where.append("rx.purpose = ?"); args.append(purpose)
    if misassign_only:
        where.append("rx.jewelry_misassign = 1")
    out = []
    for r in con.execute("""
        SELECT rx.id, rx.customer_id cid, c.name cname, rx.rx_no, rx.rx_date, rx.purpose,
               rx.lens_name, rx.frame_name, rx.total_sell, rx.handler, rx.jewelry_misassign mis
        FROM prescriptions rx LEFT JOIN customers c ON c.customer_id = rx.customer_id
        WHERE """ + " AND ".join(where) + " ORDER BY rx.rx_date DESC, rx.id DESC LIMIT 500", args):
        mis = _rx_misassign(r["mis"], r["lens_name"], r["frame_name"])
        if misassign_only and not mis:
            continue  # 名称がメガネ品(誤検知)の行は「誤登録のみ」から除外
        out.append({"id": r["id"], "customer_id": r["cid"], "customer": r["cname"] or r["cid"],
                    "rx_no": r["rx_no"], "rx_date": r["rx_date"], "purpose": r["purpose"],
                    "lens_name": r["lens_name"], "frame_name": r["frame_name"],
                    "total": r["total_sell"], "handler": r["handler"], "misassign": mis})
    return out


def detailed_customer_search(con, p):
    """顧客の横断詳細検索(B-4拡張)。顧客属性＋購入商品属性＋処方箋属性をANDで絞り込み、
    条件に合う顧客の一覧を返す(DM・お声がけ抽出用)。
      p(すべて任意):
        顧客属性: name(氏名/カナ/ID部分一致), staff(担当名), rank, birth_month(1-12),
                  district(部分一致), gender('男'/'女'), dm_ok('1'=DM可のみ),
                  last_buy('none'|'1'|'3'|'5'), exclude('1'=集計対象外/検証を除外・既定)
        購入商品: p_category, p_brand, p_metal, p_stone(部分一致), p_supplier, p_name(品名部分一致),
                  buy_from, buy_to(買上日の期間), prod_match('same'=同一商品で全条件 / 'any'=別々の購入でも可)
        処方箋:   rx_purpose, rx_lens(レンズ名/フレーム名の部分一致), rx_from, rx_to(処方日の期間)
    戻り値: {rows:[[id,name,kana,tel,rank,district,total,staff]], count, truncated}"""
    con.row_factory = sqlite3.Row
    g = lambda k: str((p or {}).get(k) or "").strip()
    where, args = ["COALESCE(c.is_test,0)=0"], []

    # ── 顧客属性 ──
    if g("exclude") != "0":  # 既定で集計対象外(ななし等)を除外
        where.append("COALESCE(c.exclude_stats,0)=0")
    if g("name"):
        nn = "%" + normjp(g("name")) + "%"
        where.append("(normjp(c.name) LIKE ? OR normjp(c.kana) LIKE ? OR c.customer_id = ?)")
        args += [nn, nn, g("name")]
    if g("staff"):
        where.append("c.staff_name = ?"); args.append(g("staff"))
    if g("rank"):
        where.append("c.rank = ?"); args.append(g("rank"))
    if g("birth_month"):
        try:
            where.append("substr(c.birthday,6,2) = ?"); args.append("%02d" % int(g("birth_month")))
        except ValueError:
            pass
    if g("district"):
        where.append("normjp(c.district) LIKE ?"); args.append("%" + normjp(g("district")) + "%")
    if g("gender"):
        where.append("c.gender = ?"); args.append(g("gender"))
    if g("dm_ok") == "1":
        where.append("COALESCE(c.dm_ok,0) = 1")

    # 最終購入(購入の最新日)。none=購入履歴なし / N=N年以上購入なし(購入はあるが古い)
    lb = g("last_buy")
    live_sales = ("SELECT 1 FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                  "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0")
    if lb == "none":
        where.append("NOT EXISTS(" + live_sales + ")")
    elif lb in ("1", "3", "5"):
        import datetime as _dt
        cutoff = (_dt.date.today() - _dt.timedelta(days=365 * int(lb))).isoformat()
        where.append("(SELECT MAX(ss.sold_at) FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                     "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0) < ?")
        args.append(cutoff)

    # ── 購入商品属性(EXISTS) ──
    def prod_conds():
        conds, a = [], []
        if g("p_category"):
            conds.append("pr.category = ?"); a.append(g("p_category"))
        if g("p_brand"):
            conds.append("pr.brand = ?"); a.append(g("p_brand"))
        if g("p_metal"):
            conds.append("pr.metal = ?"); a.append(g("p_metal"))
        if g("p_stone"):
            conds.append("normjp(pr.center_stone) LIKE ?"); a.append("%" + normjp(g("p_stone")) + "%")
        if g("p_supplier"):
            conds.append("pr.supplier = ?"); a.append(g("p_supplier"))
        if g("p_name"):
            conds.append("normjp(COALESCE(sl.free_name, pr.name)) LIKE ?"); a.append("%" + normjp(g("p_name")) + "%")
        return conds, a

    def exists_sale(extra_conds, extra_args):
        base = ("EXISTS(SELECT 1 FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                "LEFT JOIN products pr ON sl.product_key=pr.product_key "
                "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0")
        a = []
        for cnd in extra_conds:
            base += " AND " + cnd
        a += extra_args
        if g("buy_from"):
            base += " AND ss.sold_at >= ?"; a.append(g("buy_from"))
        if g("buy_to"):
            base += " AND ss.sold_at <= ?"; a.append(g("buy_to"))
        return base + ")", a

    pconds, pargs = prod_conds()
    has_period = bool(g("buy_from") or g("buy_to"))
    if pconds or has_period:
        if g("prod_match") == "any" and pconds:
            # 別々の購入でもよい: 各条件を個別のEXISTSにする(期間は各EXISTSに適用)
            for cnd, av in zip(pconds, pargs):
                sql, a = exists_sale([cnd], [av])
                where.append(sql); args += a
            if not pconds and has_period:
                sql, a = exists_sale([], [])
                where.append(sql); args += a
        else:
            # 既定(same): 同一商品(=同じ売上明細)が全条件を満たす
            sql, a = exists_sale(pconds, pargs)
            where.append(sql); args += a

    # ── 処方箋属性(EXISTS) ──
    rxc, rxa = [], []
    if g("rx_purpose"):
        rxc.append("rx.purpose = ?"); rxa.append(g("rx_purpose"))
    if g("rx_lens"):
        rl = "%" + normjp(g("rx_lens")) + "%"
        rxc.append("(normjp(rx.lens_name) LIKE ? OR normjp(rx.frame_name) LIKE ?)")
        rxa += [rl, rl]
    if g("rx_from"):
        rxc.append("rx.rx_date >= ?"); rxa.append(g("rx_from"))
    if g("rx_to"):
        rxc.append("rx.rx_date <= ?"); rxa.append(g("rx_to"))
    if rxc:
        where.append("EXISTS(SELECT 1 FROM prescriptions rx WHERE rx.customer_id=c.customer_id AND "
                     + " AND ".join(rxc) + ")")
        args += rxa

    total_sub = ("(SELECT COALESCE(SUM(sl.amount),0) FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                 "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0)")
    LIMIT = 2000
    sql = ("SELECT c.customer_id id, c.name, c.kana, c.tel, c.rank, c.district, c.staff_name staff, "
           + total_sub + " total FROM customers c WHERE " + " AND ".join(where)
           + " ORDER BY total DESC LIMIT ?")
    rows = []
    for r in con.execute(sql, args + [LIMIT + 1]):
        rows.append([r["id"], r["name"], r["kana"], r["tel"], r["rank"], r["district"],
                     r["total"] or 0, r["staff"]])
    truncated = len(rows) > LIMIT
    if truncated:
        rows = rows[:LIMIT]
    return {"rows": rows, "count": len(rows), "truncated": truncated}


# 顧客ランクの既定基準(B-5)。宝飾ナビの合計金額ランク(1が最上位)に準拠。
# (下限金額, ランク名) を上から判定。設定画面で変更した場合は app_settings に保存される。
RANK_RULES = [
    (1000000, "1"), (500000, "2"), (300000, "3"), (200000, "4"),
    (100000, "5"), (50000, "6"), (9800, "7"), (1, "8"), (0, "9"),
]


def get_rank_rules(con):
    """顧客ランク基準を返す([[下限金額,ランク名],...]・下限の降順)。未設定なら既定値。"""
    row = con.execute("SELECT value FROM app_settings WHERE key='rank_rules'").fetchone()
    if row and row[0]:
        try:
            rules = [[int(r[0]), str(r[1])] for r in json.loads(row[0]) if str(r[1]).strip() != ""]
            if rules:
                rules.sort(key=lambda x: x[0], reverse=True)
                return rules
        except (ValueError, TypeError, IndexError):
            pass
    return [[lo, lab] for lo, lab in RANK_RULES]


def set_rank_rules(con, rules):
    """顧客ランク基準を保存する。rules=[[下限金額,ランク名],...]。"""
    clean = []
    for r in (rules or []):
        try:
            lo = int(str(r[0]).replace(",", ""))
        except (ValueError, TypeError, IndexError):
            continue
        lab = str(r[1]).strip() if len(r) > 1 else ""
        if lab != "":
            clean.append([lo, lab])
    if not clean:
        raise ValueError("有効な基準がありません(金額とランク名を入力してください)")
    clean.sort(key=lambda x: x[0], reverse=True)
    con.execute("INSERT INTO app_settings(key,value) VALUES('rank_rules',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(clean, ensure_ascii=False),))
    con.commit()
    return {"rules": clean}


def rank_for_amount(total, rules=None):
    """合計購入額から基準に沿ったランク名を返す。"""
    t = total or 0
    rules = rules if rules is not None else [list(x) for x in RANK_RULES]
    for lo, label in rules:
        if t >= lo:
            return label
    return rules[-1][1] if rules else ""


def compute_rank_updates(con, kind="", date_from="", date_to="", include_bottom=False):
    """全顧客の合計購入額から新ランクを算出し、現ランクと異なる顧客の一覧を返す(プレビュー)。
      kind: ""=全て / "宝飾" / "メガネ"。集計対象外・検証ペルソナ・取消明細は対象外。
      date_from/date_to: 集計する買上日の期間(YYYY-MM-DD、空なら全期間)。
      include_bottom: True なら最下位ランク(既定"9")の顧客も更新対象に含める(復活可)。
                      False(既定)なら最下位ランクの顧客は据え置き。
    ・distribution: ランクごとの「現在の人数 / 再計算後の人数」内訳(提案B)。
    戻り値: {rules, updates, total_customers, bottom_rank, skipped_bottom,
             include_bottom, distribution, date_from, date_to}"""
    con.row_factory = sqlite3.Row
    rules = get_rank_rules(con)
    bottom_rank = rules[-1][1] if rules else "9"
    where = ["s.customer_id IS NOT NULL", "l.amount IS NOT NULL",
             "COALESCE(l.voided,0)=0", "COALESCE(s.voided,0)=0"]
    args = []
    if kind == "メガネ":
        where.append("p.is_glasses=1")
    elif kind == "宝飾":
        where.append("COALESCE(p.is_glasses,0)=0")
    if date_from:
        where.append("s.sold_at >= ?"); args.append(str(date_from))
    if date_to:
        where.append("s.sold_at <= ?"); args.append(str(date_to))
    totals = {}
    for r in con.execute("""SELECT s.customer_id cid, SUM(l.amount) t
                            FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
                            LEFT JOIN products p ON l.product_key = p.product_key
                            WHERE """ + " AND ".join(where) + " GROUP BY s.customer_id", args):
        totals[r["cid"]] = r["t"] or 0
    labels = [r[1] for r in rules]
    dist_cur = {lab: 0 for lab in labels}   # 現在ランク別の人数
    dist_calc = {lab: 0 for lab in labels}  # 基準どおり再計算した場合の人数
    other_cur = 0  # ランク未設定・基準外の現ランク
    updates = []
    n = 0
    skipped_bottom = 0
    for r in con.execute("""SELECT customer_id, name, rank FROM customers
                            WHERE COALESCE(is_test,0)=0 AND COALESCE(exclude_stats,0)=0"""):
        n += 1
        cur_rank = r["rank"] or ""
        if cur_rank in dist_cur:
            dist_cur[cur_rank] += 1
        else:
            other_cur += 1
        cid = r["customer_id"]
        total = totals.get(cid, 0) or 0
        newr = rank_for_amount(total, rules)
        if newr in dist_calc:
            dist_calc[newr] += 1
        # 最下位ランクの顧客は既定で据え置き(include_bottom=True なら含める)
        if not include_bottom and cur_rank == bottom_rank:
            skipped_bottom += 1
            continue
        if cur_rank != newr:
            updates.append({"customer_id": cid, "name": r["name"] or cid,
                            "old": r["rank"], "new": newr, "total": total})
    updates.sort(key=lambda u: u["total"], reverse=True)
    distribution = [{"rank": lab, "min": rules[i][0],
                     "cur": dist_cur[lab], "calc": dist_calc[lab]}
                    for i, lab in enumerate(labels)]
    return {"rules": rules, "updates": updates, "total_customers": n,
            "bottom_rank": bottom_rank, "skipped_bottom": skipped_bottom,
            "include_bottom": bool(include_bottom), "distribution": distribution,
            "other_cur": other_cur, "date_from": date_from or "", "date_to": date_to or ""}


def apply_rank_updates(con, kind="", date_from="", date_to="", include_bottom=False):
    """compute_rank_updates の変更をまとめて customers.rank に反映する。"""
    res = compute_rank_updates(con, kind, date_from, date_to, include_bottom)
    cur = con.cursor()
    for u in res["updates"]:
        cur.execute("UPDATE customers SET rank=? WHERE customer_id=?", (u["new"], u["customer_id"]))
    con.commit()
    return {"updated": len(res["updates"])}


def _ensure_documents_table(con):
    """発行履歴テーブルを(無ければ)作る。既存DBでもマイグレーション不要で動くように。"""
    con.execute("""CREATE TABLE IF NOT EXISTS issued_documents (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_type   TEXT NOT NULL,          -- 'quote'=見積書 / 'invoice'=請求書
        issued_at  TEXT NOT NULL,          -- 発行日 YYYY-MM-DD
        to_name    TEXT,                   -- 宛名
        keisho     TEXT,                   -- 敬称(様/御中)
        total      INTEGER,                -- 合計(税込)
        tax        INTEGER,                -- 内消費税
        lines_json TEXT,                   -- 明細 [{name,amount},...] のJSON
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")


def save_document(con, p):
    """発行した見積書/請求書を履歴に保存する。"""
    _ensure_documents_table(con)
    lines = p.get("lines") or []
    cur = con.cursor()
    cur.execute("""INSERT INTO issued_documents(doc_type,issued_at,to_name,keisho,total,tax,lines_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (p.get("doc_type"), p.get("issued_at") or datetime.date.today().isoformat(),
                 p.get("to_name"), p.get("keisho"),
                 int(p.get("total") or 0), int(p.get("tax") or 0),
                 json.dumps(lines, ensure_ascii=False)))
    con.commit()
    return {"id": cur.lastrowid}


def list_documents(con, limit=100):
    """発行履歴の一覧(新しい順)。明細も含めて返し、UIで呼び出し→編集できるようにする。"""
    _ensure_documents_table(con)
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    out = []
    for r in con.execute("""SELECT id,doc_type,issued_at,to_name,keisho,total,tax,lines_json
                            FROM issued_documents ORDER BY id DESC LIMIT ?""", (limit,)):
        try:
            lines = json.loads(r["lines_json"] or "[]")
        except (ValueError, TypeError):
            lines = []
        out.append({"id": r["id"], "doc_type": r["doc_type"], "issued_at": r["issued_at"],
                    "to_name": r["to_name"], "keisho": r["keisho"], "total": r["total"],
                    "tax": r["tax"], "lines": lines})
    return out


def set_product_image(con, product_key, image_file):
    """商品の写真ファイル名を更新する(B-7 撮影・登録)。実ファイルの保存はサーバー側で行う。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    cur = con.execute("UPDATE products SET image_file=? WHERE product_key=?", (image_file, pk))
    con.commit()
    if cur.rowcount == 0:
        raise ValueError("対象の商品が見つかりません")
    return {"product_key": pk, "image_file": image_file}


def clear_product_image(con, product_key):
    """商品の写真を外す(間違って登録した写真を取り消す用)。商品自体は削除しない。
    直前まで紐づいていたファイル名を返すので、実ファイルの削除はapp.py側で行う。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    row = con.execute("SELECT image_file FROM products WHERE product_key=?", (pk,)).fetchone()
    if not row:
        raise ValueError("対象の商品が見つかりません")
    old_file = row[0]
    con.execute("UPDATE products SET image_file=NULL WHERE product_key=?", (pk,))
    con.commit()
    return {"product_key": pk, "removed_file": old_file}


# ── 写真プール(まとめて撮影→後で商品に割り当て) ──
def add_photo_pool_entry(con, filename):
    """アップロード済みの1枚をプールに登録する(実ファイル保存はapp.py側)。"""
    con.execute("INSERT INTO photo_pool(filename, uploaded_at) VALUES (?,?)",
                (filename, datetime.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_photo_pool(con):
    """未割当の写真プール一覧(古い=先に撮った順)。件数が多くなりやすいので撮影順消化を想定。"""
    return [{"id": r[0], "filename": r[1], "uploaded_at": r[2]}
            for r in con.execute("SELECT id, filename, uploaded_at FROM photo_pool ORDER BY id")]


def assign_photo_pool(con, pool_id, product_key):
    """プールの1枚を商品に割り当てる(商品のimage_fileに設定し、プールから外す)。"""
    row = con.execute("SELECT filename FROM photo_pool WHERE id=?", (pool_id,)).fetchone()
    if not row:
        raise ValueError("対象の写真が見つかりません(他の人が使用済みかもしれません)")
    fname = row[0]
    set_product_image(con, product_key, fname)
    con.execute("DELETE FROM photo_pool WHERE id=?", (pool_id,))
    con.commit()
    return {"product_key": str(product_key), "image_file": fname}


def delete_photo_pool_row(con, pool_id):
    """プールから1枚を除外する(使わない写真の整理用)。実ファイル削除はapp.py側で行う。"""
    row = con.execute("SELECT filename FROM photo_pool WHERE id=?", (pool_id,)).fetchone()
    if not row:
        raise ValueError("対象の写真が見つかりません")
    con.execute("DELETE FROM photo_pool WHERE id=?", (pool_id,))
    con.commit()
    return row[0]


# 汎用マスタの定義(「名前の一覧」型)。table/col は使用件数と改名時のデータ追随に使う。
# ※table/col はここの固定値のみ(ユーザー入力ではない)なのでSQL的に安全。
MASTERS = {
    "category":   {"label": "商品分類",   "table": "products",      "col": "category"},
    "brand":      {"label": "ブランド",   "table": "products",      "col": "brand"},
    "stone":      {"label": "石種",       "table": "products",      "col": "center_stone"},
    "metal":      {"label": "地金",       "table": "products",      "col": "metal",
                   "seed": ["Pt900", "Pt950", "K18", "K18YG", "K18WG",
                            "K18PG", "K24", "K14", "SV925"]},
    "district":   {"label": "地区",       "table": "customers",     "col": "district"},
    "location":   {"label": "保管場所",   "table": "products",      "col": "location"},
    "motive":     {"label": "購入動機",   "table": "sales_slips",   "col": "motive"},
    "pay_method": {"label": "支払方法",   "table": "sale_payments", "col": "method",
                   "seed": ["現金", "クレジット", "PayPay", "掛売", "分割"]},
    "rank":       {"label": "顧客ランク", "table": "customers",     "col": "rank",
                   "seed": ["SA", "A", "B", "C", "VIP"]},
}


def master_types():
    """管理できるマスタの一覧(マスタ管理TOPのプルダウン用)。"""
    return [{"type": k, "label": v["label"]} for k, v in MASTERS.items()]


def _master_cfg(mtype):
    cfg = MASTERS.get(mtype)
    if not cfg:
        raise ValueError("不明なマスタです")
    return cfg


def sync_master(con, mtype):
    """既存データ(＋seed)に登場する値をマスタに取り込む(未登録のみ)。
    table/col が無いマスタ(地金など)は seed のみ取り込む。"""
    cfg = _master_cfg(mtype)
    for nm in cfg.get("seed", []):
        con.execute("INSERT OR IGNORE INTO master_items(master_type,name) VALUES (?,?)", (mtype, nm))
    t, c = cfg.get("table"), cfg.get("col")
    if t and c:
        con.execute(f"""INSERT OR IGNORE INTO master_items(master_type,name)
                        SELECT ?, {c} FROM {t} WHERE {c} IS NOT NULL AND {c}<>'' GROUP BY {c}""", (mtype,))
    con.commit()


def list_master_items(con, mtype):
    """マスタの項目一覧＋各項目の使用件数(削除時の警告に使う)。
    table/col が無いマスタは使用件数を常に0で返す。"""
    cfg = _master_cfg(mtype)
    sync_master(con, mtype)
    t, c = cfg.get("table"), cfg.get("col")
    items = []
    for r in con.execute("SELECT name FROM master_items WHERE master_type=? ORDER BY name", (mtype,)):
        cnt = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {c}=?", (r[0],)).fetchone()[0] if (t and c) else 0
        items.append({"name": r[0], "count": cnt})
    return {"type": mtype, "label": cfg["label"], "items": items}


def save_master_item(con, p):
    """マスタ項目の 追加/改名/削除。改名時は実データの該当列も追随して置換する
    (table/col が無いマスタはマスタ一覧のみ更新)。"""
    mtype = p.get("type")
    cfg = _master_cfg(mtype)
    action = p.get("action")
    name = str(p.get("name") or "").strip()
    t, c = cfg.get("table"), cfg.get("col")
    cur = con.cursor()
    if action == "add":
        if not name:
            raise ValueError("名称を入力してください")
        cur.execute("INSERT OR IGNORE INTO master_items(master_type,name) VALUES (?,?)", (mtype, name))
    elif action == "rename":
        new = str(p.get("new_name") or "").strip()
        if not name or not new:
            raise ValueError("名称を入力してください")
        if new != name:
            cur.execute("INSERT OR IGNORE INTO master_items(master_type,name) VALUES (?,?)", (mtype, new))
            cur.execute("DELETE FROM master_items WHERE master_type=? AND name=?", (mtype, name))
            if t and c:
                cur.execute(f"UPDATE {t} SET {c}=? WHERE {c}=?", (new, name))  # 実データも追随
    elif action == "delete":
        cur.execute("DELETE FROM master_items WHERE master_type=? AND name=?", (mtype, name))
        # ※実データの値は残す(表示はできる)。マスタのプルダウン候補から消えるだけ。
    else:
        raise ValueError("不明な操作です")
    con.commit()
    return {"ok": True, "type": mtype, "action": action}


def sync_staff_from_names(con):
    """記録に登場する担当者名で staff テーブルに無いものを取り込む(コードは自動採番)。
    取込済みのstaffがある場合は既存を尊重し、名前が未登録のものだけ足す。"""
    existing = {r[0] for r in con.execute("SELECT name FROM staff")}
    row = con.execute("SELECT MAX(CAST(staff_code AS INTEGER)) FROM staff WHERE staff_code GLOB '[0-9]*'").fetchone()
    nxt = (row[0] or 0) + 1
    for r in con.execute("SELECT DISTINCT staff_name FROM customers WHERE staff_name IS NOT NULL AND staff_name<>''"):
        nm = r[0]
        if nm and nm not in existing:
            con.execute("INSERT OR IGNORE INTO staff(staff_code,name,active) VALUES (?,?,1)", (str(nxt), nm))
            existing.add(nm)
            nxt += 1
    con.commit()


# 担当者が実データで紐づく場所(名前で照合)。使用件数=削除時の警告に使う。
STAFF_USAGE = [("customers", "staff_name"), ("sales_slips", "staff_name"),
               ("approach_history", "staff_name"), ("prescriptions", "handler"),
               ("repairs", "staff_name")]


def _staff_usage_map(con):
    """担当者名→使用件数(5テーブル合算)。GROUP BYで一括集計して高速化。"""
    usage = {}
    for t, c in STAFF_USAGE:
        try:
            for r in con.execute(f"SELECT {c}, COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND {c}<>'' GROUP BY {c}"):
                usage[r[0]] = usage.get(r[0], 0) + r[1]
        except sqlite3.Error:
            pass
    return usage


def list_staff(con):
    """担当者マスタ一覧。code/name/active＋使用件数(顧客/売上/アプローチ/処方箋/修理の合算)。
    並び順はデフォルトで番号(staff_code)の昇順。"""
    sync_staff_from_names(con)
    umap = _staff_usage_map(con)
    con.row_factory = sqlite3.Row
    return [{"code": r["staff_code"], "name": r["name"], "active": bool(r["active"]),
             "register": bool(r["is_register"]), "count": umap.get(r["name"], 0)}
            for r in con.execute(
                "SELECT staff_code,name,active,COALESCE(is_register,0) is_register "
                "FROM staff ORDER BY CAST(staff_code AS INTEGER)")]


def save_staff(con, p):
    """担当者の 追加(code空)/更新(name・active)/削除(action=delete)。"""
    code = str(p.get("code") or "").strip()
    name = str(p.get("name") or "").strip()
    active = 1 if p.get("active", 1) else 0
    cur = con.cursor()
    if p.get("action") == "delete":
        if not code:
            raise ValueError("担当者が指定されていません")
        cur.execute("DELETE FROM staff WHERE staff_code=?", (code,))
        con.commit()
        return {"deleted": code}
    if p.get("action") == "cleanup":  # ゴミ担当(旧タグ)の一括整理
        return purge_junk_staff(con)
    # register(レジ会計担当としてワンタップバーに出すか)。payloadに含まれる時だけ更新
    has_reg = "register" in p
    register = 1 if p.get("register") else 0
    if not code:  # 新規
        if not name:
            raise ValueError("担当者名を入力してください")
        row = con.execute("SELECT MAX(CAST(staff_code AS INTEGER)) FROM staff WHERE staff_code GLOB '[0-9]*'").fetchone()
        code = str((row[0] or 0) + 1)
        reg_new = register if has_reg else 0  # 手動追加も既定はレジ表示OFF(必要な人だけON)
        cur.execute("INSERT INTO staff(staff_code,name,active,is_register) VALUES (?,?,?,?)",
                    (code, name, active, reg_new))
    else:  # 更新
        if name:
            cur.execute("UPDATE staff SET name=?, active=? WHERE staff_code=?", (name, active, code))
        else:
            cur.execute("UPDATE staff SET active=? WHERE staff_code=?", (active, code))
        if has_reg:
            cur.execute("UPDATE staff SET is_register=? WHERE staff_code=?", (register, code))
    con.commit()
    return {"code": code, "name": name, "active": bool(active)}


def list_junk_staff(con):
    """ゴミ担当(旧タグらしき担当者)を一覧。整理プレビュー用。使用件数と処理予定を付ける。"""
    umap = _staff_usage_map(con)
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT staff_code,name,active FROM staff ORDER BY name"):
        if _is_junk_staff_name(r["name"]):
            cnt = umap.get(r["name"], 0)
            out.append({"code": r["staff_code"], "name": r["name"], "count": cnt,
                        # 使用0件は削除、使用ありは停止(データ参照を壊さない)
                        "plan": "delete" if cnt == 0 else "deactivate"})
    return out


def purge_junk_staff(con):
    """ゴミ担当(旧タグ)を一括整理。使用0件は削除、使用ありは停止＋レジ非表示にする
    (実データの担当者名は残るので過去伝票の参照は壊れない)。件数を返す。"""
    junk = list_junk_staff(con)
    cur = con.cursor()
    deleted, deactivated = [], []
    for s in junk:
        if s["plan"] == "delete":
            cur.execute("DELETE FROM staff WHERE staff_code=?", (s["code"],))
            deleted.append(s["name"])
        else:
            cur.execute("UPDATE staff SET active=0, is_register=0 WHERE staff_code=?", (s["code"],))
            deactivated.append(s["name"])
    con.commit()
    return {"deleted": deleted, "deactivated": deactivated,
            "count": len(deleted) + len(deactivated)}


def sample_in_stock_key(con):
    """会計デモ用に、在庫状態の商品を1つ選んでその product_key を返す。"""
    row = con.execute("SELECT product_key FROM products WHERE state='在庫' AND name IS NOT NULL LIMIT 1").fetchone()
    return row[0] if row else None


CUSTOMER_FIELDS = ("name", "kana", "gender", "birthday", "wedding_day", "tel", "tel2",
                   "email", "postal", "address", "address2", "rank", "district", "dm_ok",
                   "staff_name", "ring_size", "pierce", "note", "exclude_stats")


def upsert_customer(con, payload):
    """顧客の新規登録/編集。customer_id が空なら採番して新規、あれば更新。"""
    cur = con.cursor()
    cid = str(payload.get("customer_id") or "").strip()
    vals = {k: (payload.get(k) or None) for k in CUSTOMER_FIELDS}
    vals["exclude_stats"] = 1 if payload.get("exclude_stats") else 0  # NULLでなく0/1で保持(集計除外の判定用)
    is_new = not cid
    if is_new:
        row = con.execute("SELECT MAX(CAST(customer_id AS INTEGER)) FROM customers").fetchone()
        cid = str((row[0] or 0) + 1)
        cols = ["customer_id"] + list(CUSTOMER_FIELDS) + ["store_code", "registered_at"]
        ph = ",".join("?" * len(cols))
        cur.execute(f"INSERT INTO customers({','.join(cols)}) VALUES ({ph})",
                    [cid] + [vals[k] for k in CUSTOMER_FIELDS] + ["01", None])
    else:
        setclause = ",".join(f"{k}=?" for k in CUSTOMER_FIELDS)
        cur.execute(f"UPDATE customers SET {setclause} WHERE customer_id=?",
                    [vals[k] for k in CUSTOMER_FIELDS] + [cid])
    con.commit()
    return {"customer_id": cid, "new": is_new}


def add_family(con, p):
    """家族を追加する。
    A(自由入力): {customer_id, name, relation, gender, birthday}
    B(登録済み顧客とリンク): {customer_id, linked_customer_id, relation} を渡すと、
      相手顧客の氏名等をコピーして双方向に登録(相手側にも本人を家族として追加)。
    """
    cid = str(p.get("customer_id") or "").strip()
    if not cid:
        raise ValueError("顧客が指定されていません")
    cur = con.cursor()
    new_id = None
    linked = str(p.get("linked_customer_id") or "").strip() or None
    if linked:
        # B: 相手顧客の情報を取得
        row = con.execute("SELECT name,gender,birthday FROM customers WHERE customer_id=?", (linked,)).fetchone()
        if not row:
            raise ValueError("リンク先の顧客が見つかりません")
        if linked == cid:
            raise ValueError("自分自身は家族に登録できません")
        # 既に同じリンクがあれば重複させない
        dup = con.execute("SELECT id FROM customer_families WHERE customer_id=? AND linked_customer_id=?",
                          (cid, linked)).fetchone()
        if dup:
            new_id = dup[0]
        else:
            cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                           VALUES (?,?,?,?,?,?)""",
                        (cid, row[0], p.get("relation"), row[1], row[2], linked))
            new_id = cur.lastrowid
            # 双方向: 相手側にも本人を家族として登録(続柄は空。あとで相手側で編集可)
            me = con.execute("SELECT name,gender,birthday FROM customers WHERE customer_id=?", (cid,)).fetchone()
            rev = con.execute("SELECT 1 FROM customer_families WHERE customer_id=? AND linked_customer_id=?",
                              (linked, cid)).fetchone()
            if me and not rev:
                cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                               VALUES (?,?,?,?,?,?)""", (linked, me[0], None, me[1], me[2], cid))
    else:
        # A: 自由入力
        if not p.get("name"):
            raise ValueError("家族の氏名を入力してください")
        cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                       VALUES (?,?,?,?,?,?)""",
                    (cid, p.get("name"), p.get("relation"), p.get("gender"), p.get("birthday"), None))
        new_id = cur.lastrowid
    con.commit()
    return {"customer_id": cid, "ok": True, "id": new_id}


def update_family(con, p):
    """家族1件を修正する。リンク(B)行は続柄のみ変更(氏名等は相手顧客に追随)。自由入力(A)行は全項目。"""
    fid = p.get("id")
    if not fid:
        raise ValueError("対象の家族が指定されていません")
    row = con.execute("SELECT customer_id, linked_customer_id FROM customer_families WHERE id=?", (fid,)).fetchone()
    if not row:
        raise ValueError("対象の家族が見つかりません")
    relation = p.get("relation") or None
    if row[1]:  # リンク(B)
        con.execute("UPDATE customer_families SET relation=? WHERE id=?", (relation, fid))
    else:       # 自由入力(A)
        name = (p.get("name") or "").strip()
        if not name:
            raise ValueError("家族の氏名を入力してください")
        con.execute("UPDATE customer_families SET name=?, relation=?, gender=?, birthday=? WHERE id=?",
                    (name, relation, p.get("gender") or None, p.get("birthday") or None, fid))
    con.commit()
    return {"id": fid, "customer_id": row[0], "linked": row[1]}


def delete_family(con, family_id):
    """家族1件を削除する(この顧客側の1行のみ。相手側のリンク行は残す)。"""
    if not family_id:
        raise ValueError("対象の家族が指定されていません")
    row = con.execute("SELECT customer_id FROM customer_families WHERE id=?", (family_id,)).fetchone()
    if not row:
        raise ValueError("対象の家族が見つかりません")
    con.execute("DELETE FROM customer_families WHERE id=?", (family_id,))
    con.commit()
    return {"deleted": family_id, "customer_id": row[0]}


PRODUCT_FIELDS = ("product_no", "name", "category", "brand", "metal", "supplier", "cost_price",
                  "list_price", "location", "center_stone", "center_carat",
                  "color", "clarity", "cut", "cert_no", "info", "fucho",
                  "ring_fingers", "ring_size")

# 符丁(下代を隠す店内符牒)。数字→カナ「エビスアキナイカミ」対応表。
_FUCHO_DIGITS = {"1": "ｴ", "2": "ﾋ", "3": "ｽ", "4": "ｱ", "5": "ｷ",
                 "6": "ﾅ", "7": "ｲ", "8": "ｶ", "9": "ﾐ", "0": "ｹ"}


def fucho_encode(cost_price, head=""):
    """下代(cost_price)の【上3桁】を『エビスアキナイカミ』で符牒化し、頭にメーカー符丁文字(head)を付ける。
    head は仕入先マスタに登録した符丁カナ(supplier_fucho_head で取得)。漢字名対策として
    仕入先名そのものではなく登録済みのカナを使う。
    同じ数字が連続したら 先頭1文字＋「ﾀ」1つ にまとめる(2連でも3連以上でも ﾀ は1つ)。
    例: head='ｳ'・下代30800(上3桁=308) → ｳｽｹｶ / 下代12200(上3桁=122) → ｳｴﾋﾀ。cost が無ければ ''。"""
    digits = "".join(ch for ch in str(cost_price or "") if ch.isdigit())[:3]  # 下代の上3桁のみ
    if not digits:
        return ""
    out = []
    i = 0
    while i < len(digits):
        d = digits[i]
        out.append(_FUCHO_DIGITS.get(d, ""))
        j = i + 1
        while j < len(digits) and digits[j] == d:
            j += 1
        if j - i >= 2:
            out.append("ﾀ")  # 連続はまとめて ﾀ 1つ
        i = j
    return str(head or "") + "".join(out)


def add_product(con, payload):
    """商品(仕入)の新規登録。product_no 空なら自動採番。state は '在庫'。"""
    cur = con.cursor()
    vals = {k: (payload.get(k) or None) for k in PRODUCT_FIELDS}
    name = (vals["name"] or "").strip()
    if not name:
        raise ValueError("商品名は必須です")
    row = con.execute("SELECT MAX(CAST(product_key AS INTEGER)) FROM products").fetchone()
    key = str((row[0] or 0) + 1)
    pno = str(vals["product_no"] or "").strip()
    if not pno:
        # 自動採番は店の5桁系列(22XXX)の続き。6桁以上(別系列)・9桁(過去メガネ)・
        # "*"等のプレースホルダ番号は基準から除外する(それらに引っ張られて桁が増えるのを防ぐ)。
        row = con.execute(
            "SELECT MAX(CAST(product_no AS INTEGER)) FROM products "
            "WHERE product_no GLOB '[0-9]*' AND LENGTH(product_no)<=5").fetchone()
        pno = str((row[0] or 0) + 1).zfill(5)
    vals["product_no"] = pno
    for k in ("cost_price", "list_price"):
        if vals[k] is not None:
            try:
                vals[k] = int(str(vals[k]).replace(",", ""))
            except ValueError:
                raise ValueError("価格は数字で入力してください")
    if not str(vals.get("fucho") or "").strip():  # 符丁が空なら下代＋仕入先から自動生成
        vals["fucho"] = fucho_encode(vals.get("cost_price"), supplier_fucho_head(con, vals.get("supplier"))) or None
    is_glasses = 1 if ("メガネ" in (vals["category"] or "") or "メガネ" in name) else 0
    cols = ["product_key"] + list(PRODUCT_FIELDS) + ["state", "is_glasses", "registered_at"]
    cur.execute(
        f"INSERT INTO products({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [key] + [vals[k] for k in PRODUCT_FIELDS]
        + ["在庫", is_glasses, payload.get("registered_at") or None])
    con.commit()
    stone = vals["center_stone"] or ""
    if stone and vals["center_carat"]:
        stone += f' {vals["center_carat"]}ct'
    return {"product_key": key, "product_no": pno,
            "row": [pno, name, vals["category"], vals["list_price"], "在庫",
                    vals["location"], stone or None]}


def add_consignment(con, payload):
    """受託品(催事等でメーカーの品をその場でレジに通すため)を1件作成する。
    Phase 1(A方式): メーカー(仕入先)と金額だけで即作成。原価は納品書が届くまで未確定(NULL)、
    state='受託'・is_consignment=1。会計するとほかの商品と同じく 売上 になる。品名は任意(既定 受託品)。
    後日、メーカーの納品書で原価・正式品番を入れて精算するのは Phase 2。"""
    cur = con.cursor()
    supplier = str(payload.get("supplier") or "").strip()
    if not supplier:
        raise ValueError("メーカー(仕入先)を選んでください")
    name = str(payload.get("name") or "").strip() or "受託品"
    try:
        amount = int(str(payload.get("amount") or 0).replace(",", ""))
    except ValueError:
        raise ValueError("金額は数字で入力してください")
    row = con.execute("SELECT MAX(CAST(product_key AS INTEGER)) FROM products").fetchone()
    key = str((row[0] or 0) + 1)
    pno = "受託" + key  # 内部キーは常にユニーク。見える番号も受託と分かる形にする
    is_glasses = 1 if GLASS_PAT.search(name) else 0
    cur.execute("""INSERT INTO products(product_key,product_no,name,supplier,list_price,state,
                                        is_consignment,is_glasses,registered_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (key, pno, name, supplier, amount, "受託", 1, is_glasses,
                 datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    return {"product_key": key, "product_no": pno, "name": name,
            "amount": amount, "supplier": supplier}


def consignment_list(con):
    """受託品(is_consignment=1)の一覧。後日精算(納品書で原価入力)用。
    未精算(原価未確定)を先頭に、メーカー別・新しい順。売れた日も付ける。"""
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("""
        SELECT p.product_key, p.name, p.supplier, p.list_price, p.cost_price,
               COALESCE(p.consign_settled,0) settled, p.state,
               (SELECT MAX(s.sold_at) FROM sale_lines l JOIN sales_slips s ON s.slip_id=l.slip_id
                WHERE l.product_key=p.product_key AND COALESCE(l.voided,0)=0) sold_at
        FROM products p
        WHERE COALESCE(p.is_consignment,0)=1
        ORDER BY settled ASC, p.supplier, CAST(p.product_key AS INTEGER) DESC"""):
        rows.append({"product_key": r["product_key"], "name": r["name"], "supplier": r["supplier"],
                     "list_price": r["list_price"], "cost_price": r["cost_price"],
                     "settled": r["settled"], "state": r["state"], "sold_at": r["sold_at"]})
    return {"rows": rows}


def settle_consignment(con, p):
    """受託品の後日精算: 原価(下代)を入れて確定。以降は粗利が正しく計算される。
    精算済みでも原価を入れ直せば更新できる(訂正用)。"""
    pk = str(p.get("product_key") or "").strip()
    if not pk:
        raise ValueError("対象が指定されていません")
    try:
        cost = int(str(p.get("cost") or 0).replace(",", ""))
    except ValueError:
        raise ValueError("原価は数字で入力してください")
    if cost < 0:
        raise ValueError("原価は0以上で入力してください")
    row = con.execute("SELECT COALESCE(is_consignment,0) FROM products WHERE product_key=?", (pk,)).fetchone()
    if not row or not row[0]:
        raise ValueError("対象の受託品が見つかりません")
    con.execute("UPDATE products SET cost_price=?, consign_settled=1 WHERE product_key=?", (cost, pk))
    con.commit()
    return consignment_list(con)


def get_product(con, product_key):
    """商品1件の全項目を返す(修正フォームの初期表示用)。search_products の一覧行より
    項目数が多い(カラー・クラリティ・カット・鑑定書No・備考も含む)。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    con.row_factory = sqlite3.Row
    r = con.execute(
        "SELECT product_key,product_no,name,category,brand,metal,supplier,cost_price,list_price,location,"
        "center_stone,center_carat,color,clarity,cut,cert_no,info,fucho,state,image_file,"
        "ring_fingers,ring_size "
        "FROM products WHERE product_key=?", (pk,)).fetchone()
    if not r:
        raise ValueError("商品が見つかりません")
    return dict(r)


def update_product(con, payload):
    """商品情報の修正(B-7: 登録内容の確認・修正)。product_key必須。
    state(在庫/売上/受託/返品)と image_file はここでは変更しない
    (会計・返品・写真登録の各機能が管理しているため、競合を避けて触れない)。"""
    pk = str(payload.get("product_key") or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    vals = {k: (payload.get(k) or None) for k in PRODUCT_FIELDS}
    name = (vals["name"] or "").strip()
    if not name:
        raise ValueError("商品名は必須です")
    for k in ("cost_price", "list_price"):
        if vals[k] is not None:
            try:
                vals[k] = int(str(vals[k]).replace(",", ""))
            except ValueError:
                raise ValueError("価格は数字で入力してください")
    if not str(vals.get("fucho") or "").strip():  # 符丁が空なら下代＋仕入先から自動生成
        vals["fucho"] = fucho_encode(vals.get("cost_price"), supplier_fucho_head(con, vals.get("supplier"))) or None
    is_glasses = 1 if ("メガネ" in (vals["category"] or "") or "メガネ" in name) else 0
    sets = ",".join(f"{k}=?" for k in PRODUCT_FIELDS) + ",is_glasses=?"
    cur = con.execute(f"UPDATE products SET {sets} WHERE product_key=?",
                       [vals[k] for k in PRODUCT_FIELDS] + [is_glasses, pk])
    con.commit()
    if cur.rowcount == 0:
        raise ValueError("対象の商品が見つかりません")
    return get_product(con, pk)


def delete_product(con, product_key):
    """商品の削除(誤登録の訂正用)。販売履歴(sale_lines)に紐づく商品は削除しない
    (削除すると購入履歴の商品名解決ができなくなるため)。画像ファイル名を返すので、
    実ファイルの削除はapp.py側(ディスク操作)で行う。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    used = con.execute("SELECT COUNT(*) FROM sale_lines WHERE product_key=? AND COALESCE(voided,0)=0", (pk,)).fetchone()[0]
    if used:
        raise ValueError(f"この商品は販売履歴({used}件)と紐づいているため削除できません。誤登録の場合は内容の修正をご利用ください。")
    row = con.execute("SELECT image_file FROM products WHERE product_key=?", (pk,)).fetchone()
    if not row:
        raise ValueError("対象の商品が見つかりません")
    image_file = row[0]
    con.execute("DELETE FROM products WHERE product_key=?", (pk,))
    con.commit()
    return {"deleted": pk, "image_file": image_file}


def add_prescription(con, p):
    """メガネ処方箋の新規登録/編集。id があれば更新、無ければ採番して新規。
    合計金額はレンズ金額+フレーム金額を優先(無ければ total_sell を使用)。"""
    cur = con.cursor()

    def v(k):
        x = p.get(k)
        x = str(x).strip() if x is not None else ""
        return x or None

    def n_int(k):
        try:
            return int(str(p.get(k)).replace(",", ""))
        except (TypeError, ValueError):
            return None

    lens_price, frame_price = n_int("lens_price"), n_int("frame_price")
    total = (lens_price or 0) + (frame_price or 0)
    if not total:
        total = n_int("total_sell")

    cols = ("purpose", "lens_name", "frame_name", "frame_type",
            "sph_r", "sph_l", "cyl_r", "cyl_l", "ax_r", "ax_l", "pri_r", "pri_l", "base_r", "base_l",
            "pri2_r", "pri2_l", "base2_r", "base2_l", "add_r", "add_l",
            "pd_far_both", "pd_far_r", "pd_far_l", "pd_near_both", "pd_near_r", "pd_near_l",
            "naked_both", "naked_r", "naked_l", "corrected_both", "corrected_r", "corrected_l",
            "handler", "rx_date")
    vals = [v(c) for c in cols]
    slid = n_int("sale_line_id")

    def _sync_sale_line_name():
        # 処方箋で品名(レンズ/フレーム)を直したら、紐づく購入明細(番号なし行)の表示名も
        # 合わせて更新する。これで購入一覧の品名も処方箋の修正が反映される。
        # 在庫品(product_key有り)の名前は商品側が正なので触らない(番号なし行のみ)。
        disp = v("lens_name") or v("frame_name")
        if slid and disp:
            cur.execute("UPDATE sale_lines SET free_name=? WHERE line_id=? AND product_key IS NULL",
                        (disp, slid))

    rx_id = n_int("id")
    if rx_id:  # 編集(既存を更新)
        setclause = ",".join(f"{c}=?" for c in cols) + ",lens_price=?,frame_price=?,total_sell=?,sale_line_id=?"
        cur.execute(f"UPDATE prescriptions SET {setclause} WHERE id=?",
                    vals + [lens_price, frame_price, total, slid, rx_id])
        _sync_sale_line_name()
        con.commit()
        row = con.execute("SELECT rx_no FROM prescriptions WHERE id=?", (rx_id,)).fetchone()
        return {"id": rx_id, "rx_no": row[0] if row else None, "total": total}

    n = con.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
    rx_no = f"RX-{n + 1:04d}"
    cur.execute(f"""INSERT INTO prescriptions
        (customer_id,rx_no,{",".join(cols)},lens_price,frame_price,total_sell,sale_line_id,jewelry_misassign)
        VALUES (?,?,{",".join("?" * len(cols))},?,?,?,?,0)""",
        [str(p.get("customer_id")), rx_no] + vals + [lens_price, frame_price, total, slid])
    _sync_sale_line_name()
    con.commit()
    return {"id": cur.lastrowid, "rx_no": rx_no, "total": total}


REPAIR_STATUSES = ["預かり中", "修理中", "連絡済み", "引渡済み"]


def add_repair(con, p):
    """修理伝票の新規登録(預かり)。伝票番号を採番して返す。"""
    cur = con.cursor()

    def n_int(k):
        try:
            return int(str(p.get(k)).replace(",", ""))
        except (TypeError, ValueError):
            return None

    n = con.execute("SELECT COUNT(*) FROM repairs").fetchone()[0]
    repair_no = f"R-{n + 1:06d}"
    cur.execute("""INSERT INTO repairs
        (repair_no,customer_id,item_name,issue,estimate,received_at,promised_at,status,staff_name,note)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (repair_no, str(p.get("customer_id")), p.get("item_name"), p.get("issue"),
         n_int("estimate"), p.get("received_at"), p.get("promised_at"), "預かり中",
         p.get("staff_name"), p.get("note")))
    con.commit()
    return {"id": cur.lastrowid, "repair_no": repair_no, "status": "預かり中"}


def add_repair_photos(con, repair_id, filenames):
    """修理伝票に写真ファイル名を追加する(既存に追記)。戻り値は更新後の全ファイル名リスト。"""
    if not repair_id:
        raise ValueError("修理伝票が指定されていません")
    row = con.execute("SELECT photo_files FROM repairs WHERE id=?", (repair_id,)).fetchone()
    if not row:
        raise ValueError("対象の修理伝票が見つかりません")
    cur = [x for x in (row[0] or "").split(",") if x]
    cur.extend([f for f in (filenames or []) if f])
    con.execute("UPDATE repairs SET photo_files=? WHERE id=?", (",".join(cur), repair_id))
    con.commit()
    return {"id": repair_id, "photos": cur}


def update_repair_status(con, p):
    """修理の進捗を更新(預かり中→修理中→連絡済み→引渡済み)。引渡済みの完了日はサーバー日時を正とする。"""
    repair_id = p.get("id")
    status = p.get("status")
    if status not in REPAIR_STATUSES:
        raise ValueError(f"不正な状態です: {status}")
    completed_at = datetime.date.today().isoformat() if status == "引渡済み" else None
    con.execute("UPDATE repairs SET status=?, completed_at=? WHERE id=?",
                (status, completed_at, repair_id))
    con.commit()
    return {"id": repair_id, "status": status, "completed_at": completed_at}


def add_receivable_payment(con, p):
    """売掛の入金を記録する(特定の売掛行の残高を減らし、入金履歴に1行追加)。"""
    receivable_id = p.get("receivable_id")
    amount = p.get("amount")
    if not receivable_id or not amount or int(amount) <= 0:
        raise ValueError("入金額を正しく入力してください")
    amount = int(amount)
    paid_at = p.get("paid_at") or datetime.date.today().isoformat()
    row = con.execute("SELECT customer_id, balance FROM receivables WHERE id=?", (receivable_id,)).fetchone()
    if not row:
        raise ValueError("対象の売掛が見つかりません")
    cid, balance = row[0], row[1] or 0
    new_balance = balance - amount
    method = (p.get("method") or "現金").strip() or "現金"  # 現金/銀行振込/カード/その他
    cur = con.cursor()
    cur.execute("UPDATE receivables SET balance=?, last_paid_at=? WHERE id=?", (new_balance, paid_at, receivable_id))
    cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid,note,method)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (cid, "入金", paid_at, None, None, amount, p.get("note"), method))
    con.commit()
    return {"receivable_id": receivable_id, "new_balance": new_balance, "paid_at": paid_at,
            "amount": amount, "method": method}


def receivable_summary(con):
    """売掛残高のある顧客ごとの合計(売掛管理の一覧用)。誰がいくら・件数・最古買上日・
    最終入金日を返し、総合計と対象顧客数も付ける。残高の多い順。"""
    con.row_factory = sqlite3.Row
    rows, total = [], 0
    for r in con.execute("""
        SELECT r.customer_id cid, c.name cname, c.staff_name staff, c.tel tel,
               COUNT(*) cnt, SUM(r.balance) bal, MAX(r.last_paid_at) last_paid, MIN(r.bought_at) oldest
        FROM receivables r LEFT JOIN customers c ON c.customer_id = r.customer_id
        WHERE COALESCE(r.balance,0) > 0
        GROUP BY r.customer_id
        HAVING SUM(r.balance) > 0
        ORDER BY bal DESC"""):
        bal = r["bal"] or 0
        total += bal
        rows.append({"customer_id": r["cid"], "name": r["cname"] or r["cid"], "staff": r["staff"],
                     "tel": r["tel"], "count": r["cnt"], "balance": bal,
                     "last_paid": r["last_paid"], "oldest": r["oldest"]})
    return {"rows": rows, "total": total, "count": len(rows)}


def add_receivable(con, p):
    """既存顧客に売掛(未回収残高)を手動で追加する。レジ会計を経由しない過去分の登録用。
    payload: {customer_id, product_name, amount, bought_at}"""
    cid = str(p.get("customer_id") or "").strip()
    if not cid:
        raise ValueError("顧客が指定されていません")
    try:
        amount = int(str(p.get("amount")).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("金額を数字で入力してください")
    if amount <= 0:
        raise ValueError("売掛金額を正しく入力してください")
    bought_at = p.get("bought_at") or datetime.date.today().isoformat()
    name = p.get("product_name") or None
    cur = con.cursor()
    cur.execute("""INSERT INTO receivables(customer_id,product_name,bought_at,down_payment,balance,last_paid_at)
                   VALUES (?,?,?,?,?,?)""", (cid, name, bought_at, 0, amount, None))
    rid = cur.lastrowid
    cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                   VALUES (?,?,?,?,?,?)""", (cid, "掛売", bought_at, name, amount, None))
    con.commit()
    return {"id": rid, "customer_id": cid, "product_name": name, "bought_at": bought_at,
            "down_payment": 0, "balance": amount, "last_paid_at": None}


def update_receivable(con, p):
    """売掛1件の修正(商品名・残高・買上日)。入力ミスの訂正用。"""
    rid = p.get("id")
    if not rid:
        raise ValueError("対象の売掛が指定されていません")
    row = con.execute("SELECT customer_id FROM receivables WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ValueError("対象の売掛が見つかりません")
    try:
        balance = int(str(p.get("amount")).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("金額を数字で入力してください")
    if balance < 0:
        raise ValueError("残高は0以上で入力してください")
    name = p.get("product_name") or None
    bought_at = p.get("bought_at") or None
    con.execute("UPDATE receivables SET product_name=?, balance=?, bought_at=? WHERE id=?",
                (name, balance, bought_at, rid))
    con.commit()
    return {"id": rid, "customer_id": row[0], "product_name": name, "bought_at": bought_at,
            "balance": balance}


def delete_receivable(con, rid):
    """売掛1件を削除(誤登録の訂正用)。売掛残高から消える。入金履歴の記録は残す。"""
    if not rid:
        raise ValueError("対象の売掛が指定されていません")
    row = con.execute("SELECT customer_id FROM receivables WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ValueError("対象の売掛が見つかりません")
    con.execute("DELETE FROM receivables WHERE id=?", (rid,))
    con.commit()
    return {"deleted": rid, "customer_id": row[0]}


def add_cash_movement(con, p):
    """レジ入出金(代引手数料・収入印紙・両替・経費等)を記録する。amountは +入金 / -出金。"""
    try:
        amount = int(str(p.get("amount")).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("金額を数字で入力してください")
    if amount == 0:
        raise ValueError("金額を入力してください(出金はマイナス)")
    occurred_at = p.get("occurred_at") or datetime.date.today().isoformat()
    cur = con.cursor()
    cur.execute("""INSERT INTO cash_movements(category,amount,note,staff_name,occurred_at)
                   VALUES (?,?,?,?,?)""",
                (p.get("category") or "その他", amount, p.get("note"), p.get("staff_name"), occurred_at))
    con.commit()
    return {"id": cur.lastrowid, "category": p.get("category") or "その他", "amount": amount,
            "note": p.get("note"), "staff_name": p.get("staff_name"), "occurred_at": occurred_at}


def list_cash_movements(con, limit=500):
    """レジ入出金の一覧(新しい順)。画面の日報・ホーム集計に使う。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        limit = 500
    return [{"id": r["id"], "category": r["category"], "amount": r["amount"], "note": r["note"],
             "staff_name": r["staff_name"], "occurred_at": r["occurred_at"]}
            for r in con.execute(
                "SELECT id,category,amount,note,staff_name,occurred_at FROM cash_movements "
                "ORDER BY occurred_at DESC, id DESC LIMIT ?", (limit,))]


def checkout(con, payload):
    """会計を実DBに書き込む。伝票+明細+支払内訳+在庫引落+ポイント加算を1トランザクションで。

    支払は複数方法に分けられる(例: 現金5万+クレジット5万)。payments=[{method,amount},...]
    を渡すと、その内訳ごとに sale_payments へ記録し、method="掛売" の内訳は自動的に
    売掛(receivables/receivable_entries)を起票する(店外イベント等の一部後払いに対応)。
    payments を渡さない場合は pay_method 1本(従来どおり)として扱う。

    sold_at を渡すと当日以外の日付(過去)で登録できる(店外イベントの後日精算など)。
    未来日は不可。created_at(登録日時)は別途サーバー時刻で自動記録されるため、
    実際の入力日は後から追跡できる。
    """
    cur = con.cursor()
    today = datetime.date.today().isoformat()
    sold_at = payload.get("sold_at") or today
    try:
        sd = datetime.date.fromisoformat(sold_at)
    except (ValueError, TypeError):
        raise ValueError("売上日の形式が正しくありません(YYYY-MM-DD)")
    if sd > datetime.date.today():
        raise ValueError("売上日は本日より後の日付にはできません")

    cid = str(payload.get("customer_id"))
    lines = payload.get("lines", [])
    # 二重販売の防止(在庫品は1点もの)。同一商品キーの重複 / すでに売却済みの品を弾く。
    line_keys = [l.get("product_key") for l in lines if l.get("product_key")]
    dupes = sorted({k for k in line_keys if line_keys.count(k) > 1})
    if dupes:
        raise ValueError("同じ在庫品が明細に重複しています(在庫1点の品は1会計で1回だけ販売できます)")
    for pk in dict.fromkeys(line_keys):
        prow = con.execute("SELECT state, name FROM products WHERE product_key=?", (pk,)).fetchone()
        if prow and prow[0] == "売上":
            raise ValueError(f"「{prow[1] or pk}」はすでに販売済みです(在庫にありません)。返品してから再販売してください")
    total = sum(int(l.get("amount") or 0) for l in lines)
    earned = total // 200  # デモ: 200円=1pt

    payments = payload.get("payments") or [{"method": payload.get("pay_method", "現金"), "amount": total}]
    pay_total = sum(int(p.get("amount") or 0) for p in payments)
    if pay_total != total:
        raise ValueError(f"支払方法の内訳合計(¥{pay_total:,})が請求金額(¥{total:,})と一致しません")
    methods = [p.get("method") for p in payments if p.get("method") and int(p.get("amount") or 0) > 0]
    pay_label = "+".join(dict.fromkeys(methods)) if methods else "現金"

    cur.execute("""INSERT INTO sales_slips(customer_id,staff_name,store_code,sold_at,pay_method,earned_points)
                   VALUES (?,?,?,?,?,?)""",
                (cid, payload.get("staff_name"), "01", sold_at, pay_label, earned))
    slip_id = cur.lastrowid

    lines_out = []
    for l in lines:
        pk = l.get("product_key")
        amt = int(l.get("amount") or 0)
        cur.execute("""INSERT INTO sale_lines(slip_id,product_key,free_name,amount,spec_pending)
                       VALUES (?,?,?,?,?)""",
                    (slip_id, pk, l.get("free_name"), amt, 1 if l.get("spec_pending") else 0))
        line_id = cur.lastrowid
        name = l.get("free_name")
        cat = None
        is_glass = bool(GLASS_PAT.search(name or ""))
        if pk:
            prow = con.execute("SELECT name,is_glasses,category FROM products WHERE product_key=?", (pk,)).fetchone()
            if prow:
                name, cat = prow[0], prow[2]
                is_glass = is_glass or prow[1] == 1
            cur.execute("UPDATE products SET state='売上' WHERE product_key=?", (pk,))
            cur.execute("""INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id)
                           VALUES (?,?,?,?)""", (pk, "売上引落", -1, slip_id))
        lines_out.append({"line_id": line_id, "name": name, "amount": amt,
                          "glasses": is_glass, "kind": glass_kind(cat, name)})

    item_names = [ln["name"] for ln in lines_out if ln["name"]]
    summary_name = "、".join(dict.fromkeys(item_names)) or None
    if summary_name and len(summary_name) > 60:
        summary_name = summary_name[:59] + "…"

    receivables_out = []
    for p in payments:
        method = p.get("method") or "現金"
        amt = int(p.get("amount") or 0)
        if amt <= 0:
            continue
        cur.execute("INSERT INTO sale_payments(slip_id,method,amount) VALUES (?,?,?)", (slip_id, method, amt))
        if method == "掛売":
            cur.execute("""INSERT INTO receivables(customer_id,product_name,bought_at,down_payment,balance,last_paid_at)
                           VALUES (?,?,?,?,?,?)""", (cid, summary_name, sold_at, 0, amt, None))
            rid = cur.lastrowid  # 画面側でD.urikakeを即時更新できるよう新しい売掛行を返す
            cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                           VALUES (?,?,?,?,?,?)""", (cid, "掛売", sold_at, summary_name, amt, None))
            receivables_out.append({"id": rid, "product_name": summary_name, "bought_at": sold_at,
                                    "down_payment": 0, "balance": amt, "last_paid_at": None})

    if earned:
        row = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
        newbal = (row[0] if row else 0) + earned
        cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,balance,ref_slip_id,occurred_at)
                       VALUES (?,?,?,?,?,?,?)""", (cid, "加算", earned, earned, newbal, slip_id, sold_at))
        cur.execute("""INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)
                       ON CONFLICT(customer_id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
                    (cid, newbal, sold_at))

    con.commit()
    return {"slip_id": slip_id, "earned": earned, "total": total, "lines": lines_out,
            "sold_at": sold_at, "pay_method": pay_label, "receivables": receivables_out}


def _restock_line(con, line_id):
    """取消する明細に在庫品が紐づいていれば在庫に戻す(売上→在庫)。返品の在庫戻し。"""
    row = con.execute("SELECT product_key, slip_id FROM sale_lines WHERE line_id=?", (line_id,)).fetchone()
    if not row:
        return
    pk = row[0]
    if pk:
        con.execute("UPDATE products SET state='在庫' WHERE product_key=? AND state='売上'", (pk,))
        con.execute("""INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id)
                       VALUES (?,?,?,?)""", (pk, "返品", 1, row[1]))


def void_sale_line(con, line_id):
    """明細1行を取消(訂正/一部返品)。集計・履歴から除外し、在庫品なら在庫に戻す。
    最終正データのみ表示する方針のため、取消済み行は各画面に出さない。"""
    line_id = int(line_id)
    row = con.execute("SELECT voided FROM sale_lines WHERE line_id=?", (line_id,)).fetchone()
    if not row:
        raise ValueError("対象の明細が見つかりません")
    if row[0]:
        return {"line_id": line_id, "already": True}
    _restock_line(con, line_id)
    today = datetime.date.today().isoformat()
    con.execute("UPDATE sale_lines SET voided=1, voided_at=? WHERE line_id=?", (today, line_id))
    con.commit()
    return {"line_id": line_id, "voided": True}


def void_sale_slip(con, slip_id):
    """伝票ごと取消(返品)。伝票の全明細を無効化し、在庫品は在庫に戻す。
    伝票のvoidedも立て、入金(sale_payments)も集計から外れる。"""
    slip_id = int(slip_id)
    row = con.execute("SELECT voided FROM sales_slips WHERE slip_id=?", (slip_id,)).fetchone()
    if not row:
        raise ValueError("対象の伝票が見つかりません")
    for lr in con.execute("SELECT line_id FROM sale_lines WHERE slip_id=? AND COALESCE(voided,0)=0", (slip_id,)):
        _restock_line(con, lr[0])
    today = datetime.date.today().isoformat()
    con.execute("UPDATE sale_lines SET voided=1, voided_at=? WHERE slip_id=?", (today, slip_id))
    con.execute("UPDATE sales_slips SET voided=1 WHERE slip_id=?", (slip_id,))
    con.commit()
    return {"slip_id": slip_id, "voided": True}


# ── ログイン認証・ロール制御(アクセス制御④。docs/access-control.md) ──
ROLE_LABELS = {"admin": "管理者", "staff": "社員", "part": "パート"}


def _hash_pw(password, salt=None):
    """パスワードをPBKDF2でハッシュ化して 'salt$hash' 形式で返す(標準ライブラリのみ)。"""
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return salt + "$" + h


def _check_pw(password, stored):
    """保存済みハッシュとパスワードを照合する。"""
    try:
        salt, h = (stored or "").split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return secrets.compare_digest(calc, h)


def list_login_users(con):
    """ログイン画面のユーザー選択用(有効ユーザーのみ・ハッシュは返さない)。"""
    con.row_factory = sqlite3.Row
    return [{"id": r["user_id"], "name": r["display_name"] or r["user_id"],
             "has_pw": bool(r["pass_hash"])}
            for r in con.execute("""SELECT user_id, display_name, pass_hash FROM app_users
                                    WHERE active=1 ORDER BY role='admin' DESC, user_id""")]


def login_user(con, user_id, password):
    """ログイン。パスワード未設定(初回)なら入力されたものを設定して通す。
    成功時 {token, user:{id,name,role}, first_time} / 失敗は ValueError。"""
    row = con.execute("""SELECT user_id, display_name, role, pass_hash, active
                         FROM app_users WHERE user_id=?""", (str(user_id or ""),)).fetchone()
    if not row or not row[4]:
        raise ValueError("ユーザーが見つかりません")
    first = not row[3]
    if first:
        if len(password or "") < 4:
            raise ValueError("初回ログインです。パスワードを4文字以上で決めて入力してください")
        con.execute("UPDATE app_users SET pass_hash=? WHERE user_id=?", (_hash_pw(password), row[0]))
    elif not _check_pw(password, row[3]):
        raise ValueError("パスワードが違います")
    token = secrets.token_hex(32)
    con.execute("INSERT INTO app_sessions(token, user_id, created_at) VALUES (?,?,datetime('now','localtime'))",
                (token, row[0]))
    # 古いセッションの掃除(60日でログインし直し)
    con.execute("DELETE FROM app_sessions WHERE created_at < datetime('now','-60 days','localtime')")
    con.commit()
    return {"token": token, "first_time": first,
            "user": {"id": row[0], "name": row[1] or row[0], "role": row[2] or "staff"}}


def session_user(con, token):
    """セッショントークンからログインユーザーを引く。無効ならNone。"""
    if not token:
        return None
    row = con.execute("""SELECT u.user_id, u.display_name, u.role
                         FROM app_sessions s JOIN app_users u ON u.user_id = s.user_id
                         WHERE s.token=? AND u.active=1
                           AND s.created_at >= datetime('now','-60 days','localtime')""",
                      (token,)).fetchone()
    if not row:
        return None
    return {"id": row[0], "name": row[1] or row[0], "role": row[2] or "staff"}


def logout_user(con, token):
    """セッションを破棄する。"""
    if token:
        con.execute("DELETE FROM app_sessions WHERE token=?", (token,))
        con.commit()
    return {"ok": True}


def list_app_users(con):
    """ユーザー管理画面用の一覧(管理者のみ)。ハッシュ本体は返さない。"""
    con.row_factory = sqlite3.Row
    return [{"id": r["user_id"], "name": r["display_name"] or r["user_id"],
             "role": r["role"] or "staff", "active": bool(r["active"]),
             "has_pw": bool(r["pass_hash"])}
            for r in con.execute("""SELECT user_id, display_name, role, pass_hash, active
                                    FROM app_users ORDER BY role='admin' DESC, user_id""")]


def save_app_user(con, p):
    """ユーザーの追加・更新(管理者のみ)。reset_password=Trueでパスワードを未設定に戻す
    (次回そのユーザーがログインする時に新しいパスワードを設定する)。"""
    uid = str(p.get("id") or "").strip()
    if not uid or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", uid):
        raise ValueError("ログインIDは半角英数字(1〜20文字)で入力してください")
    role = str(p.get("role") or "staff")
    if role not in ROLE_LABELS:
        raise ValueError("役割は 管理者/社員/パート から選んでください")
    name = str(p.get("name") or "").strip() or uid
    active = 1 if p.get("active", True) else 0
    exists = con.execute("SELECT 1 FROM app_users WHERE user_id=?", (uid,)).fetchone()
    # 安全装置: 最後の有効な管理者を降格・無効化してロックアウトしない
    if exists and (role != "admin" or not active):
        others = con.execute("""SELECT COUNT(*) FROM app_users
                                WHERE role='admin' AND active=1 AND user_id != ?""", (uid,)).fetchone()[0]
        was_admin = con.execute("SELECT 1 FROM app_users WHERE user_id=? AND role='admin' AND active=1",
                                (uid,)).fetchone()
        if was_admin and others == 0:
            raise ValueError("最後の管理者は降格・無効化できません(先に別の管理者を作ってください)")
    if exists:
        con.execute("UPDATE app_users SET display_name=?, role=?, active=? WHERE user_id=?",
                    (name, role, active, uid))
    else:
        con.execute("INSERT INTO app_users(user_id, display_name, role, active) VALUES (?,?,?,?)",
                    (uid, name, role, active))
    if p.get("reset_password"):
        con.execute("UPDATE app_users SET pass_hash=NULL WHERE user_id=?", (uid,))
        con.execute("DELETE FROM app_sessions WHERE user_id=?", (uid,))  # 使い回し防止
    if not active:
        con.execute("DELETE FROM app_sessions WHERE user_id=?", (uid,))  # 無効化=即ログアウト
    con.commit()
    return {"users": list_app_users(con)}


def logout_user_all(con, uid):
    """指定ユーザーを全端末から強制ログアウト(セッションを全破棄)。
    パスワード・有効状態は変えないので、本人は同じパスワードで入り直せる。"""
    uid = str(uid or "").strip()
    if not uid:
        raise ValueError("ユーザーが指定されていません")
    con.execute("DELETE FROM app_sessions WHERE user_id=?", (uid,))
    con.commit()
    return {"users": list_app_users(con), "logged_out": uid}
