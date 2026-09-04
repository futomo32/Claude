# -*- coding: utf-8 -*-
"""v1.0.1〜v1.0.9 で入れた画面の変更を、実ブラウザで確かめる。

  python3 server/app.py &
  python3 tests/ui_smoke_v11.py

★実ブラウザで動かす確認(動作確認モード用)。蓄積モードでは実行しない。
  管理者ユーザー admin のパスワードをテスト用に設定するので、**本番機では実行しないこと**。
  画面の写真は logs/shots/ に残る(.gitignore 済み)。
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8760"
SHOT = "logs/shots"
os.makedirs(SHOT, exist_ok=True)
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  OK  " if ok else "★NG  ") + name + (("   … " + str(detail)) if detail else ""))


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
    check("バージョン表示が v1.3.5", pg.inner_text("#app-ver").strip() == "v1.3.5",
          pg.inner_text("#app-ver").strip())

    pg.click('.nav-item[data-screen="register"]')
    pg.wait_for_timeout(1200)

    # 会計担当を1人選ぶ
    for b in pg.query_selector_all(".op-bar .op-btn"):
        t = (b.inner_text() or "").strip()
        if t and not t.startswith("＋"):
            b.click()
            break
    pg.wait_for_timeout(300)

    # ★お預かり欄は「現金の支払行がある時」だけ出るので、先に明細を1つ入れる
    pg.click('button:has-text("商品番号で追加")')
    pg.wait_for_selector("#prod-modal.show", timeout=8000)
    pg.fill("#pm-search", "1001")
    pg.wait_for_timeout(1000)
    add = pg.query_selector("#prod-modal tbody tr button")
    if add:
        add.click()
        pg.wait_for_timeout(700)
    if pg.evaluate("() => document.getElementById('prod-modal').classList.contains('show')"):
        pg.click('#prod-modal button:has-text("閉じる")')
    pg.wait_for_selector("#prod-modal", state="hidden", timeout=8000)
    pg.wait_for_timeout(600)
    check("明細を1行入れられた", pg.evaluate("() => posLines.length") >= 1)

    # ── v1.0.6/v1.0.9 金額欄のカンマとカーソル(実際にキーを打つ)──
    pg.click("#deposit")
    pg.keyboard.press("Control+a")
    pg.keyboard.type("7500")
    v1 = pg.eval_on_selector("#deposit", "e => [e.value, e.selectionStart]")
    pg.keyboard.type("0")
    v2 = pg.eval_on_selector("#deposit", "e => [e.value, e.selectionStart]")
    check("お預かり: 7500 と打つと 7,500", v1[0] == "7,500", v1)
    check("★お預かり: 続けて0を打つと 75,000 でカーソルは末尾",
          v2[0] == "75,000" and v2[1] == 6, v2)
    # 途中の桁を直せるか(先頭の7の後ろに8を入れる)
    pg.eval_on_selector("#deposit", "e => e.setSelectionRange(1,1)")
    pg.keyboard.type("8")
    v3 = pg.eval_on_selector("#deposit", "e => [e.value, e.selectionStart]")
    check("★お預かり: 途中に入れてもカーソルがその場に残る",
          v3[0] == "785,000" and v3[1] == 2, v3)
    pg.click("#deposit")
    pg.keyboard.press("Control+a")
    pg.keyboard.type("50000")

    # ── v1.0.3 IMEで変換中は触らない ──
    ime = pg.evaluate("""() => {
        var el = document.getElementById('pos-cust-input');
        el.focus(); el.value = '';
        el.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}));
        el.value = 'yanase';                     // 未確定のローマ字
        el.dispatchEvent(new InputEvent('input', {bubbles:true, isComposing:true}));
        var during = el.value;
        el.value = 'やなせ';                      // 変換が確定した
        el.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true, data:'やなせ'}));
        var after = el.value;
        el.value = '';
        return {during: during, after: after};
    }""")
    check("★変換中は入力欄に手を出さない", ime["during"] == "yanase", ime)

    # かな欄は確定時にカタカナへ直る
    kana = pg.evaluate("""() => {
        var el = document.getElementById('cm-kana');
        if (!el) return null;
        el.value = 'やなせ';
        el.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}));
        el.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true}));
        var v = el.value; el.value = ''; return v;
    }""")
    check("フリガナ欄は確定時にカタカナへ直る", kana == "ヤナセ", kana)

    # ── v1.0.9 ボタンの配置 ──
    btns = pg.evaluate("""() => {
        var wide = document.querySelector('.tenkey .wide');
        var clear = Array.from(document.querySelectorAll('button'))
                     .find(function(b){ return b.textContent.indexOf('明細クリア') >= 0; });
        var cash = Array.from(document.querySelectorAll('button'))
                     .find(function(b){ return b.textContent.indexOf('レジ入出金') >= 0; });
        return {wideText: wide && wide.textContent.trim(),
                wideOnclick: wide && wide.getAttribute('onclick'),
                clearNextToCash: !!(clear && cash && cash.nextElementSibling === clear)};
    }""")
    check("テンキーの広いボタンは数字クリア",
          btns["wideText"] == "クリア" and "keyClear" in (btns["wideOnclick"] or ""), btns)
    check("明細クリアがレジ入出金の隣にある", btns["clearNextToCash"], btns)

    # ── v1.0.5 レシートへのポイント印字 ──
    st = pg.query_selector_all(".op-bar .op-btn")
    for b in st:
        t = (b.inner_text() or "").strip()
        if t and not t.startswith("＋"):
            b.click()
            break
    pg.wait_for_timeout(300)
    pt = pg.evaluate("""() => {
        var cb = document.getElementById('pos-print-points');
        var out = {def: cb.checked};
        setCardHeld('1', 'テスト 様');            // カードを保持した状態
        out.onCard = cb.checked;
        setCardHeld(null);                        // 排出
        out.offEject = cb.checked;
        cb.checked = true; markPointPrintTouched();   // 手で入れた
        setCardHeld(null);                        // カードを抜いても
        out.keepManual = cb.checked;              // 手の設定が残る
        var note = document.getElementById('pos-print-points-note').textContent;
        cb.checked = false;
        return Object.assign(out, {note: note});
    }""")
    check("ポイント印字: 既定はOFF", pt["def"] is False, pt["def"])
    check("ポイント印字: カード保持で自動ON", pt["onCard"] is True, pt["onCard"])
    check("ポイント印字: カード排出で自動OFF", pt["offEject"] is False, pt["offEject"])
    check("★手で入れた設定はカードで上書きされない", pt["keepManual"] is True, pt["note"])

    # ── v1.0.1 ドロワー(機器OFFなので呼ばないこと) ──
    dr = pg.evaluate("""() => {
        var calls = 0, of = window.fetch;
        window.fetch = function(u){ if (String(u).indexOf('/drawer_open') >= 0) calls++;
                                    return of.apply(this, arguments); };
        kickDrawer();
        window.fetch = of;
        return {calls: calls, hw: !!(window.TOKIWA_DATA && TOKIWA_DATA.hardwareMode)};
    }""")
    check("機器OFFではドロワーを叩かない", dr["calls"] == 0 and dr["hw"] is False, dr)

    # ── v1.0.7 商品情報が明細で打てる ──
    pg.click('button:has-text("番号なしで追加")')
    pg.wait_for_timeout(800)
    free = pg.query_selector('#free-modal button')
    if free:
        free.click()
        pg.wait_for_timeout(800)
    if pg.evaluate("() => document.getElementById('free-modal').classList.contains('show')"):
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
    info = pg.evaluate("""() => {
        var rows = document.querySelectorAll('#pos-lines tr');
        if (!rows.length) return {rows: 0};
        var inp = rows[0].querySelectorAll('td')[2].querySelector('input');
        if (!inp) return {rows: rows.length, hasInput: false};
        inp.value = 'SR626SW';
        inp.dispatchEvent(new Event('input', {bubbles:true}));
        return {rows: rows.length, hasInput: true, saved: (posLines[0] || {}).info};
    }""")
    check("明細の商品情報が打てて、明細に残る",
          info.get("hasInput") and info.get("saved") == "SR626SW", info)

    # ── v1.0.8/1.0.9 明細クリア ──
    n_before = pg.evaluate("() => posLines.length")
    pg.click('button:has-text("明細クリア")')
    pg.wait_for_timeout(600)
    pg.screenshot(path=SHOT + "/20_clear_confirm.png")
    dlg = pg.evaluate("""() => {
        var m = document.getElementById('alert-modal');
        return {shown: m.classList.contains('show'),
                title: document.getElementById('al-title-text').textContent,
                ok: document.getElementById('al-ok').textContent,
                lines: posLines.length};
    }""")
    check("明細クリア: 確認が出て、押すまでは消えない",
          dlg["shown"] and dlg["lines"] == n_before and "消す" in dlg["ok"], dlg)
    pg.click("#al-ok")
    pg.wait_for_timeout(600)
    after = pg.evaluate("""() => ({lines: posLines.length,
        pay: payRows.length, dep: document.getElementById('deposit').value,
        cust: !!posCustomer, staff: !!posOperator})""")
    check("明細クリア: 明細と支払とお預かりが戻る",
          after["lines"] == 0 and after["pay"] == 1 and after["dep"] == "0", after)
    check("明細クリア: 会計担当は残る", after["staff"] is True, after)

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    pg.screenshot(path=SHOT + "/21_after_clear.png")
    br.close()

print("\n" + "=" * 56)
ng = [r for r in results if not r[1]]
print(f"  {len(results)}項目中 {len(results)-len(ng)}項目OK / NG {len(ng)}項目")
for n, _o, d in ng:
    print(f"    ★ {n}   {d}")
sys.exit(1 if ng else 0)
