# -*- coding: utf-8 -*-
"""消費税(8%)と仕入の個数を、実ブラウザとDBの両方で確かめる(v1.2.0)。

  python3 server/app.py &
  python3 tests/tax_smoke.py

★実ブラウザで動かす確認(動作確認モード用)。蓄積モードでは実行しない。
  管理者ユーザー admin のパスワードをテスト用に設定するので、**本番機では実行しないこと**。
  ★DBに商品と伝票を作るので、開発用DBで実行すること(最後に取消・削除して片付ける)。
"""
import os
import sqlite3
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8760"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db", "tokiwa.db")
SHOT = "logs/shots"
os.makedirs(SHOT, exist_ok=True)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  OK  " if ok else "★NG  ") + name + (("   … " + str(detail)) if detail else ""))


def rows(sql, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(sql, args)]
    c.close()
    return out


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get(
        "CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
    pg = br.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE, wait_until="networkidle")
    if pg.query_selector("#uid"):
        pg.select_option("#uid", "admin")
        pg.fill("#pw", "tokiwa-test-1234")
        pg.click("#btn")
    pg.wait_for_selector("#app.active", timeout=20000)
    pg.wait_for_timeout(1500)

    # ── ① 画面の TAX とサーバーの taxes.py が同じ答えか ──
    #    同じ規則を2つの言語で持っているので、ここがずれると画面とレシートで金額が食い違う
    js = pg.evaluate("""() => {
        var lines = [{amount:75000, tax_rate:10}, {amount:1080, tax_rate:8}, {amount:500, tax_rate:10}];
        return {t10: TAX.of(75000,10), t8: TAX.of(1080,8), total: TAX.total(lines),
                ordered: TAX.ordered(lines).map(function(x){return [x.rate,x.total,x.tax];})};
    }""")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
    import taxes as T
    pyl = [{"amount": 75000, "tax_rate": 10}, {"amount": 1080, "tax_rate": 8},
           {"amount": 500, "tax_rate": 10}]
    pys = T.split_by_rate(pyl)
    py_ordered = [[r, pys[r]["total"], pys[r]["tax"]] for r in sorted(pys, reverse=True)]
    check("★画面とサーバーの税計算が一致する",
          js["t10"] == T.tax_of(75000, 10) and js["t8"] == T.tax_of(1080, 8)
          and js["total"] == T.total_tax(pyl) and js["ordered"] == py_ordered,
          {"画面": js, "サーバー": {"total": T.total_tax(pyl), "ordered": py_ordered}})

    # ── ② 仕入登録: 税率8% × 個数3 ──
    pg.click('.nav-item[data-screen="products"]')
    pg.wait_for_timeout(1200)
    tab = pg.query_selector('[data-tabgroup="prod"] [data-tab="p-new"]')
    if tab:
        tab.click()
        pg.wait_for_timeout(800)
    made = pg.evaluate("""async () => {
        var r = await fetch('/api/product', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({name:'ﾃｽﾄ ｸｯｷｰ', category:'その他',
                                  list_price:1080, cost_price:600, tax_rate:'8', qty:3})});
        return await r.json();
    }""")
    check("個数3で3件登録される", made.get("count") == 3,
          f'{made.get("first_no")}〜{made.get("last_no")}')
    keys = [m["product_key"] for m in made.get("products", [])]
    got = rows("SELECT tax_rate FROM products WHERE product_key IN (%s)"
               % ",".join("?" * len(keys)), keys) if keys else []
    check("3件とも8%で保存される", {g["tax_rate"] for g in got} == {8}, got)

    # 商品番号を書いた時は個数2を断る
    ng = pg.evaluate("""async () => {
        var r = await fetch('/api/product', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({name:'x', product_no:'99999', qty:2})});
        return await r.json();
    }""")
    check("番号を指定した時は個数2を断る", bool(ng.get("error")), (ng.get("error") or "")[:38])

    # 画面に個数と税率の欄があるか
    fld = pg.evaluate("""() => ({qty: !!document.getElementById('np-qty'),
                                 rate: !!document.getElementById('np-tax-rate'),
                                 rateDefault: (document.getElementById('np-tax-rate')||{}).value})""")
    check("仕入登録の画面に個数と税率がある",
          fld["qty"] and fld["rate"] and fld["rateDefault"] == "10", fld)

    # ── ③ レジ: 8%と10%を混ぜて会計 ──
    pg.click('.nav-item[data-screen="register"]')
    pg.wait_for_timeout(1000)
    for b in pg.query_selector_all(".op-bar .op-btn"):
        t = (b.inner_text() or "").strip()
        if t and not t.startswith("＋"):
            b.click()
            break
    pg.wait_for_timeout(300)
    tenpct = rows("SELECT product_key, product_no FROM products "
                  "WHERE state='在庫' AND COALESCE(tax_rate,10)=10 AND list_price>0 LIMIT 1")[0]
    before = len(rows("SELECT slip_id FROM sales_slips"))
    res = pg.evaluate("""async (a) => {
        var r = await fetch('/api/checkout', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({customer_id: a.cid, staff_name:'三輪', sold_at:'2026-09-02',
              payments:[{method:'現金', amount:76080}], deposit:80000,
              lines:[{product_key: a.p10, amount:75000},
                     {product_key: a.p8, amount:1080}]})});
        return await r.json();
    }""", {"cid": rows("SELECT customer_id FROM customers LIMIT 1")[0]["customer_id"],
           "p10": tenpct["product_key"], "p8": keys[0]})
    sid = res.get("slip_id")
    check("8%と10%を混ぜて会計できる", bool(sid) and not res.get("error"), res.get("error") or sid)
    ln = rows("SELECT amount, tax, tax_rate FROM sale_lines WHERE slip_id=? ORDER BY line_id", (sid,))
    check("明細に税率が焼き付く", [x["tax_rate"] for x in ln] == [10, 8], ln)
    check("行ごとの税額が正しい", [x["tax"] for x in ln] == [6818, 80], [x["tax"] for x in ln])

    # ★商品の税率を後から変えても、過去の伝票は変わらない
    c = sqlite3.connect(DB)
    c.execute("UPDATE products SET tax_rate=10 WHERE product_key=?", (keys[0],))
    c.commit()
    c.close()
    check("★商品の税率を変えても過去の伝票は変わらない",
          [x["tax_rate"] for x in rows(
              "SELECT tax_rate FROM sale_lines WHERE slip_id=? ORDER BY line_id", (sid,))] == [10, 8])

    # ── ④ レシート ──
    import db_query as Q
    import devices as D
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    Q.ensure_schema(con)
    rc = Q.receipt_data(con, sid, 80000)
    txt = D.build_receipt_bytes(rc).decode("shift_jis", "replace")
    con.close()
    check("レシートに 10%対象 と 8%対象 が並ぶ", "10%対象" in txt and "8%対象" in txt)
    check("軽減税率の品名に ※ が付く", T.REDUCED_MARK + "ﾃｽﾄ" in txt.replace(" ", ""))
    check("※の凡例が出る", T.REDUCED_NOTE in txt)
    check("税額が税率ごとに出ている", "6,818" in txt and "80" in txt)

    # ── ⑤ 片付け(取消して、作った商品を消す) ──
    pg.evaluate("""async (sid) => {
        await fetch('/api/void_slip', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({slip_id: sid, reason:'動作確認のテスト',
                                  operator:'admin', staff:'admin'})});
    }""", sid)
    pg.wait_for_timeout(1000)
    c = sqlite3.connect(DB)
    c.execute("DELETE FROM stock_events WHERE product_key IN (%s)" % ",".join("?" * len(keys)), keys)
    c.execute("DELETE FROM products WHERE product_key IN (%s)" % ",".join("?" * len(keys)), keys)
    c.commit()
    c.close()
    check("片付け完了(テスト商品を削除)", not rows(
        "SELECT product_key FROM products WHERE product_key IN (%s)"
        % ",".join("?" * len(keys)), keys))

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    br.close()

print("\n" + "=" * 56)
ng = [r for r in results if not r[1]]
print(f"  {len(results)}項目中 {len(results)-len(ng)}項目OK / NG {len(ng)}項目")
for n, _o, d in ng:
    print(f"    ★ {n}   {d}")
sys.exit(1 if ng else 0)
