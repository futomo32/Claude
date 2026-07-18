"""tokiwa.db から画面用データ(TOKIWA_DATA と同一形状)を組み立て、会計を書き込む。

UIの描画コードを変えずに済むよう、埋め込み版と同じ配列の並びで返す。
"""
import json, re, sqlite3, datetime

GLASS_PAT = re.compile(r"メガネ|眼鏡|レンズ|フレーム|ﾒｶﾞﾈ|ﾚﾝｽﾞ")
FRAME_PAT = re.compile(r"フレーム|ﾌﾚｰﾑ|frame", re.I)
LENS_PAT = re.compile(r"レンズ|ﾚﾝｽﾞ|lens|非球面|累進", re.I)


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
    def cols(t):
        try:
            return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        except sqlite3.Error:
            return set()
    adds = [
        ("products", "image_file", "TEXT"),
        ("customers", "tel2", "TEXT"), ("customers", "note", "TEXT"),
        ("customers", "postal", "TEXT"), ("customers", "address2", "TEXT"),
        ("customers", "email", "TEXT"),
        ("customer_families", "linked_customer_id", "TEXT"),
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
    if changed:
        con.commit()


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
        GROUP BY s.customer_id"""):
        totals[r["cid"]] = r["tot"] or 0
        y2026[r["cid"]] = r["y26"] or 0
        last_buy[r["cid"]] = r["last"]

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day,
                                   is_test,note,postal,address2,tel2,email
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y2026.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),   # 11=テスト印 12=用途 13=最終購入日
            r["postal"], r["address2"],                    # 14=郵便番号 15=建物名等
            r["tel2"], r["email"],                         # 16=携帯電話(TEL2) 17=eメール
        ])

    def group(sql, key_idx=0):
        d = {}
        for row in cur.execute(sql):
            vals = list(row)
            d.setdefault(str(vals[key_idx]), []).append(vals[1:])
        return d

    sales = group("""SELECT s.customer_id, s.sold_at, COALESCE(l.free_name, p.name), l.info,
                            l.amount, s.pay_method, s.staff_name
                     FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
                     LEFT JOIN products p ON l.product_key = p.product_key
                     WHERE s.customer_id IS NOT NULL
                     ORDER BY s.sold_at DESC""")

    families = group("""SELECT customer_id, name, relation, gender, birthday, linked_customer_id, id
                        FROM customer_families ORDER BY id""")

    urikake = group("""SELECT customer_id, id, product_name, bought_at, down_payment, balance, last_paid_at
                       FROM receivables""")
    urikake_hist = group("""SELECT customer_id, entry_date, entry_type, product_name, amount, paid
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
        WHERE s.customer_id IS NOT NULL"""):
        nm = r["nm"] or ""
        is_glass = r["g"] == 1 or bool(GLASS_PAT.search(nm))
        if is_glass and r["line_id"] not in linked:
            rx_candidates.setdefault(str(r["cid"]), []).append(
                [r["line_id"], r["sold_at"], nm, r["amount"], glass_kind(r["cat"], nm)])

    products = []
    for r in cur.execute("""SELECT product_no,name,category,list_price,state,location,
                                   center_stone,center_carat,product_key,image_file
                            FROM products ORDER BY product_no"""):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        products.append([r["product_no"], r["name"], r["category"], r["list_price"],
                         r["state"], r["location"], stone or None, r["product_key"], r["image_file"]])

    repairs = []
    for r in cur.execute("""SELECT id,repair_no,customer_id,item_name,issue,estimate,
                                   received_at,promised_at,status,completed_at,staff_name,note
                            FROM repairs ORDER BY id DESC"""):
        repairs.append({
            "id": r["id"], "repair_no": r["repair_no"], "customer_id": r["customer_id"],
            "item_name": r["item_name"], "issue": r["issue"], "estimate": r["estimate"],
            "received_at": r["received_at"], "promised_at": r["promised_at"],
            "status": r["status"], "completed_at": r["completed_at"],
            "staff_name": r["staff_name"], "note": r["note"],
        })

    # 在庫サマリ(状態=在庫の商品のみ)。上代=list_price(税込)、下代=cost_price(税別)。
    # 粗利率 = (1 - 下代×(1+消費税率) / 上代) × 100  … 下代を税込換算して上代(税込)と比較。
    # ※消費税率は当面10%固定。将来 zztaxrate 連動やロール別の非表示は access-control で対応。
    TAX_RATE = 0.10
    srow = cur.execute("""SELECT COUNT(*) c, COALESCE(SUM(list_price),0) lt, COALESCE(SUM(cost_price),0) ct
                          FROM products WHERE state='在庫'""").fetchone()
    s_count, s_list, s_cost = srow["c"], srow["lt"] or 0, srow["ct"] or 0
    s_margin = round((1 - (s_cost * (1 + TAX_RATE)) / s_list) * 100, 1) if s_list else 0
    stock_stats = {"count": s_count, "listTotal": s_list, "costTotal": s_cost,
                   "marginRate": s_margin, "taxRate": TAX_RATE}

    # 支払方法の内訳(フラット配列)。日報等で「支払方法別の実額」を正確に集計するために使う
    # (1会計が複数方法に分かれる場合、明細1行ごとの支払方法は代表ラベルに過ぎないため)
    tenders = []
    for r in cur.execute("""SELECT s.sold_at, sp.method, sp.amount, s.customer_id
                            FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
                            ORDER BY s.sold_at DESC"""):
        tenders.append([r["sold_at"], r["method"], r["amount"], str(r["customer_id"])])

    return dict(customers=customers, sales=sales, families=families, points=points,
                pointTx=point_tx, urikake=urikake, urikakeHist=urikake_hist,
                approach=approach, rx=rx, rxCandidates=rx_candidates, products=products,
                repairs=repairs, tenders=tenders, stockStats=stock_stats)


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
        GROUP BY s.customer_id""", (cur_year + "%",)):
        totals[r["cid"]] = r["tot"] or 0
        y_cur[r["cid"]] = r["yc"] or 0
        last_buy[r["cid"]] = r["last"]

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day,
                                   is_test,note,postal,address2,tel2,email
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y_cur.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),
            r["postal"], r["address2"], r["tel2"], r["email"],
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
                       FROM receivables""")
    urikake_hist = group("""SELECT customer_id, entry_date, entry_type, product_name, amount, paid
                            FROM receivable_entries ORDER BY entry_date DESC""")
    points = {str(r["customer_id"]): r["balance"]
              for r in cur.execute("SELECT customer_id, balance FROM point_balances")}

    repairs = []
    for r in cur.execute("""SELECT id,repair_no,customer_id,item_name,issue,estimate,
                                   received_at,promised_at,status,completed_at,staff_name,note
                            FROM repairs ORDER BY id DESC"""):
        repairs.append({
            "id": r["id"], "repair_no": r["repair_no"], "customer_id": r["customer_id"],
            "item_name": r["item_name"], "issue": r["issue"], "estimate": r["estimate"],
            "received_at": r["received_at"], "promised_at": r["promised_at"],
            "status": r["status"], "completed_at": r["completed_at"],
            "staff_name": r["staff_name"], "note": r["note"],
        })

    TAX_RATE = 0.10
    srow = cur.execute("""SELECT COUNT(*) c, COALESCE(SUM(list_price),0) lt, COALESCE(SUM(cost_price),0) ct
                          FROM products WHERE state='在庫'""").fetchone()
    s_count, s_list, s_cost = srow["c"], srow["lt"] or 0, srow["ct"] or 0
    s_margin = round((1 - (s_cost * (1 + TAX_RATE)) / s_list) * 100, 1) if s_list else 0
    stock_stats = {"count": s_count, "listTotal": s_list, "costTotal": s_cost,
                   "marginRate": s_margin, "taxRate": TAX_RATE}

    tenders = []
    for r in cur.execute("""SELECT s.sold_at, sp.method, sp.amount, s.customer_id
                            FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
                            ORDER BY s.sold_at DESC"""):
        tenders.append([r["sold_at"], r["method"], r["amount"], str(r["customer_id"])])

    return dict(customers=customers, families=families, points=points,
                urikake=urikake, urikakeHist=urikake_hist,
                repairs=repairs, tenders=tenders, stockStats=stock_stats,
                lite=True)  # lite=True で「明細は遅延取得」とUIに知らせる


def _rx_row(r):
    """prescriptions の1行を画面用dictに変換(build_blob と customer_detail で共用)。"""
    return {
        "id": r["id"], "rx_no": r["rx_no"], "purpose": r["purpose"],
        "lens_name": r["lens_name"], "frame_name": r["frame_name"],
        "lens_price": r["lens_price"], "frame_price": r["frame_price"], "total": r["total_sell"],
        "misassign": bool(r["jewelry_misassign"]), "sale_line_id": r["sale_line_id"],
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


def customer_detail(con, cid):
    """1顧客ぶんの重い明細(売上/処方箋/処方箋候補/ポイント履歴/アプローチ)を返す。
    顧客詳細を開いた時にだけ呼ぶ(遅延取得)。UIの D.sales[id] 等と同じ形状。"""
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cid = str(cid)

    sales = [list(r) for r in cur.execute("""
        SELECT s.sold_at, COALESCE(l.free_name, p.name), l.info,
               l.amount, s.pay_method, s.staff_name
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ?
        ORDER BY s.sold_at DESC""", (cid,))]

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
        WHERE s.customer_id = ?""", (cid,)):
        nm = r["nm"] or ""
        is_glass = r["g"] == 1 or bool(GLASS_PAT.search(nm))
        if is_glass and r["line_id"] not in linked:
            rx_candidates.append([r["line_id"], r["sold_at"], nm, r["amount"], glass_kind(r["cat"], nm)])

    return {"sales": sales, "rx": rx, "rxCandidates": rx_candidates,
            "pointTx": point_tx, "approach": approach}


