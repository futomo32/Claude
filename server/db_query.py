"""tokiwa.db から画面用データ(TOKIWA_DATA と同一形状)を組み立て、会計を書き込む。

UIの描画コードを変えずに済むよう、埋め込み版と同じ配列の並びで返す。
"""
import re, sqlite3, datetime

JEWELRY_PAT = re.compile(
    r"ﾘﾝｸﾞ|リング|ﾈｯｸﾚｽ|ネックレス|ﾀﾞｲﾔ|ダイヤ|ｻﾌｧｲｱ|ﾋﾟｱｽ|ﾌﾞﾚｽ|ﾍﾟﾝﾀﾞ|ﾒﾉｰ|ﾙﾋﾞｰ|ｴﾒﾗﾙﾄﾞ|ﾊﾟｰﾙ|真珠|指輪|K1[048]|PT|SV")


def _mark(name):
    if name and JEWELRY_PAT.search(name):
        return "!" + name
    return name


def build_blob(con):
    """全画面ぶんのデータを1つのdictにまとめて返す(埋め込み版と同一形状)。"""
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 売上合算(累計・2026年度)を明細から算出
    totals, y2026 = {}, {}
    for r in cur.execute("""
        SELECT s.customer_id cid, SUM(l.amount) tot,
               SUM(CASE WHEN s.sold_at LIKE '2026%' THEN l.amount ELSE 0 END) y26
        FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
        WHERE s.customer_id IS NOT NULL AND l.amount IS NOT NULL
        GROUP BY s.customer_id"""):
        totals[r["cid"]] = r["tot"] or 0
        y2026[r["cid"]] = r["y26"] or 0

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day
                            FROM customers ORDER BY CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y2026.get(cid, 0), r["wedding_day"],
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

    urikake = group("""SELECT customer_id, product_name, bought_at, down_payment, balance, last_paid_at
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
    for r in cur.execute("""SELECT customer_id,rx_no,purpose,lens_name,frame_name,total_sell,total_list,
                                   sph_r,sph_l,cyl_r,cyl_l,ax_r,ax_l,add_r,add_l,
                                   pd_far_r,pd_far_l,pd_far_both,pd_near_r,pd_near_l,pd_near_both,
                                   handler,rx_date
                            FROM prescriptions"""):
        rx.setdefault(str(r["customer_id"]), []).append([
            r["rx_no"], r["purpose"], _mark(r["lens_name"]), _mark(r["frame_name"]),
            r["total_sell"], r["total_list"],
            r["sph_r"], r["sph_l"], r["cyl_r"], r["cyl_l"], r["ax_r"], r["ax_l"], r["add_r"], r["add_l"],
            r["pd_far_r"], r["pd_far_l"], r["pd_far_both"], r["pd_near_r"], r["pd_near_l"], r["pd_near_both"],
            r["handler"], r["rx_date"],
        ])

    products = []
    for r in cur.execute("""SELECT product_no,name,category,list_price,state,location,
                                   center_stone,center_carat
                            FROM products ORDER BY product_no"""):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        products.append([r["product_no"], r["name"], r["category"], r["list_price"],
                         r["state"], r["location"], stone or None])

    return dict(customers=customers, sales=sales, families=families, points=points,
                pointTx=point_tx, urikake=urikake, urikakeHist=urikake_hist,
                approach=approach, rx=rx, products=products)


def sample_in_stock_key(con):
    """会計デモ用に、在庫状態の商品を1つ選んでその product_key を返す。"""
    row = con.execute("SELECT product_key FROM products WHERE state='在庫' AND name IS NOT NULL LIMIT 1").fetchone()
    return row[0] if row else None


def checkout(con, payload):
    """会計を実DBに書き込む。伝票+明細+在庫引落+ポイント加算を1トランザクションで。"""
    cur = con.cursor()
    today = datetime.date.today().isoformat()
    cid = str(payload.get("customer_id"))
    lines = payload.get("lines", [])
    total = sum(int(l.get("amount") or 0) for l in lines)
    earned = total // 200  # デモ: 200円=1pt

    cur.execute("""INSERT INTO sales_slips(customer_id,staff_name,store_code,sold_at,pay_method,earned_points)
                   VALUES (?,?,?,?,?,?)""",
                (cid, payload.get("staff_name"), "01", today, payload.get("pay_method", "現金"), earned))
    slip_id = cur.lastrowid

    for l in lines:
        pk = l.get("product_key")
        amt = int(l.get("amount") or 0)
        cur.execute("""INSERT INTO sale_lines(slip_id,product_key,free_name,amount,spec_pending)
                       VALUES (?,?,?,?,?)""",
                    (slip_id, pk, l.get("free_name"), amt, 1 if l.get("spec_pending") else 0))
        if pk:
            cur.execute("UPDATE products SET state='売上' WHERE product_key=?", (pk,))
            cur.execute("""INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id)
                           VALUES (?,?,?,?)""", (pk, "売上引落", -1, slip_id))

    if earned:
        row = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
        newbal = (row[0] if row else 0) + earned
        cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,balance,ref_slip_id,occurred_at)
                       VALUES (?,?,?,?,?,?,?)""", (cid, "加算", earned, earned, newbal, slip_id, today))
        cur.execute("""INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)
                       ON CONFLICT(customer_id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
                    (cid, newbal, today))

    con.commit()
    return {"slip_id": slip_id, "earned": earned, "total": total}
