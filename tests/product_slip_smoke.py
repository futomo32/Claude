# -*- coding: utf-8 -*-
"""商品登録の「納品書No」「伝票日付」(v1.3.13 / v1.4.10)を実ブラウザで確かめる。

  python3 server/app.py &
  python3 tests/product_slip_smoke.py

★実ブラウザで動かす確認(動作確認モード用)。蓄積モードでは実行しない。
  管理者ユーザー admin のパスワードをテスト用に設定するので、**本番機では実行しないこと**。
  作ったテスト商品は最後に必ず消す。
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
SLIP = "TEST-DEN-9001"          # この番号で入れた商品をあとでまとめて消す
SLIP2 = "TEST-DEN-9002"


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  OK  " if ok else "★NG  ") + name + (("   … " + str(detail)) if detail else ""))


def cleanup():
    c = sqlite3.connect(DB)
    n = c.execute("DELETE FROM products WHERE purchase_slip_no IN (?,?)", (SLIP, SLIP2)).rowcount
    c.commit()
    c.close()
    return n


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get(
        "CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
    pg = br.new_page(viewport={"width": 1600, "height": 1100})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE, wait_until="networkidle")
    if pg.query_selector("#uid"):
        pg.select_option("#uid", "admin")
        pg.fill("#pw", "tokiwa-test-1234")
        pg.click("#btn")
    pg.wait_for_selector("#app.active", timeout=20000)
    pg.wait_for_timeout(1500)

    # ── ① 仕入登録の画面に欄がある ──
    pg.click('.nav-item[data-screen="products"]')
    pg.wait_for_timeout(1200)
    pg.click('[data-tabgroup="prod"] [data-tab="p-purchase"]')
    pg.wait_for_timeout(800)
    has = pg.evaluate("""() => ({
        np: !!document.getElementById('np-slip-no'),
        label: (function () {
            var el = document.getElementById('np-slip-no');
            return el ? el.closest('.field').querySelector('label').textContent.trim() : '';
        })()})""")
    check("仕入登録に「納品書No」の欄がある(名前は宝飾ナビと同じ)",
          has["np"] and has["label"] == "納品書No", has)

    # ── ② 1点目を登録 → ★伝票番号の欄だけ残る(他は消える) ──
    pg.evaluate("""(slip) => {
        document.getElementById('np-name').value = 'ﾃｽﾄ 伝票番号A';
        document.getElementById('np-slip-no').value = slip;
        document.getElementById('np-cost').value = '1000';
        document.getElementById('np-list').value = '3000';
    }""", SLIP)
    pg.click('#p-purchase button:has-text("登録する")')
    pg.wait_for_timeout(1800)
    after = pg.evaluate("""() => ({
        slip: (document.getElementById('np-slip-no') || {}).value,
        name: (document.getElementById('np-name') || {}).value,
        cost: (document.getElementById('np-cost') || {}).value})""")
    check("★登録しても納品書Noは残る(同じ納品書の商品を続けて登録できる)",
          after["slip"] == SLIP, after["slip"])
    check("他の欄は空に戻る(前の商品を引きずらない)",
          after["name"] == "" and after["cost"] == "", after)

    # ── ③ 2点目を同じ伝票番号で登録(APIで直接。画面の操作は②で確認済み) ──
    made = pg.evaluate("""async (slip) => {
        var r = await fetch('/api/product', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({name:'ﾃｽﾄ 伝票番号B', category:'その他',
                                  cost_price:2000, list_price:5000, purchase_slip_no: slip})});
        return await r.json();
    }""", SLIP)
    saved = [dict(r) for r in (lambda c: (setattr(c, "row_factory", sqlite3.Row), c)[1])(
        sqlite3.connect(DB)).execute(
        "SELECT product_no, name, purchase_slip_no FROM products WHERE purchase_slip_no=? "
        "ORDER BY CAST(product_key AS INTEGER)", (SLIP,))]
    check("2点とも伝票番号がDBに保存されている",
          len(saved) == 2 and all(r["purchase_slip_no"] == SLIP for r in saved),
          [(r["product_no"], r["name"]) for r in saved])

    # ── ④ 在庫一覧の検索欄で伝票番号でも引ける ──
    pg.click('[data-tabgroup="prod"] [data-tab="p-stock"]')
    pg.wait_for_timeout(800)
    pg.fill("#q-prod", SLIP)
    pg.select_option("#q-state", "")          # 状態「すべて」
    pg.evaluate("() => renderProducts()")
    pg.wait_for_timeout(1600)
    found = pg.evaluate("""() => ({total: prodTotal,
        slips: prodRows.map(r => r[13]),
        names: prodRows.map(r => r[1])})""")
    check("★検索欄に伝票番号を入れると、その伝票の商品だけが出る",
          found["total"] == 2 and all(s == "%s" % None or True for s in found["slips"])
          and set(found["slips"]) == {SLIP}, found)

    # 一覧に「仕入伝票」の列が出て、押すと並べ替わる
    col = pg.evaluate("""async () => {
        var ths = Array.from(document.querySelectorAll('#stock-thead th'));
        var i = ths.findIndex(t => t.textContent.indexOf('納品書No') >= 0);
        var d = {heads: ths.length, idx: i,
                 cells: document.querySelectorAll('#stock-tbody tr:first-child td').length,
                 shown: (document.querySelectorAll('#stock-tbody tr:first-child td')[i] || {}).textContent};
        sortProducts('slip');
        await new Promise(r => setTimeout(r, 1500));
        d.sort = prodSort.key; d.dir = prodSort.dir; d.total2 = prodTotal;
        return d;
    }""")
    check("在庫一覧に「納品書No」の列がある(見出しとセルの数が合う)",
          col["idx"] >= 0 and col["heads"] == col["cells"] == 11, col)
    check("その列に伝票番号が出る", col["shown"] == SLIP, col["shown"])
    check("見出しを押すと伝票番号で並べ替わる(件数は変わらない)",
          col["sort"] == "slip" and col["total2"] == 2, col)

    # ── ⑤ 商品詳細に出る ──
    pg.evaluate("() => openProductDetail(0)")
    pg.wait_for_timeout(1500)
    det = pg.evaluate("""() => {
        var rows = Array.from(document.querySelectorAll('#pd-info .kv-row'))
            .map(r => [r.querySelector('.k').textContent.trim(),
                       r.querySelector('.v').textContent.trim()]);
        return {rows: rows,
                slip: (rows.find(r => r[0] === '納品書No') || [])[1]};
    }""")
    check("商品詳細に「納品書No」が出る", det["slip"] == SLIP, det["slip"])

    # ── ⑥ 商品修正で書き換えられる ──
    edited = pg.evaluate("""async (slip2) => {
        startEditProduct();
        await new Promise(r => setTimeout(r, 800));
        var before = document.getElementById('pe-slip-no').value;
        document.getElementById('pe-slip-no').value = slip2;
        document.querySelector('#pd-edit-form button.btn-primary').click();
        await new Promise(r => setTimeout(r, 1800));
        return {before: before};
    }""", SLIP2)
    c = sqlite3.connect(DB)
    n2 = c.execute("SELECT COUNT(*) FROM products WHERE purchase_slip_no=?", (SLIP2,)).fetchone()[0]
    c.close()
    check("修正フォームに今の伝票番号が入っている", edited["before"] == SLIP, edited["before"])
    check("★商品修正で伝票番号を書き換えられる", n2 == 1, n2)

    # ── ⑦ 在庫CSV。★サーバー稼働時に1件も出なかった不具合の再発防止も兼ねる
    #      (D.products は空なので、サーバーから取り直せていないと0件になる) ──
    pg.evaluate("() => { closeProductDetail(); renderProducts(); }")   # 修正を反映してから出す
    pg.wait_for_timeout(1800)
    csv = pg.evaluate("""async () => {
        var got = null, real = window.downloadCsv;
        window.downloadCsv = function (name, rows) { got = {name: name, rows: rows}; };
        exportStockCsv();
        for (var i = 0; i < 60 && !got; i++) await new Promise(r => setTimeout(r, 200));
        window.downloadCsv = real;
        return {csv: got, dProducts: (D.products || []).length, total: prodTotal};
    }""")
    got = (csv or {}).get("csv")
    head = got["rows"][0] if got else []
    idx = head.index("納品書No") if "納品書No" in head else -1
    check("★在庫CSVが実際に書き出される(サーバー稼働時。D.products は空)",
          bool(got) and len(got["rows"]) - 1 == csv["total"] and csv["total"] > 0,
          {"CSVの行": (len(got["rows"]) - 1) if got else None,
           "一覧の件数": csv["total"], "D.products": csv["dProducts"]})
    check("在庫一覧のCSVに「納品書No」の列がある", idx >= 0, head)
    check("★CSVのその列に値が入っている",
          idx >= 0 and any(r[idx] in (SLIP, SLIP2) for r in got["rows"][1:]),
          [r[idx] for r in got["rows"][1:]] if idx >= 0 else None)

    # 絞り込み無しでも出る(店が実際に使う出し方。ここが0件だったのが今回の不具合)
    wide = pg.evaluate("""async () => {
        document.getElementById('q-prod').value = '';
        document.getElementById('q-state').value = '';
        renderProducts();
        await new Promise(r => setTimeout(r, 2000));
        var got = null, real = window.downloadCsv;
        window.downloadCsv = function (n, rows) { got = {rows: rows}; };
        exportStockCsv();
        for (var i = 0; i < 80 && !got; i++) await new Promise(r => setTimeout(r, 200));
        window.downloadCsv = real;
        return {n: got ? got.rows.length - 1 : 0, total: prodTotal};
    }""")
    check("★絞り込み無しでも全件書き出せる",
          wide["n"] == wide["total"] and wide["n"] > 100, wide)

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    pg.screenshot(path=SHOT + "/40_product_slip_no.png")
    br.close()

removed = cleanup()
check("片付け完了(テスト商品を削除)", removed == 2, "%d件削除" % removed)

ng = [r for r in results if not r[1]]
print("\n" + "=" * 56)
print("  %d項目中 %d項目OK / NG %d項目" % (len(results), len(results) - len(ng), len(ng)))
for n, _, d in ng:
    print("    ★ " + n + ("   " + str(d) if d else ""))
sys.exit(1 if ng else 0)
