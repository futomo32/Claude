"""tokiwa.db から画面用データ(TOKIWA_DATA と同一形状)を組み立て、会計を書き込む。

UIの描画コードを変えずに済むよう、埋め込み版と同じ配列の並びで返す。
"""
import re, sqlite3, datetime

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
                                   is_test,note,postal,address2
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y2026.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),   # 11=テスト印 12=用途 13=最終購入日
            r["postal"], r["address2"],                    # 14=郵便番号 15=建物名等
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

    families = group("""SELECT customer_id, name, relation, gender, birthday
                        FROM customer_families""")

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
                                   center_stone,center_carat
                            FROM products ORDER BY product_no"""):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        products.append([r["product_no"], r["name"], r["category"], r["list_price"],
                         r["state"], r["location"], stone or None])

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
                repairs=repairs, tenders=tenders)


def sample_in_stock_key(con):
    """会計デモ用に、在庫状態の商品を1つ選んでその product_key を返す。"""
    row = con.execute("SELECT product_key FROM products WHERE state='在庫' AND name IS NOT NULL LIMIT 1").fetchone()
    return row[0] if row else None


CUSTOMER_FIELDS = ("name", "kana", "gender", "birthday", "wedding_day", "tel",
                   "email", "postal", "address", "address2", "rank", "dm_ok",
                   "staff_name", "ring_size", "pierce")


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
