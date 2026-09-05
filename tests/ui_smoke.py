# -*- coding: utf-8 -*-
"""画面の通し確認。v0.34.11〜v1.2.0 で入れた変更が生きているかを実ブラウザで見る。

  python3 server/app.py &          # 先にサーバーを起動しておく
  python3 tests/ui_smoke.py

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
    br = p.chromium.launch(executable_path=os.environ.get("CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"))
    pg = br.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))

    # ── ログイン ──
    pg.goto(BASE, wait_until="networkidle")
    pg.select_option("#uid", "admin")
    pg.fill("#pw", "tokiwa-test-1234")
    pg.click("#btn")
    pg.wait_for_selector("#app.active", timeout=20000)
    check("ログイン(パスワード未設定ユーザーの初回設定)", True)

    pg.wait_for_timeout(1500)
    pg.screenshot(path=SHOT + "/01_home.png")

    # ── v0.35.11 デモ注意書きが出ていない ──
    note = pg.evaluate("""() => {
        var e = document.getElementById('mock-note');
        if (!e) return {gone: true, text: ''};
        var st = getComputedStyle(e);
        return {gone: st.display === 'none', text: e.textContent.slice(0, 40)};
    }""")
    check("v0.35.11 デモデータの注意書きが出ない", note["gone"], note["text"])

    # ── バージョン表示 ──
    ver = pg.inner_text("#app-ver")
    check("バージョン表示が v1.4.11", ver.strip() == "v1.4.11", ver)

    # ── 顧客画面へ ──
    pg.click('.nav-item[data-screen="customers"]')
    pg.wait_for_timeout(1200)

    # ローマ字検索(v0.34.23の共通部品)
    # ★顧客管理は「検索するまで一覧を出さない」仕様。まずカナで引く
    pg.fill("#q-name", "ﾒｶﾞﾈ")
    pg.wait_for_timeout(900)
    n_kana = pg.evaluate("() => document.querySelectorAll('tr[data-cust]').length")
    pg.fill("#q-name", "megane")
    pg.wait_for_timeout(900)
    n_romaji = pg.evaluate("() => document.querySelectorAll('tr[data-cust]').length")
    check("ローマ字検索(megane)がカナ検索と同じ結果になる",
          n_romaji > 0 and n_romaji == n_kana, f"カナ={n_kana} / ローマ字={n_romaji}")
    pg.fill("#q-name", "ｺ")
    pg.wait_for_timeout(900)

    # ── 顧客詳細 ──
    # ★一覧は「行をダブルクリックで詳細」。チェックボックス列を避けて氏名の欄を叩く
    first = pg.query_selector("tr[data-cust] td:nth-child(2)")
    if first:
        first.dblclick()
        pg.wait_for_timeout(1800)
        pg.screenshot(path=SHOT + "/02_customer.png", full_page=True)
        info = pg.evaluate("""() => {
            var g = document.querySelectorAll('#screen-customers .kv4, .kv4');
            var addr = document.querySelectorAll('.kv-addr');
            var labels = [];
            if (g[0]) g[0].querySelectorAll('label').forEach(function(l){labels.push(l.textContent.trim());});
            var alabels = [];
            if (addr[0]) addr[0].querySelectorAll('label').forEach(function(l){alabels.push(l.textContent.trim());});
            var cols = g[0] ? getComputedStyle(g[0]).gridTemplateColumns.split(' ').length : 0;
            return {n_kv4: g.length, labels: labels, addr: alabels, cols: cols};
        }""")
        check("顧客詳細の基本情報が4列(.kv4)", info["cols"] == 4, f"{info['cols']}列")
        check("1段目の並び 名前/フリガナ/性別/生年月日",
              info["labels"][:4] == ["顧客名", "フリガナ", "性別", "生年月日"], info["labels"][:4])
        check("2段目の並び 電話/携帯/DM送付/登録日",
              info["labels"][4:8] == ["電話", "携帯電話", "DM送付", "登録日"], info["labels"][4:8])
        check("3段目が住所(郵便番号/住所1/住所2)",
              info["addr"][:1] == ["郵便番号"] and len(info["addr"]) == 3, info["addr"])

        # ★名前の横に年齢を出す(v1.4.1 店の指定)。基本情報の生年月日まで目を下ろさずに分かる
        agechip = pg.evaluate("""() => {
            var el = document.getElementById('cd-age');
            if (!el) return null;
            var c = findCust(window.__curCust);
            var st = getComputedStyle(el);
            return {text: el.textContent.trim(), shown: st.display !== 'none',
                    birth: c ? c[6] : null, age: c ? ageFrom(c[6]) : null,
                    // 名前と同じ行に並んでいるか(上下がずれていない)
                    sameRow: Math.abs(el.getBoundingClientRect().top
                             - document.getElementById('cd-name').getBoundingClientRect().top) < 30,
                    // ★値は <input value="…"> に入っているので textContent では取れない
                    birthRow: (function () {
                        var f = Array.from(document.querySelectorAll(
                                '[data-screen="customer-detail"] .kv4 .field'))
                            .find(function (x) {
                                return x.querySelector('label').textContent.trim() === '生年月日'; });
                        return f ? f.querySelector('input').value : '';
                    })()};
        }""")
        if agechip and agechip["age"] is not None:
            check("★名前の横に「〇〇歳」が出る",
                  agechip["shown"] and agechip["text"] == "%d歳" % agechip["age"], agechip)
            check("名前と同じ行に並んでいる", agechip["sameRow"], agechip["sameRow"])
            check("生年月日の欄はそのまま(年齢つき)",
                  "歳)" in agechip["birthRow"], agechip["birthRow"])
        elif agechip:
            check("生年月日が無い方には年齢を出さない",
                  not agechip["shown"] and agechip["text"] == "", agechip)
        else:
            check("名前の横の年齢", False, "cd-age の要素が見つかりません")

        # 顧客メモの枠(スクロール)。メモを持つ顧客でしか出ないので存在すれば見る
        memo = pg.evaluate("""() => {
            var t = Array.from(document.querySelectorAll('.section-title'))
                     .find(function(e){return e.textContent.indexOf('顧客メモ') === 0;});
            if (!t) return null;
            var box = t.nextElementSibling;
            var st = getComputedStyle(box);
            return {maxh: st.maxHeight, overflow: st.overflowY, border: st.borderTopWidth};
        }""")
        if memo:
            check("顧客メモが枠内スクロール(max-height+overflow+枠線)",
                  memo["overflow"] == "auto" and memo["maxh"] != "none" and memo["border"] != "0px", memo)
        else:
            check("顧客メモの枠", True, "このDBにメモ付き顧客がいないため確認できず(スキップ)")

        # 家族の追加モーダル(続柄の両方向)
        fam = pg.query_selector('button:has-text("＋ 家族を追加")')
        if fam:
            fam.click()
            pg.wait_for_timeout(800)
            rel = pg.evaluate("""() => {
                if (typeof reverseRelation !== 'function') return null;
                return {wife: reverseRelation('夫'), husband: reverseRelation('妻'),
                        son_m: reverseRelation('長男','男'), son_f: reverseRelation('長男','女'),
                        other: reverseRelation('友人')};
            }""")
            check("続柄の裏返し(夫→妻/妻→夫/長男→父or母/その他→家族)",
                  rel and rel["wife"] == "妻" and rel["husband"] == "夫"
                  and rel["son_m"] == "父" and rel["son_f"] == "母" and rel["other"] == "家族", rel)
            pg.screenshot(path=SHOT + "/03_family.png")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)
        else:
            check("家族モーダル", False, "「＋ 家族を追加」が見つからない")
    else:
        check("顧客詳細", False, "顧客行が見つからない")

    # ── メーカー(仕入先)の絞り込みが6か所に付いているか ──
    sel = pg.evaluate("""() => {
        var ids = ['np-supplier','pe-supplier','cs-supplier','sd-supplier','q-supplier','pm-supplier'];
        return ids.map(function(id){
            var e = document.getElementById(id);
            if (!e) return [id, 'なし'];
            var prev = e.previousElementSibling;
            var ok = e.getAttribute('data-filtered') === '1'
                     && prev && prev.classList.contains('sel-filter-wrap')
                     && prev.querySelector('input.sel-filter');
            return [id, ok ? 'あり' : 'ついていない'];
        });
    }""")
    check("メーカー絞り込みが6か所すべてに付いている",
          all(x[1] == "あり" for x in sel), sel)

    # ── 顧客変更(旧「付替」)のラベル ──
    lbl = pg.evaluate("""() => {
        var t = document.body.innerHTML;
        return {kokyaku: t.indexOf('顧客変更') >= 0, tsukekae: /[^:]付替/.test(t)};
    }""")
    check("ボタンのラベルが「顧客変更」(旧「付替」が残っていない)",
          lbl["kokyaku"] and not lbl["tsukekae"], lbl)

    # ── 重複チェックの比較表が一覧より上にあるか ──
    dup = pg.evaluate("""() => {
        var c = document.getElementById('dup-compare'), l = document.getElementById('dup-list');
        if (!c || !l) return null;
        return (c.compareDocumentPosition(l) & Node.DOCUMENT_POSITION_FOLLOWING) ? 'compareが先' : 'listが先';
    }""")
    check("重複チェックの比較表が一覧より上にある", dup == "compareが先", dup)

    # ── トースト: ⚠ は自動で消えない / 通常は消える ──
    shown = "() => { var t=document.getElementById('toast'); return !!t && t.classList.contains('show'); }"
    err_cls = "() => { var t=document.getElementById('toast'); return !!t && t.classList.contains('toast-error'); }"
    pg.evaluate("() => showToast('⚠ テスト用の警告です')")
    pg.wait_for_timeout(300)
    warn_now = pg.evaluate(shown)
    warn_red = pg.evaluate(err_cls)
    pg.wait_for_timeout(7000)
    warn_after = pg.evaluate(shown)
    check("⚠のお知らせは自動で消えない(赤で表示)", warn_now and warn_red and warn_after,
          f"直後={warn_now} 赤={warn_red} / 7秒後={warn_after}")
    pg.evaluate("() => showToast('通常のお知らせ')")
    pg.wait_for_timeout(300)
    ok_now = pg.evaluate(shown)
    pg.wait_for_timeout(7000)
    ok_after = pg.evaluate(shown)
    check("通常のお知らせは自動で消える", ok_now and not ok_after, f"直後={ok_now} / 7秒後={ok_after}")

    # ── ユーザー管理の並べ替え ▲▼ ──
    has_move = pg.evaluate("() => typeof moveAppUser === 'function'")
    check("ログインユーザーの並べ替え(moveAppUser)がある", has_move)

    # ── 動作ログ(設定→レシート・機器) ──
    log = pg.evaluate("""async () => {
        var r = await fetch('/api/app_log');
        var j = await r.json();
        return Array.isArray(j.lines) ? j.lines.length : (j.error || 'ok');
    }""")
    check("動作ログAPIが応答する", isinstance(log, int) or log == "ok", log)

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    pg.screenshot(path=SHOT + "/04_last.png")
    br.close()

print("\n" + "=" * 56)
ng = [r for r in results if not r[1]]
print(f"  {len(results)}項目中 {len(results) - len(ng)}項目OK / NG {len(ng)}項目")
for n, _o, d in ng:
    print(f"    ★ {n}   {d}")
sys.exit(1 if ng else 0)