def search_products(con, q="", cat="", state="", supplier="", limit=50, offset=0):
    """商品検索(在庫一覧・レジの商品ピッカー用)。全商品(21万件)を送らずサーバーで絞り込む。
    戻り値 {rows:[...], total:N}。rows は [商品番号,品名,分類,上代,状態,置場,石,商品キー]。
    末尾の商品キー(product_key)はレジで在庫引落・購入履歴の紐付けに使う内部キー。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    where, args = [], []
    if q:
        where.append("(product_no LIKE ? OR name LIKE ?)")
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        args += [like, like]
    if cat:
        where.append("category = ?"); args.append(cat)
    if state:
        where.append("state = ?"); args.append(state)
    if supplier:
        where.append("supplier = ?"); args.append(supplier)
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    total = con.execute("SELECT COUNT(*) FROM products" + wsql, args).fetchone()[0]
    rows = []
    for r in con.execute(
            "SELECT product_no,name,category,list_price,state,location,center_stone,center_carat,product_key,image_file "
            "FROM products" + wsql + " ORDER BY product_no LIMIT ? OFFSET ?", args + [limit, offset]):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        rows.append([r["product_no"], r["name"], r["category"], r["list_price"],
                     r["state"], r["location"], stone or None, r["product_key"], r["image_file"]])
    return {"rows": rows, "total": total}


def product_categories(con):
    """商品分類の一覧(在庫一覧の絞り込みプルダウン用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category<>'' ORDER BY category")]


def product_suppliers(con):
    """仕入先の一覧(在庫一覧・レジの商品ピッカーの絞り込みプルダウン用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT supplier FROM products WHERE supplier IS NOT NULL AND supplier<>'' ORDER BY supplier")]


def daily_sales(con, date):
    """指定日のレジ売上明細(日報・ホームタイル用)。全売上をブラウザに持たずサーバーで集計。"""
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("""
        SELECT s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.info, l.amount, s.pay_method, s.staff_name
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sold_at = ?""", (str(date),)):
        out.append({"cid": r["cid"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "info": r["info"], "amount": r["amount"] or 0,
                    "pay": r["pay_method"] or "現金", "staff": r["staff_name"]})
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
               COALESCE(l.free_name, p.name) item, l.amount, s.pay_method, s.staff_name
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sold_at >= ? AND s.sold_at <= ?""" + staffsql + """
        ORDER BY s.sold_at""", args):
        out.append({"date": r["sold_at"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "amount": r["amount"] or 0, "pay": r["pay_method"] or "", "staff": r["staff_name"]})
    return out


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


def sample_in_stock_key(con):
    """会計デモ用に、在庫状態の商品を1つ選んでその product_key を返す。"""
    row = con.execute("SELECT product_key FROM products WHERE state='在庫' AND name IS NOT NULL LIMIT 1").fetchone()
    return row[0] if row else None


CUSTOMER_FIELDS = ("name", "kana", "gender", "birthday", "wedding_day", "tel", "tel2",
                   "email", "postal", "address", "address2", "rank", "dm_ok",
                   "staff_name", "ring_size", "pierce", "note")


def upsert_customer(con, payload):
    """顧客の新規登録/編集。customer_id が空なら採番して新規、あれば更新。"""
    cur = con.cursor()
    cid = str(payload.get("customer_id") or "").strip()
    vals = {k: (payload.get(k) or None) for k in CUSTOMER_FIELDS}
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
    linked = str(p.get("linked_customer_id") or "").strip() or None
    if linked:
        # B: 相手顧客の情報を取得
        row = con.execute("SELECT name,gender,birthday FROM customers WHERE customer_id=?", (linked,)).fetchone()
        if not row:
            raise ValueError("リンク先の顧客が見つかりません")
        if linked == cid:
            raise ValueError("自分自身は家族に登録できません")
        # 既に同じリンクがあれば重複させない
        dup = con.execute("SELECT 1 FROM customer_families WHERE customer_id=? AND linked_customer_id=?",
                          (cid, linked)).fetchone()
        if not dup:
            cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                           VALUES (?,?,?,?,?,?)""",
                        (cid, row[0], p.get("relation"), row[1], row[2], linked))
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
    con.commit()
    return {"customer_id": cid, "ok": True}


PRODUCT_FIELDS = ("product_no", "name", "category", "supplier", "cost_price",
                  "list_price", "location", "center_stone", "center_carat",
                  "color", "clarity", "cut", "cert_no", "info")


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
        row = con.execute(
            "SELECT MAX(CAST(product_no AS INTEGER)) FROM products WHERE product_no GLOB '[0-9]*'").fetchone()
        pno = str((row[0] or 0) + 1).zfill(5)
    vals["product_no"] = pno
    for k in ("cost_price", "list_price"):
        if vals[k] is not None:
            try:
                vals[k] = int(str(vals[k]).replace(",", ""))
            except ValueError:
                raise ValueError("価格は数字で入力してください")
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

    cols = ("purpose", "lens_name", "frame_name",
            "sph_r", "sph_l", "cyl_r", "cyl_l", "ax_r", "ax_l", "pri_r", "pri_l", "base_r", "base_l",
            "pri2_r", "pri2_l", "base2_r", "base2_l", "add_r", "add_l",
            "pd_far_both", "pd_far_r", "pd_far_l", "pd_near_both", "pd_near_r", "pd_near_l",
            "naked_both", "naked_r", "naked_l", "corrected_both", "corrected_r", "corrected_l",
            "handler", "rx_date")
    vals = [v(c) for c in cols]

    rx_id = n_int("id")
    if rx_id:  # 編集(既存を更新)
        setclause = ",".join(f"{c}=?" for c in cols) + ",lens_price=?,frame_price=?,total_sell=?,sale_line_id=?"
        cur.execute(f"UPDATE prescriptions SET {setclause} WHERE id=?",
                    vals + [lens_price, frame_price, total, n_int("sale_line_id"), rx_id])
        con.commit()
        row = con.execute("SELECT rx_no FROM prescriptions WHERE id=?", (rx_id,)).fetchone()
        return {"id": rx_id, "rx_no": row[0] if row else None, "total": total}

    n = con.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
    rx_no = f"RX-{n + 1:04d}"
    cur.execute(f"""INSERT INTO prescriptions
        (customer_id,rx_no,{",".join(cols)},lens_price,frame_price,total_sell,sale_line_id,jewelry_misassign)
        VALUES (?,?,{",".join("?" * len(cols))},?,?,?,?,0)""",
        [str(p.get("customer_id")), rx_no] + vals + [lens_price, frame_price, total, n_int("sale_line_id")])
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
    cur = con.cursor()
    cur.execute("UPDATE receivables SET balance=?, last_paid_at=? WHERE id=?", (new_balance, paid_at, receivable_id))
    cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid,note)
                   VALUES (?,?,?,?,?,?,?)""",
                (cid, "入金", paid_at, None, None, amount, p.get("note")))
    con.commit()
    return {"receivable_id": receivable_id, "new_balance": new_balance, "paid_at": paid_at, "amount": amount}


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

    for p in payments:
        method = p.get("method") or "現金"
        amt = int(p.get("amount") or 0)
        if amt <= 0:
            continue
        cur.execute("INSERT INTO sale_payments(slip_id,method,amount) VALUES (?,?,?)", (slip_id, method, amt))
        if method == "掛売":
            cur.execute("""INSERT INTO receivables(customer_id,product_name,bought_at,down_payment,balance,last_paid_at)
                           VALUES (?,?,?,?,?,?)""", (cid, summary_name, sold_at, 0, amt, None))
            cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                           VALUES (?,?,?,?,?,?)""", (cid, "掛売", sold_at, summary_name, amt, None))

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
            "sold_at": sold_at, "pay_method": pay_label}
