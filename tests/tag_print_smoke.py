# -*- coding: utf-8 -*-
"""在庫品の値札(タグ)印刷(v1.4.2)を実ブラウザで確かめる。

  python3 server/app.py &
  python3 tests/tag_print_smoke.py

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
SLIP = "TEST-TAG-9001"      # この伝票番号で入れた商品をあとでまとめて消す
PER_SHEET = 12              # 台紙1枚の面数(3列×4行)


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  OK  " if ok else "★NG  ") + name + (("   … " + str(detail)) if detail else ""))


def cleanup():
    c = sqlite3.connect(DB)
    n = c.execute("DELETE FROM products WHERE purchase_slip_no=?", (SLIP,)).rowcount
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

    # ── ① テスト商品を3件作る(自動採番は5桁なのでバーコードが作れる番号になる)──
    made = pg.evaluate("""async (slip) => {
        var out = [];
        for (var i = 1; i <= 3; i++) {
            var r = await fetch('/api/product', {method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({name:'ﾃｽﾄ 値札' + i, category:'その他',
                    cost_price: 1000 * i, list_price: 3000 * i,
                    tag_name:'ﾀｸﾞ品名' + i, maker_no:'MK-' + i, purchase_slip_no: slip})});
            out.push(await r.json());
        }
        return out.map(x => (x.products || [{}])[0]);
    }""", SLIP)
    nos = [m.get("product_no") for m in made]
    check("テスト商品を3件作れた", len(nos) == 3 and all(nos), nos)

    # ── ② 在庫一覧にチェック欄がある ──
    pg.click('.nav-item[data-screen="products"]')
    pg.wait_for_timeout(1200)
    pg.click('[data-tabgroup="prod"] [data-tab="p-stock"]')
    pg.wait_for_timeout(600)
    pg.fill("#q-prod", SLIP)
    pg.select_option("#q-state", "")
    pg.evaluate("() => renderProducts()")
    pg.wait_for_timeout(1800)
    cols = pg.evaluate("""() => ({
        heads: document.querySelectorAll('#stock-thead th').length,
        cells: document.querySelectorAll('#stock-tbody tr:first-child td').length,
        firstIsCheck: !!document.querySelector('#stock-tbody tr:first-child td input[type=checkbox]'),
        selAll: !!document.getElementById('stock-sel-all'),
        total: prodTotal})""")
    check("在庫一覧の3件が出る", cols["total"] == 3, cols["total"])
    check("チェック欄が付いた(見出しとセルの数が合う)",
          cols["heads"] == cols["cells"] == 11 and cols["firstIsCheck"] and cols["selAll"], cols)

    # ── ③ 選択の帯 ──
    sel = pg.evaluate("""async () => {
        stockSelectAll(true);
        await new Promise(r => setTimeout(r, 300));
        var d = {n: stockSelected.size,
                 label: document.getElementById('stock-sel-count').textContent,
                 btn: document.getElementById('stock-tag-btn').style.display !== 'none',
                 headChecked: document.getElementById('stock-sel-all').checked};
        stockClearSelection();
        await new Promise(r => setTimeout(r, 300));
        d.after = stockSelected.size;
        d.btnAfter = document.getElementById('stock-tag-btn').style.display !== 'none';
        stockSelectAll(true);
        await new Promise(r => setTimeout(r, 300));
        return d;
    }""")
    check("★「表示中をすべて選択」で3件選べる",
          sel["n"] == 3 and "選択中 3件" in sel["label"], sel)
    check("値札の印刷ボタンは選択がある時だけ出る", sel["btn"] and not sel["btnAfter"], sel)
    check("見出しのチェックも入る", sel["headChecked"], sel["headChecked"])

    # ── ④ 値札印刷のモーダル(枚数の計算)──
    plan = pg.evaluate("""async () => {
        openTagPrint();
        for (var i = 0; i < 40 && !tagPrintItems.length; i++) await new Promise(r => setTimeout(r, 150));
        var d = {open: document.getElementById('tagprint-modal').classList.contains('show'),
                 items: tagPrintItems.length,
                 summary: document.getElementById('tp-summary').textContent,
                 plan1: document.getElementById('tp-plan').textContent,
                 warn1: document.getElementById('tp-warn').style.display !== 'none'};
        document.getElementById('tp-start').value = '11';   // 使いかけの台紙(11面目から)
        paintTagPrintPlan();
        await new Promise(r => setTimeout(r, 200));
        d.plan11 = document.getElementById('tp-plan').textContent;
        return d;
    }""")
    check("値札印刷のモーダルが開き、選んだ3件を読み込む",
          plan["open"] and plan["items"] == 3 and "3件" in plan["summary"], plan)
    check("1面目からなら台紙1枚・3面目まで",
          "台紙 1枚" in plan["plan1"] and "3面目" in plan["plan1"], plan["plan1"])
    check("★11面目からなら台紙2枚になり、1〜10面目は空ける",
          "台紙 2枚" in plan["plan11"] and "1〜10面目は空けます" in plan["plan11"], plan["plan11"])
    check("バーコードを刷れない商品の警告は出ない(5桁の自動採番なので作れる)",
          not plan["warn1"], plan["warn1"])

    # ── ⑤ 印刷プレビューの中身 ──
    prev = pg.evaluate("""async () => {
        document.getElementById('tp-start').value = '11';
        paintTagPrintPlan();
        doTagPrint();
        await new Promise(r => setTimeout(r, 600));
        var box = document.getElementById('print-preview-content');
        var cells = box.querySelectorAll('.tag-cell');
        var blanks = 0;
        for (var i = 0; i < cells.length; i++) if (!cells[i].innerHTML.trim()) blanks++;
        return {shown: document.getElementById('print-preview').classList.contains('show'),
                sheets: box.querySelectorAll('.tag-sheet').length,
                cells: cells.length,
                blanks: blanks,
                barcodes: box.querySelectorAll('svg.tg-bc').length,
                firstTenBlank: Array.from(cells).slice(0, 10)
                    .every(function (c) { return !c.innerHTML.trim(); }),
                breaks: box.querySelectorAll('[style*="page-break-before"]').length,
                modalClosed: !document.getElementById('tagprint-modal').classList.contains('show'),
                texts: Array.from(box.querySelectorAll('.tg-price')).map(e => e.textContent)};
    }""")
    check("印刷プレビューが出て、モーダルは閉じる", prev["shown"] and prev["modalClosed"], prev)
    check("★台紙2枚ぶん(12面×2=24面)が組まれる",
          prev["sheets"] == 2 and prev["cells"] == 24, prev)
    check("★1〜10面目が空で、商品は11面目から入る",
          prev["firstTenBlank"] and prev["blanks"] == 21, prev)   # 24面 - 商品3面
    check("★バーコードが3枚ぶん出る", prev["barcodes"] == 3, prev["barcodes"])
    check("2枚目に改ページが入る(1枚に重ならない)", prev["breaks"] == 1, prev["breaks"])
    check("表に価格が入る", prev["texts"][:3] == ["¥3,000", "¥6,000", "¥9,000"], prev["texts"][:3])
    pg.screenshot(path=SHOT + "/41_tag_print_preview.png")
    pg.evaluate("() => cancelPrint()")
    pg.wait_for_timeout(300)

    # ── ⑥ バーコードを作れない番号は刷らない(警告を出す)──
    bad = pg.evaluate("""() => ({
        five: tagBarcode12('22001'), navi: tagBarcode12('17543-1-01-20-130'),
        short: tagBarcode12('1001'), letters: tagBarcode12('R-5000'), empty: tagBarcode12('')})""")
    check("★5桁の番号はバーコードにできる", bad["five"] == "220010000000", bad["five"])
    check("★宝飾ナビの管理番号もバーコードにできる", bad["navi"] == "175431012000", bad["navi"])
    check("★レジで引き当たらない番号にはバーコードを作らない",
          bad["short"] is None and bad["letters"] is None and bad["empty"] is None, bad)

    # ── ⑦ 仕入登録の直後、その商品が選ばれている ──
    reg = pg.evaluate("""async (slip) => {
        stockClearSelection();
        document.querySelector('[data-tabgroup="prod"] [data-tab="p-purchase"]').click();
        await new Promise(r => setTimeout(r, 600));
        document.getElementById('np-name').value = 'ﾃｽﾄ 値札 登録直後';
        document.getElementById('np-slip-no').value = slip;
        document.getElementById('np-list').value = '4500';
        var btn = Array.from(document.querySelectorAll('#p-purchase button'))
            .find(function (b) { return b.textContent.indexOf('登録する') >= 0; });
        saveProduct(btn);
        await new Promise(r => setTimeout(r, 2500));
        return {sel: stockSelected.size,
                btn: document.getElementById('stock-tag-btn').style.display !== 'none',
                onStock: document.querySelector('[data-tabgroup="prod"] [data-tab="p-stock"]')
                    .classList.contains('active')};
    }""", SLIP)
    check("★仕入登録すると在庫一覧に移り、その商品が選ばれている",
          reg["sel"] == 1 and reg["btn"] and reg["onStock"], reg)

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    br.close()

removed = cleanup()
check("片付け完了(テスト商品を削除)", removed == 4, "%d件削除" % removed)

ng = [r for r in results if not r[1]]
print("\n" + "=" * 56)
print("  %d項目中 %d項目OK / NG %d項目" % (len(results), len(results) - len(ng), len(ng)))
for n, _, d in ng:
    print("    ★ " + n + ("   " + str(d) if d else ""))
sys.exit(1 if ng else 0)
