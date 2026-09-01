# -*- coding: utf-8 -*-
"""レジで1件会計し、伝票・在庫・日報に反映されるかを確かめる(最後に取消して元に戻す)。

  python3 server/app.py &          # 先にサーバーを起動しておく
  python3 tests/pos_smoke.py

★実ブラウザで動かす確認(動作確認モード用)。蓄積モードでは実行しない。
  管理者ユーザー admin のパスワードをテスト用に設定するので、**本番機では実行しないこと**。
  画面の写真は logs/shots/ に残る(.gitignore 済み)。
"""
import sqlite3
import os
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


def q(sql, args=()):
    c = sqlite3.connect(DB)
    r = c.execute(sql, args).fetchone()
    c.close()
    return r[0] if r else None


before_slips = q("SELECT COUNT(*) FROM sales_slips")
before_stock = q("SELECT COUNT(*) FROM products WHERE state='在庫'")
target = sqlite3.connect(DB).execute(
    "SELECT product_no, name FROM products WHERE state='在庫' AND product_no IS NOT NULL "
    "AND list_price > 0 LIMIT 1").fetchone()
print(f"前: 伝票={before_slips} 在庫={before_stock} / 使う商品={target}\n")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
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

    # ── レジへ ──
    pg.click('.nav-item[data-screen="register"]')
    pg.wait_for_timeout(1200)

    # 会計担当を1人選ぶ
    st = pg.query_selector_all(".op-bar .op-btn")
    picked = None
    for b in st:
        t = (b.inner_text() or "").strip()
        if t and not t.startswith("＋"):
            b.click()
            picked = t
            break
    pg.wait_for_timeout(400)
    check("会計担当をワンタップで選べる", picked is not None, picked)

    # 商品番号で追加
    pg.click('button:has-text("商品番号で追加")')
    pg.wait_for_selector("#prod-modal.show", timeout=8000)
    pg.fill("#pm-search", target[0])
    pg.wait_for_timeout(1200)
    pg.screenshot(path=SHOT + "/10_picker.png")
    # ★行をクリックしても入らない。行の「追加」ボタンを押す仕様
    add = pg.query_selector('#prod-modal tbody tr button')
    if add:
        add.click()
        pg.wait_for_timeout(800)
    # 「追加」を押すとモーダルは自動で閉じる。開いたままなら閉じる
    if pg.evaluate("() => document.getElementById('prod-modal').classList.contains('show')"):
        pg.click('#prod-modal button:has-text("閉じる")')
    pg.wait_for_selector("#prod-modal", state="hidden", timeout=8000)
    pg.wait_for_timeout(600)
    n_lines = pg.evaluate("() => document.querySelectorAll('#pos-lines tr').length")
    bill = pg.evaluate("() => (typeof BILL !== 'undefined') ? BILL : null")
    check("商品番号で明細に追加できる", n_lines >= 1 and (bill or 0) > 0,
          f"明細={n_lines}行 / 請求={bill}")

    # ★顧客は必須。カナで引いて候補の1件目を選ぶ
    pg.fill("#pos-cust-input", "ﾒｶﾞﾈ")
    pg.wait_for_timeout(1200)
    opt = pg.query_selector("#pos-cust-drop div, #pos-cust-drop li, #pos-cust-drop button")
    if opt:
        opt.click()
        pg.wait_for_timeout(700)
    linked = pg.evaluate("() => (document.getElementById('pos-cust-input')||{}).value || ''")
    check("顧客をカナで選べる", bool(linked.strip()), linked)

    # 支払(現金)に請求額を入れる
    pg.evaluate("""() => {
        var rows = document.querySelectorAll('#pay-rows input, .pay-row input');
        var inp = rows[rows.length - 1];
        if (inp) { inp.value = String(BILL); inp.dispatchEvent(new Event('input', {bubbles:true})); }
    }""")
    pg.wait_for_timeout(600)

    # ★お預かり(現金)を入れないと会計できない。これは正しい動きなので、
    #   まず「入れずに押すと止まること」を確かめてから、入れて通す。
    pg.click("#btn-checkout")
    pg.wait_for_timeout(1500)
    blocked = q("SELECT COUNT(*) FROM sales_slips") == before_slips
    msg = pg.evaluate("() => (document.body.innerText.match(/預り金額が不足[^\\n]*/)||[''])[0]")
    check("お預かりが足りないと会計できない(正しく止まる)", blocked and "不足" in msg, msg[:44])

    pg.fill("#deposit", "")
    pg.type("#deposit", str(bill))
    pg.wait_for_timeout(700)
    pg.screenshot(path=SHOT + "/11_pos.png")

    # 会計確定
    pg.click("#btn-checkout")
    pg.wait_for_timeout(3500)
    pg.screenshot(path=SHOT + "/12_after.png")

    after_slips = q("SELECT COUNT(*) FROM sales_slips")
    after_stock = q("SELECT COUNT(*) FROM products WHERE state='在庫'")
    check("会計で伝票が1件増える", after_slips == before_slips + 1,
          f"{before_slips} → {after_slips}")
    check("会計で在庫が1点減る", after_stock == before_stock - 1,
          f"{before_stock} → {after_stock}")

    slip_id = q("SELECT slip_id FROM sales_slips ORDER BY slip_id DESC LIMIT 1")
    amt = q("SELECT SUM(amount) FROM sale_lines WHERE slip_id=?", (slip_id,))
    check("明細の金額が入っている", (amt or 0) > 0, f"伝票{slip_id} / 合計{amt}")

    # 品名が顧客名になっていないか(v0.35.7の回帰確認)
    nm = q("""SELECT COALESCE(l.free_name, p.name) FROM sale_lines l
              LEFT JOIN products p ON p.product_key=l.product_key
              WHERE l.slip_id=? LIMIT 1""", (slip_id,))
    check("明細の品名が商品名になっている", nm == target[1], f"表示名={nm} / 期待={target[1]}")

    # ── 日報に出るか ──
    pg.click('.nav-item[data-screen="reports"]')
    pg.wait_for_timeout(2000)
    rep = pg.evaluate("() => document.body.innerText.indexOf('%s') >= 0" % target[1][:6])
    pg.screenshot(path=SHOT + "/13_report.png", full_page=True)
    check("日報にその会計が出る", rep, target[1][:6])

    # ── 取消(テストの後始末) ──
    voided = pg.evaluate("""async (sid) => {
        var r = await fetch('/api/void_slip', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({slip_id: sid, reason:'動作確認のテスト', operator:'admin', staff:'admin'})});
        return await r.json();
    }""", slip_id)
    pg.wait_for_timeout(1200)
    end_slips = q("SELECT COUNT(*) FROM sales_slips WHERE COALESCE(voided_at,'')=''") \
        if q("SELECT COUNT(*) FROM pragma_table_info('sales_slips') WHERE name='voided_at'") else None
    end_stock = q("SELECT COUNT(*) FROM products WHERE state='在庫'")
    check("取消で在庫が戻る", end_stock == before_stock, f"{after_stock} → {end_stock}")
    check("取消が受け付けられた", isinstance(voided, dict) and not voided.get("error"), voided)

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    br.close()

print("\n" + "=" * 56)
ng = [r for r in results if not r[1]]
print(f"  {len(results)}項目中 {len(results)-len(ng)}項目OK / NG {len(ng)}項目")
for n, _o, d in ng:
    print(f"    ★ {n}   {d}")
sys.exit(1 if ng else 0)
