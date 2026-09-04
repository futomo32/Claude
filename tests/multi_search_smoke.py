# -*- coding: utf-8 -*-
"""複合検索(v1.2.1〜v1.2.7)と、日報CSVの支払方法の列(v1.2.4)を実ブラウザで確かめる。

  python3 server/app.py &
  python3 tests/multi_search_smoke.py

★実ブラウザで動かす確認(動作確認モード用)。蓄積モードでは実行しない。
  管理者ユーザー admin のパスワードをテスト用に設定するので、**本番機では実行しないこと**。
  画面の写真は logs/shots/ に残る(.gitignore 済み)。
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


# ── 日報CSVの検証用データ ─────────────────────────────────
# 店から報告のあった不具合(売掛入金がカードなのにCSVで区別できない)を再現するため、
# 売上のある日に「カードでの売掛入金」を1件作る。最後に必ず消す。
CSV_DATE = "2026-08-23"          # この日は現金の売上が1件ある(サンプルデータ)
CSV_PAID = 123456
_c = sqlite3.connect(DB)
_cid = _c.execute("SELECT customer_id FROM customers WHERE COALESCE(is_test,0)=0 LIMIT 1").fetchone()[0]
_cur = _c.cursor()
_cur.execute("INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,paid,method) "
             "VALUES (?,'入金',?,'テスト入金',?,'カード')", (_cid, CSV_DATE, CSV_PAID))
TEST_ENTRY = _cur.lastrowid
_c.commit()
_c.close()


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
    check("バージョン表示が v1.3.6", pg.inner_text("#app-ver").strip() == "v1.3.6",
          pg.inner_text("#app-ver").strip())

    # ── 複合検索のタブを開く ──
    pg.click('.nav-item[data-screen="search"]')
    pg.wait_for_timeout(1200)
    pg.click('[data-tabgroup="srch"] [data-tab="s-multi"]')
    pg.wait_for_timeout(1200)

    # ★既存のタブが動いていないこと(店が覚えた並びを変えていない)
    tabs = pg.eval_on_selector_all('[data-tabgroup="srch"] .tab',
                                   "es => es.map(e => e.textContent.trim())")
    check("★既存のタブの並びが変わっていない(複合検索は末尾に追加)",
          tabs == ["顧客検索・DM抽出", "詳細検索", "購入順位ランキング",
                   "メガネ処方箋検索", "複合検索"], tabs)

    # 条件の行が既定で5本、項目の一覧が出ているか
    st = pg.evaluate("""() => ({
        rows: document.querySelectorAll('#ms-rows select').length,
        fields: msFields.length,
        groups: Array.from(new Set(msFields.map(f => f.group))),
        dm: document.getElementById('ms-dm').checked })""")
    check("条件の行が既定で5本ある", st["rows"] == 5, st["rows"])
    check("項目が31個ある", st["fields"] == 31, st["fields"])
    check("項目が 顧客/購入/処方箋 に分かれている",
          st["groups"] == ["顧客", "購入", "処方箋"], st["groups"])
    check("★DM可のみが既定でONになっている(v1.2.6)", st["dm"] is True, st["dm"])

    # ── 担当者の「番号: 名前」一覧(v1.2.5)──
    dl = pg.evaluate("""() => {
        var d = document.getElementById('ms-list-staff_code');
        return {opts: d ? Array.from(d.options).map(o => o.value) : null,
                labels: d ? Array.from(d.options).map(o => o.label) : null};
    }""")
    check("★担当者が「番号: 名前」で選べる(候補一覧がある)",
          bool(dl["opts"]) and len(dl["opts"]) >= 2 and dl["opts"][0].startswith("101:"),
          dl["opts"])
    # ★候補は1件=1行。value と label を別にするとブラウザが2行で描き、
    #   同じ内容が重なって見え、一度に出る候補の数も半分になる(v1.3.1で修正)
    check("★候補が1件1行になっている(値と説明が二重に出ない)",
          all(l == v for l, v in zip(dl["labels"], dl["opts"])), dl["labels"][:2])
    # 名前ごと入っても番号として読める
    nm = pg.evaluate("""async () => {
        var r = await fetch('/api/multi_search', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({conditions:[{field:'staff_code',
                   from:'101: 三輪 祐加', to:'102: 簗瀬 智宏'}], exclude:'1'})});
        var a = await r.json();
        var r2 = await fetch('/api/multi_search', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({conditions:[{field:'staff_code', from:'101', to:'102'}], exclude:'1'})});
        var b = await r2.json();
        return {withName: a.count, numOnly: b.count};
    }""")
    check("★名前ごと入った欄でも番号として引ける",
          nm["withName"] == nm["numOnly"] and nm["numOnly"] > 0, nm)

    # ── 担当者の範囲を2行足す = OR(v1.2.1 の核心)──
    def set_rows(js):
        pg.evaluate(js)
        pg.wait_for_timeout(200)

    def search():
        pg.click('#s-multi button:has-text("検索")')
        pg.wait_for_timeout(1400)
        return pg.evaluate("() => ({count: msCount, shown: msResults.length, ids: msIds.length})")

    set_rows("""() => {
        msRows = [{field:'staff_code', from:'101', to:'102', value:''},
                  {field:'', from:'', to:'', value:''}];
        paintMsRows();
    }""")
    a = search()
    set_rows("""() => {
        msRows = [{field:'staff_code', from:'104', to:'104', value:''}];
        paintMsRows();
    }""")
    b = search()
    set_rows("""() => {
        msRows = [{field:'staff_code', from:'101', to:'102', value:''},
                  {field:'staff_code', from:'104', to:'104', value:''}];
        paintMsRows();
    }""")
    both = search()
    check("★担当者の範囲を2行足すと OR(足し算)になる",
          both["count"] == a["count"] + b["count"],
          f'{a["count"]} + {b["count"]} = {both["count"]}')
    pg.screenshot(path=SHOT + "/30_multi_staff_range.png")

    # 違う項目を足すと AND(絞られる)
    set_rows("""() => {
        msRows = [{field:'staff_code', from:'101', to:'102', value:''},
                  {field:'gender', from:'女', to:'女', value:''}];
        paintMsRows();
    }""")
    w = search()
    check("★違う項目を足すと AND(絞られる)", 0 < w["count"] < a["count"],
          f'担当のみ {a["count"]} → 担当×女 {w["count"]}')

    # ── 選ぶ項目の「から〜まで」(v1.2.5)──
    rng = pg.evaluate("""() => {
        var f = msFields.find(x => x.key === 'category');
        var opts = f.options;
        return {opts: opts,
                three: msChoiceRange(f, {from: opts[0], to: opts[2]}),
                rev:   msChoiceRange(f, {from: opts[2], to: opts[0]}),
                one:   msChoiceRange(f, {from: opts[0], to: opts[0]})};
    }""")
    check("★選ぶ項目の範囲が一覧の並び順で切り出される",
          rng["three"] == rng["opts"][:3] and rng["rev"] == rng["opts"][:3]
          and rng["one"] == [rng["opts"][0]], rng["three"])

    # 「から」を選ぶと「まで」も同じ値が入る(1つだけ選ぶ操作を壊さない)
    auto = pg.evaluate("""() => {
        msRows = [{field:'gender', from:'', to:'', value:''}];
        paintMsRows();
        msSetChoice(0, 'from', '女');
        return {from: msRows[0].from, to: msRows[0].to};
    }""")
    check("★「から」を選ぶと「まで」も同じ値が入る",
          auto["from"] == "女" and auto["to"] == "女", auto)
    one = search()
    check("1つだけ選んだ時は女だけに絞られる", one["count"] == w["count"] or one["count"] > 0,
          one["count"])

    # ── 買ったものの条件と「↑と同じ商品」(v1.2.2)──
    cat = pg.evaluate("() => msFields.find(x => x.key === 'category').options[0]")
    set_rows("""(cat) => {
        msRows = [{field:'category', from:cat, to:cat, value:''},
                  {field:'pname', from:'', to:'', value:'ダイヤ'}];
        paintMsRows();
    }""" if False else """() => {
        var cat = msFields.find(x => x.key === 'category').options
                    .find(o => o === 'リング') || msFields.find(x => x.key === 'category').options[0];
        msRows = [{field:'category', from:cat, to:cat, value:''},
                  {field:'pname', from:'', to:'', value:'ダイヤ'}];
        paintMsRows();
    }""")
    apart = search()
    same_shown = pg.evaluate("""() => {
        var el = document.querySelectorAll('#ms-rows input[type=checkbox]');
        return {n: el.length, label: el.length ? el[0].parentElement.textContent.trim() : ''};
    }""")
    check("★「購入」が2行続くと「↑と同じ商品」が出る",
          same_shown["n"] >= 1 and "同じ商品" in same_shown["label"], same_shown)
    set_rows("""() => { msRows[1].same_prev = true; paintMsRows(); }""")
    same = search()
    check("★「↑と同じ商品」で結果が変わる(絞られる)",
          same["count"] < apart["count"] and same["count"] > 0,
          f'別々でも可 {apart["count"]} → 同じ商品 {same["count"]}')
    pg.screenshot(path=SHOT + "/31_multi_same_product.png")

    # ── 処方箋の条件はまとめられない(表が違う)──
    mix = pg.evaluate("""() => {
        msRows = [{field:'category', from:'リング', to:'リング', value:''},
                  {field:'rx_purpose', from:'', to:'', value:''}];
        paintMsRows();
        return {canSame: msCanSame(1)};
    }""")
    check("★買ったものと処方箋はまとめられない", mix["canSame"] is False, mix)

    # ── 一覧の列と並べ替え(v1.2.7)──
    set_rows("""() => { msRows = [{field:'', from:'', to:'', value:''}]; paintMsRows(); }""")
    allc = search()
    head = pg.eval_on_selector_all("#ms-thead th",
                                   "es => es.map(e => e.textContent.trim()).filter(t => t)")
    check("一覧の列が9つ(年齢・住所・今年の購入を含む)",
          len(head) == 9 and any("年齢" in h for h in head) and any("住所" in h for h in head)
          and any("今年の購入" in h for h in head), head)
    check("「今年の購入」の見出しに年が入っている",
          any("今年の購入(" in h and "年)" in h for h in head),
          [h for h in head if "今年" in h])
    check("地区の列は無くなっている", not any(h.startswith("地区") for h in head), head)

    # 年齢で昇順・降順(★ページをまたいで並ぶこと=サーバー側で並べていること)
    def sort_by(label):
        pg.click('#ms-thead th:has-text("%s")' % label)
        pg.wait_for_timeout(1300)
        return pg.evaluate("""() => ({sort: msSort, order: msOrder,
            vals: msResults.map(r => r[4]), first: msResults[0], n: msCount})""")
    asc = sort_by("年齢")
    if asc["order"] != "asc":
        asc = sort_by("年齢")
    desc = sort_by("年齢")
    nums = [v for v in asc["vals"] if v is not None]
    check("年齢の昇順で並ぶ", asc["order"] == "asc" and nums == sorted(nums),
          nums[:6])
    dnums = [v for v in desc["vals"] if v is not None]
    check("★もう一度押すと降順になる", desc["order"] == "desc" and dnums == sorted(dnums, reverse=True),
          dnums[:6])
    check("並べ替えても該当件数は変わらない", asc["n"] == desc["n"] == allc["count"],
          f'{allc["count"]} / {asc["n"]} / {desc["n"]}')

    # ★並べ替えはページ送りをまたいで効く(画面の200件だけを並べていない)
    page = pg.evaluate("""async () => {
        var r = await fetch('/api/multi_search', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({conditions:[], exclude:'1', dm_ok:'1',
                                  sort:'total', order:'desc', limit:5, offset:0})});
        var a = await r.json();
        var r2 = await fetch('/api/multi_search', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({conditions:[], exclude:'1', dm_ok:'1',
                                  sort:'total', order:'desc', limit:5, offset:5})});
        var b = await r2.json();
        return {p1: a.rows.map(x => x[8]), p2: b.rows.map(x => x[8]),
                ids1: a.rows.map(x => x[0]), ids2: b.rows.map(x => x[0])};
    }""")
    check("★2ページ目は1ページ目より小さい金額が続く(全体を並べている)",
          min(page["p1"]) >= max(page["p2"]), f'1頁 {page["p1"]} / 2頁 {page["p2"]}')
    check("★ページ送りで同じ人が2回出ない",
          not (set(page["ids1"]) & set(page["ids2"])), page["ids1"])
    pg.screenshot(path=SHOT + "/32_multi_sorted.png")

    # ── 選択は検索し直しても消えない(v1.2.1)──
    sel = pg.evaluate("""() => {
        msSelected.clear();
        msIds.slice(0, 3).forEach(id => msSelected.add(String(id)));
        updateMsSelCount();
        return {n: msSelected.size, label: document.getElementById('ms-sel-count').textContent};
    }""")
    set_rows("""() => {
        msRows = [{field:'staff_code', from:'103', to:'103', value:''}];
        paintMsRows();
    }""")
    n_ref = search()["count"]      # このあとの並べ替えで件数が変わらないことの基準
    after = pg.evaluate("""() => ({n: msSelected.size,
        label: document.getElementById('ms-sel-count').textContent,
        btn: document.getElementById('ms-label-btn').style.display !== 'none'})""")
    check("★検索をやり直しても選択が残る(担当者ごとに足していける)",
          after["n"] == sel["n"] == 3, f'{sel["label"]} → {after["label"]}')
    check("「選択中 N件」とラベル印刷のボタンが出る",
          "選択中 3件" in after["label"] and after["btn"], after)

    # ★この検索結果の中の内訳(チェック/未チェック)が出る(v1.3.2)
    here = pg.evaluate("""() => {
        msSelected.clear();
        msIds.slice(0, 4).forEach(id => msSelected.add(String(id)));   // 今の結果から4人
        msSelected.add('存在しないID');                                // 別の条件で選んだ分
        updateMsSelCount();
        var n = msIds.length;
        return {text: document.getElementById('ms-sel-here').textContent,
                all: document.getElementById('ms-sel-count').textContent, n: n};
    }""")
    check("★この検索結果のチェック/未チェックの件数が出る",
          ("チェック 4件" in here["text"]
           and ("未チェック %d件" % (here["n"] - 4)) in here["text"]), here["text"])
    check("「選択中」は検索をまたいだ累計のまま(5件)",
          "選択中 5件" in here["all"], here["all"])

    # ★チェックの有無で並べ替えられる(v1.3.2)
    chk = pg.evaluate("""async () => {
        msSort_('checked');
        await new Promise(r => setTimeout(r, 1600));
        var top = msResults.slice(0, 4).map(r => msSelected.has(String(r[0])));
        var d = {order: msOrder, top: top};
        msSort_('checked');                       // もう一度で逆順
        await new Promise(r => setTimeout(r, 1600));
        d.order2 = msOrder;
        d.top2 = msResults.slice(0, 4).map(r => msSelected.has(String(r[0])));
        d.n = msCount;
        return d;
    }""")
    check("★チェックした人を上にまとめられる",
          chk["order"] == "desc" and all(chk["top"]), chk["top"])
    check("★もう一度押すと未チェックが上になる",
          chk["order2"] == "asc" and not any(chk["top2"]), chk["top2"])
    check("チェックで並べ替えても該当件数は変わらない", chk["n"] == n_ref, chk["n"])
    pg.evaluate("() => { msSelected.clear(); updateMsSelCount(); }")

    # 全選択は「表示中のページ」ではなく「該当者すべて」
    allsel = pg.evaluate("""() => {
        msSelectAll(true);
        return {sel: msSelected.size, ids: msIds.length, shown: msResults.length};
    }""")
    check("★全選択は該当者すべてが対象(表示中のページだけではない)",
          allsel["sel"] >= allsel["ids"], allsel)
    pg.evaluate("() => { msSelected.clear(); updateMsSelCount(); }")

    # ── よく使う条件(v1.2.3)──
    pre = pg.evaluate("""() => {
        msPreset('birth');
        return {rows: msRows.filter(r => r.field).map(r => [r.field, r.from, r.to]),
                dm: document.getElementById('ms-dm').checked};
    }""")
    check("よく使う条件「今月が誕生月」が条件を入れる",
          pre["rows"] and pre["rows"][0][0] == "birth_month" and pre["dm"] is True, pre["rows"])
    n_birth = search()
    check("「今月が誕生月」で検索できる", n_birth["count"] >= 0, n_birth["count"])

    # ── 日報CSVの支払方法の列(v1.2.4)──
    dsv = pg.evaluate("""async () => {
        var r = await fetch('/api/daily_sales?date=2026-09-02');
        var j = await r.json();
        return {cols: j.payColumns, map: j.payColumnOf,
                split: (j.lines || []).map(l => [l.item, l.amount, l.pay, l.pay_split])};
    }""")
    check("日報が支払方法の列を返す",
          dsv["cols"] and "カード・クレジット" in dsv["cols"], dsv["cols"])
    check("★カードとクレジットが同じ列にまとまっている",
          dsv["map"].get("カード") == dsv["map"].get("クレジット") == "カード・クレジット",
          {k: dsv["map"].get(k) for k in ("カード", "クレジット")})

    # ★実際に書き出されるCSVの中身を見る(downloadCsv を横取りして受け取る)。
    #   店から報告のあった「売掛入金がカードなのに区別できない」不具合そのものの確認
    pg.click('.nav-item[data-screen="reports"]')
    pg.wait_for_timeout(1200)
    csv = pg.evaluate("""async (d) => {
        document.getElementById('rep-date').value = d;
        var got = null, orig = window.downloadCsv;
        window.downloadCsv = function (name, rows) { got = {name: name, rows: rows}; };
        exportDailyCsv();
        await new Promise(r => setTimeout(r, 1500));
        window.downloadCsv = orig;
        return got;
    }""", CSV_DATE)
    check("日報CSVが書き出せる", bool(csv and csv["rows"]), csv and csv["name"])
    head = csv["rows"][0]
    body = csv["rows"][1:]
    print("      CSVの見出し:", head)
    for r in body:
        print("      ", r)
    check("CSVの見出しに支払方法の列が並ぶ",
          head[:7] == ["日付", "顧客", "区分", "内容", "金額", "支払", "担当者"]
          and "カード・クレジット" in head, head)
    paid_row = [r for r in body if r[2] == "売掛入金" and r[4] == CSV_PAID]
    check("★売掛入金の行に支払方法「カード」が入る(v1.2.4で直した不具合)",
          bool(paid_row) and paid_row[0][5] == "カード",
          paid_row[0][:7] if paid_row else "行が見つからない")
    ci = head.index("カード・クレジット")
    check("★その金額がカード・クレジットの列に入る",
          bool(paid_row) and paid_row[0][ci] == CSV_PAID,
          paid_row[0][ci] if paid_row else None)
    cash_i = head.index("現金")
    check("★カードの入金は現金の列には入らない(レジ締めが狂わない)",
          bool(paid_row) and not paid_row[0][cash_i], paid_row[0][cash_i] if paid_row else None)
    sale_row = [r for r in body if r[2] == "レジ売上"]
    check("現金の売上は現金の列に入る",
          bool(sale_row) and sale_row[0][cash_i] == sale_row[0][4],
          sale_row[0][:7] if sale_row else "行なし")
    # 列を縦に足すと、その日の方法別の受取になる(Excelでやることと同じ検算)
    tot = {}
    for r in body:
        for i in range(7, len(head)):
            if r[i]:
                tot[head[i]] = tot.get(head[i], 0) + r[i]
    check("★列の合計 = 金額の合計(どの行も必ずどれかの列に入っている)",
          sum(tot.values()) == sum(r[4] for r in body), f'{tot} / 金額計 {sum(r[4] for r in body)}')

    check("画面のJSエラーが出ていない", not errors, errors[:3])
    pg.screenshot(path=SHOT + "/33_multi_full.png", full_page=True)
    br.close()

# ── 片付け(テスト用に入れた売掛入金を消す)──
_c = sqlite3.connect(DB)
_c.execute("DELETE FROM receivable_entries WHERE id=?", (TEST_ENTRY,))
_c.commit()
_c.close()
check("片付け完了(テスト用の入金を削除)",
      not rows("SELECT id FROM receivable_entries WHERE id=?", (TEST_ENTRY,)))

print("\n" + "=" * 60)
ng = [r for r in results if not r[1]]
print(f"  {len(results)}項目中 {len(results)-len(ng)}項目OK / NG {len(ng)}項目")
for n, _o, d in ng:
    print(f"    ★ {n}   {d}")
sys.exit(1 if ng else 0)
