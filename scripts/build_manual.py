#!/usr/bin/env python3
"""トキワ操作マニュアル(簡潔版・詳細版)のHTMLを生成する。
・大きめ文字・ゴシック(PDFはIPA Pゴシックにフォールバック)・図/画面イメージ入り。
・符丁の説明は含めない(パート権限の人が見る可能性があるため)。
・余白が大きすぎるページを避けるため、強制改ページは最小限にする。
PDF化は別途 Chromium で行う(scripts では生成しない)。

  python3 scripts/build_manual.py    # docs/manual-quick.html と docs/manual-full.html を生成
"""
import os

BASE = os.path.join(os.path.dirname(__file__), "..")
DOCS = os.path.join(BASE, "docs")

# フォント: 画面(HTML)は Hiragino/Yu Gothic 等でこれまで通り。PDF(この環境のChromium)は
# それらが無いので IPAPGothic/IPAGothic を使う。中国語フォントへの化けを防ぐため明示する。
FONT = ('"Hiragino Kaku Gothic ProN","Yu Gothic","YuGothic","Meiryo",'
        '"Noto Sans CJK JP","Noto Sans JP","IPAPGothic","IPAGothic",sans-serif')

CSS = """
  :root{ --ink:#191c20; --muted:#54606e; --line:#d6dce4; --accent:#7a1f2b; --accent2:#a83a48;
         --soft:#f6f2ef; --warn:#8a5a00; --warnbg:#fff6e0; --ok:#2f6f3e; --okbg:#eef6f0; --info:#2a5b8a; --infobg:#eef3f8; }
  *{ box-sizing:border-box; }
  html{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  body{ font-family:__FONT__; color:var(--ink); line-height:1.85; margin:0; font-size:21px; background:#fff; }
  .page{ max-width:960px; margin:0 auto; padding:26px 32px; }
  .hd{ background:var(--accent); color:#fff; border-radius:10px; padding:20px 26px; margin-bottom:8px; }
  .hd .ttl{ font-size:34px; font-weight:800; letter-spacing:.02em; }
  .hd .st{ font-size:19px; opacity:.95; margin-top:4px; }
  .hd .badge{ display:inline-block; background:#fff; color:var(--accent); font-weight:800; font-size:15px;
        padding:3px 16px; border-radius:999px; letter-spacing:.15em; margin-bottom:8px; }
  h2{ font-size:27px; margin:30px 0 12px; padding:9px 18px; background:var(--accent); color:#fff; border-radius:6px; }
  h3{ font-size:23px; margin:24px 0 8px; padding:3px 0 6px; border-bottom:3px solid var(--accent2); color:var(--accent); }
  h4{ font-size:20px; margin:16px 0 6px; }
  p{ margin:8px 0; }
  ul,ol{ margin:8px 0 12px; padding-left:1.5em; }
  li{ margin:5px 0; }
  b{ color:#111; }
  code{ background:var(--soft); padding:2px 7px; border-radius:4px; font-family:Consolas,Menlo,monospace; font-size:.9em; }
  table{ border-collapse:collapse; width:100%; margin:14px 0; font-size:19px; }
  th,td{ border:1px solid var(--line); padding:9px 12px; text-align:left; vertical-align:top; }
  th{ background:var(--soft); }
  .lead{ color:var(--muted); font-size:20px; }
  .note{ background:var(--warnbg); border-left:6px solid var(--warn); padding:12px 16px; margin:14px 0; border-radius:0 6px 6px 0; }
  .note b{ color:var(--warn); }
  .tip{ background:var(--okbg); border-left:6px solid var(--ok); padding:12px 16px; margin:14px 0; border-radius:0 6px 6px 0; }
  .tip b{ color:var(--ok); }
  /* メニューグリッド(図) */
  .menugrid{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0; }
  .menugrid .m{ flex:1 1 28%; min-width:180px; border:2px solid var(--line); border-radius:12px; padding:12px 14px; background:#fff; }
  .menugrid .m .ic{ font-size:1.7em; line-height:1; }
  .menugrid .m .nm{ font-weight:800; font-size:1.05em; }
  .menugrid .m .ds{ color:var(--muted); font-size:.8em; }
  /* フロー図(縦) */
  .flow{ margin:16px 0; }
  .flow .box{ border:2px solid var(--accent2); background:#fff; border-radius:12px; padding:11px 16px; font-size:1.02em; }
  .flow .box .n{ display:inline-block; background:var(--accent); color:#fff; border-radius:50%; width:1.7em; height:1.7em;
        line-height:1.7em; text-align:center; margin-right:.55em; font-weight:800; font-size:.85em; }
  .flow .box b{ color:var(--accent); }
  .flow .box small{ display:block; color:var(--muted); font-size:.8em; margin:2px 0 0 2.4em; line-height:1.55; }
  .flow .arrow{ text-align:center; color:var(--accent2); font-size:1.5em; line-height:1; margin:1px 0; }
  /* 役割カード(図) */
  .rolecards{ display:flex; gap:14px; flex-wrap:wrap; margin:14px 0; }
  .rolecards .rc{ flex:1 1 30%; min-width:230px; border-radius:12px; padding:14px 16px; border:2px solid; font-size:.95em; }
  .rc h4{ margin:0 0 6px; font-size:1.1em; }
  .rc.admin{ border-color:var(--ok); background:var(--okbg); } .rc.admin h4{ color:var(--ok); }
  .rc.staff{ border-color:var(--info); background:var(--infobg); } .rc.staff h4{ color:var(--info); }
  .rc.part{ border-color:var(--warn); background:var(--warnbg); } .rc.part h4{ color:var(--warn); }
  .btnrow{ display:flex; flex-wrap:wrap; gap:10px; margin:12px 0; }
  .btnrow .bt{ border:2px solid var(--accent); color:var(--accent); border-radius:8px; padding:7px 13px; font-weight:800; background:#fff; font-size:.9em; }
  .toc{ background:var(--soft); border:1px solid var(--line); border-radius:10px; padding:14px 30px; font-size:20px; column-count:2; column-gap:30px; }
  .toc ol{ margin:0; }
  /* 画面イメージ(モック) */
  .screen{ border:2px solid #cfd6df; border-radius:10px; overflow:hidden; margin:16px 0 4px; box-shadow:0 1px 3px rgba(0,0,0,.10); }
  .screen .bar{ background:#3a4150; color:#fff; padding:5px 12px; font-size:14px; font-weight:700; }
  .screen .rowx{ display:flex; }
  .screen .nav{ background:#eef1f5; border-right:1px solid #dfe4ea; padding:8px 6px; width:96px; font-size:13px; }
  .screen .nav .it{ padding:3px 6px; border-radius:5px; color:#5a6673; margin:1px 0; }
  .screen .nav .it.on{ background:var(--accent); color:#fff; font-weight:800; }
  .screen .main{ flex:1; padding:11px 13px; background:#fff; }
  .shot{ display:block; width:100%; border:1px solid var(--line); border-radius:8px; box-shadow:0 1px 5px rgba(0,0,0,.14); margin:16px 0 4px; }
  .cap{ text-align:center; font-size:15px; color:var(--muted); margin:0 0 14px; }
  /* モック内部 */
  .mk-btns{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }
  .mk-btn{ border:1.5px solid var(--accent); color:var(--accent); border-radius:6px; padding:3px 9px; font-size:13px; font-weight:800; }
  .mk-btn.p{ background:var(--accent); color:#fff; }
  .mk-field{ border:1.5px solid #cfd6df; border-radius:6px; padding:4px 9px; font-size:13px; color:#66707c; background:#fbfcfd; margin:4px 0; }
  .mk-t{ width:100%; border-collapse:collapse; font-size:12.5px; margin-top:5px; }
  .mk-t th,.mk-t td{ border:1px solid #e2e7ee; padding:3px 7px; text-align:left; }
  .mk-t th{ background:#f4f6f9; }
  .mk-tiles{ display:flex; gap:6px; margin-bottom:7px; }
  .mk-tile{ flex:1; border:1px solid #e2e7ee; border-radius:6px; padding:5px; text-align:center; font-size:12px; background:#fafbfc; }
  .mk-tile b{ display:block; font-size:1.5em; color:var(--accent); }
  .mk-note{ font-size:12.5px; color:#66707c; margin-top:5px; }
  hr.br{ border:0; border-top:2px dashed var(--line); margin:24px 0; }
  @media print{
    .page{ max-width:none; padding:0 3mm; }
    h2,h3,h4{ page-break-after:avoid; }
    table,.note,.tip,.flow .box,.menugrid .m,.rolecards .rc,.btnrow,.screen{ page-break-inside:avoid; }
    .page-break{ page-break-before:always; }
    a{ color:inherit; text-decoration:none; }
  }
""".replace("__FONT__", FONT)


def wrap(title, body):
    return ("<!DOCTYPE html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{title}</title><style>{CSS}</style></head><body><div class=\"page\">"
            f"{body}</div></body></html>\n")


def flow(steps):
    out = ["<div class=\"flow\">"]
    for i, (t, s) in enumerate(steps):
        if i:
            out.append("<div class=\"arrow\">▼</div>")
        sm = f"<small>{s}</small>" if s else ""
        out.append(f"<div class=\"box\"><span class=\"n\">{i+1}</span><b>{t}</b>{sm}</div>")
    out.append("</div>")
    return "".join(out)


NAV = [("レジ", "register"), ("顧客", "customers"), ("検索", "search"), ("売掛", "recv"),
       ("商品", "products"), ("棚卸", "stocktake"), ("修理", "repair"),
       ("見積", "estimate"), ("日報", "reports"), ("設定", "settings")]


def screen(active, main, cap):
    nav = "".join(f'<div class="it{" on" if k == active else ""}">{lbl}</div>' for lbl, k in NAV)
    return (f'<div class="screen"><div class="bar">トキワ</div>'
            f'<div class="rowx"><div class="nav">{nav}</div>'
            f'<div class="main">{main}</div></div></div>'
            f'<div class="cap">▲ {cap}(画面イメージ)</div>')


def img(name, cap):
    return (f'<img class="shot" src="manual-img/{name}" alt="{cap}">'
            f'<div class="cap">▲ {cap}(実際の画面)</div>')


MENUGRID = """
<div class="menugrid">
  <div class="m"><div class="ic">￥</div><div class="nm">レジ</div><div class="ds">売上登録・会計</div></div>
  <div class="m"><div class="ic">👤</div><div class="nm">顧客管理</div><div class="ds">検索・登録・履歴</div></div>
  <div class="m"><div class="ic">🔍</div><div class="nm">検索・分析</div><div class="ds">詳細検索・ランキング</div></div>
  <div class="m"><div class="ic">💳</div><div class="nm">売掛管理</div><div class="ds">入金・残高</div></div>
  <div class="m"><div class="ic">◆</div><div class="nm">商品・在庫</div><div class="ds">仕入登録・在庫一覧</div></div>
  <div class="m"><div class="ic">📋</div><div class="nm">棚卸し</div><div class="ds">現物照合</div></div>
  <div class="m"><div class="ic">🔧</div><div class="nm">修理伝票</div><div class="ds">預かり・写真・印刷</div></div>
  <div class="m"><div class="ic">📄</div><div class="nm">見積・請求</div><div class="ds">見積書・請求書</div></div>
  <div class="m"><div class="ic">▤</div><div class="nm">日報・帳票</div><div class="ds">売上の締め</div></div>
  <div class="m"><div class="ic">⚙</div><div class="nm">設定・マスター</div><div class="ds">各種マスタ・権限</div></div>
</div>
"""

ROLECARDS = """
<div class="rolecards">
  <div class="rc admin"><h4>管理者</h4>すべて可。ユーザー管理・担当者マスタも操作できます。</div>
  <div class="rc staff"><h4>社員</h4>ユーザー管理・担当者マスタ以外はほぼ可。</div>
  <div class="rc part"><h4>パート</h4>原価(下代)・粗利・商品在庫画面・設定は<b>見えません</b>。レジ・接客が中心。</div>
</div>
"""

# ---- 画面イメージ(モック)の中身 ----
MK_REGISTER = ('<div class="mk-field">🔍 お客様を検索(カナ・電話)</div>'
               '<div class="mk-btns"><span class="mk-btn">＋商品番号で追加</span>'
               '<span class="mk-btn">＋番号なしで追加</span><span class="mk-btn">＋受託品(催事)</span></div>'
               '<table class="mk-t"><tr><th>品名</th><th>買上金額</th></tr>'
               '<tr><td>Pt900 ダイヤリング</td><td>250,000</td></tr>'
               '<tr><td>電池交換</td><td>1,320</td></tr></table>'
               '<div class="mk-note">支払方法: 現金 / クレジット / PayPay / 掛売 / 分割　→　'
               '<span class="mk-btn p">会計を確定</span></div>')

MK_CUSTOMER = ('<div class="mk-field">🔍 カナ・電話番号・担当者・ランク・誕生月で検索</div>'
               '<table class="mk-t"><tr><th>氏名</th><th>カナ</th><th>担当</th><th>電話</th></tr>'
               '<tr><td>山田 花子</td><td>ﾔﾏﾀﾞ ﾊﾅｺ</td><td>三輪</td><td>090-…</td></tr>'
               '<tr><td>鈴木 亮</td><td>ｽｽﾞｷ ﾘｮｳ</td><td>田中</td><td>070-…</td></tr></table>'
               '<div class="mk-note">タブ: 基本情報 / 購入・アプローチ履歴 / 入金管理 / ポイント / 処方箋</div>')

MK_RECV = ('<table class="mk-t"><tr><th>お客様</th><th>残高</th><th>担当</th><th></th></tr>'
           '<tr><td>売掛 次郎</td><td>560,000</td><td>簗瀬</td><td><span class="mk-btn p">入金</span></td></tr>'
           '<tr><td>井上 智子</td><td>585,000</td><td>簗瀬</td><td><span class="mk-btn p">入金</span></td></tr></table>'
           '<div class="mk-note">残高の多い順。「入金」で 金額＋方法(現金/振込/カード/その他) を記録。</div>')

MK_PRODUCT = ('<div class="mk-note">仕入登録タブ</div>'
              '<div class="mk-field">品名: Pt900 サファイアリング</div>'
              '<div class="mk-field">分類 / ブランド / 地金 / 仕入先</div>'
              '<div class="mk-field">仕入単価(下代) / 上代　→ 掛率・折数は自動</div>'
              '<div class="mk-btns"><span class="mk-btn">📷 写真</span><span class="mk-btn p">登録</span></div>')

MK_STOCK = ('<div class="mk-tiles"><div class="mk-tile"><b>2,617</b>在庫</div>'
            '<div class="mk-tile"><b>2,540</b>確認済</div><div class="mk-tile"><b>77</b>未確認(差異)</div></div>'
            '<div class="mk-field">商品番号を読み取り(スキャン/入力してEnter)　<span class="mk-btn p">確認</span></div>'
            '<table class="mk-t"><tr><th>差異(未確認)</th><th>保管場所</th></tr>'
            '<tr><td>17543-1-01-20-130</td><td>本店ケースA</td></tr></table>')

MK_REPAIR = ('<div class="mk-btns"><span class="mk-btn p">＋新規預かり</span></div>'
             '<table class="mk-t"><tr><th>お客様</th><th>品物</th><th>状態</th><th>写真</th></tr>'
             '<tr><td>修理 実子</td><td>時計 電池・ベルト</td><td>進行中</td><td>🖼️</td></tr></table>'
             '<div class="mk-note">預かり伝票を印刷して手渡し。進行中/引渡済みで管理。</div>')


# ============================================================ 簡潔版
def build_quick():
    b = []
    b.append('<div class="hd"><div class="badge">簡潔版</div>'
             '<div class="ttl">トキワ かんたん操作ガイド</div>'
             '<div class="st">図と画面でわかる ／ 宝石・メガネ・時計 ヤナセ ／ 2026-07-23</div></div>')

    b.append('<h2>画面メニュー</h2>')
    b.append('<p class="lead">左のメニューで画面を切り替えます。</p>')
    b.append(MENUGRID)
    b.append('<div class="note"><b>権限がパートの人</b>は、原価(下代)・粗利・商品在庫画面・設定は表示されません。</div>')

    b.append('<h2>1. レジで会計する</h2>')
    b.append(img("register.png", "レジ画面"))
    b.append(flow([
        ("お客様を選ぶ", "カタカナ名や電話番号で検索。新規は「＋新規顧客」。"),
        ("商品を明細に足す", "「＋商品番号で追加」でスキャン/入力。修理・電池は「＋番号なしで追加」。"),
        ("金額を確認する", "値引きは買上金額をその場で書き換えればOK。"),
        ("会計担当を選ぶ", "レジを打つ人を毎回選びます。"),
        ("支払方法を選ぶ", "現金/クレジット/PayPay/掛売/分割。分割は「＋支払方法を追加」。"),
        ("「会計を確定」", "お預かりを入れると釣銭が出ます。履歴・在庫・売掛まで自動。"),
    ]))
    b.append('<div class="tip"><b>掛売</b>にすると、その分がお客様の<b>売掛残</b>になります(現金締めには数えません)。</div>')

    b.append('<h2>2. 顧客を探す・登録する</h2>')
    b.append(img("customers.png", "顧客管理画面"))
    b.append(flow([
        ("「👤 顧客管理」を開く", None),
        ("カナ・電話などで検索", "半角/全角・大小文字は気にしなくてOK。"),
        ("顧客を開く", "基本情報／購入履歴／入金／ポイント／処方箋のタブ。"),
        ("新規は「＋新規顧客」", "郵便番号から住所を呼び出せます。"),
    ]))

    b.append('<h2>3. 売掛の入金を記録する</h2>')
    b.append(img("receivables.png", "売掛管理画面"))
    b.append(flow([
        ("「💳 売掛管理」を開く", "残高の多い順に並びます。"),
        ("お客様の「入金」を押す", None),
        ("入金額と方法を入れる", "現金/銀行振込/カード/その他。"),
        ("残高が自動で減る", "入金履歴に1行残ります。"),
    ]))

    b.append('<h2>4. 商品を登録する</h2>')
    b.append(img("products_purchase.png", "商品・在庫(仕入登録)画面"))
    b.append(flow([
        ("「◆ 商品・在庫」→「仕入登録」", None),
        ("品名・分類・仕入先・価格を入力", "宝石以外は宝飾専用の項目が隠れます。"),
        ("「登録」する", "掛率・折数は自動。写真も付けられます。"),
    ]))

    b.append('<h2>5. 催事で受託品を打つ</h2>')
    b.append(flow([
        ("レジで「＋受託品(催事)」", None),
        ("メーカーを選び金額を入れる", "品名は任意(未入力なら「受託品」)。"),
        ("そのまま会計する", "原価・正式品番は後日、納品書が来てから。"),
    ]))

    b.append('<h2>6. 修理を預かる</h2>')
    b.append(img("repairs.png", "修理伝票画面"))
    b.append(flow([
        ("「🔧 修理伝票」→「＋新規預かり」", None),
        ("お客様・品物・内容を入力", "写真も撮って添付できます。"),
        ("預かり伝票を印刷して渡す", "進行中/引渡済みで管理。"),
    ]))

    b.append('<h2>7. 棚卸しをする</h2>')
    b.append(img("stocktake.png", "棚卸し画面"))
    b.append(flow([
        ("「📋 棚卸し」を開く", "開始日時が記録されます。"),
        ("現物を1点ずつスキャン", "商品番号を読み取り→「確認」。"),
        ("差異を確認する", "未確認に残った在庫が差異(紛失・登録漏れの疑い)。"),
        ("必要ならCSVに出す", "やり直しは「最初からやり直す」。"),
    ]))
    b.append('<div class="note">棚卸しは<b>パート権限では使えません</b>。</div>')

    b.append('<hr class="br"><p class="lead">くわしくは「詳細版マニュアル」を見てください。</p>')
    return wrap("トキワ かんたん操作ガイド(簡潔版)", "".join(b))


# ============================================================ 詳細版
def build_full():
    b = []
    b.append('<div class="hd"><div class="badge">詳細版</div>'
             '<div class="ttl">トキワ 操作マニュアル</div>'
             '<div class="st">画面ごとのくわしい説明 ／ 宝石・メガネ・時計 ヤナセ ／ 2026-07-23</div></div>')

    b.append('<h2>目次</h2><div class="toc"><ol>'
             '<li>全体像・ログイン・権限</li><li>レジ(売上登録)</li><li>顧客管理</li>'
             '<li>検索・分析</li><li>売掛管理</li><li>商品・在庫(仕入登録)</li><li>棚卸し</li>'
             '<li>修理伝票</li><li>見積・請求</li><li>日報・帳票</li><li>設定・マスター</li>'
             '<li>受託(催事)の運用</li><li>メンテナンス(バックアップ等)</li>'
             '</ol></div>')

    b.append('<div class="page-break"></div>')
    b.append('<h2>1. 全体像・ログイン・権限</h2>')
    b.append('<p>トキワは、宝飾ナビに代わる店舗の販売・顧客・在庫の管理システムです。1台のPCで動かし、ブラウザで使います。</p>')
    b.append('<h3>画面メニュー</h3>')
    b.append(MENUGRID)
    b.append('<h3>ログイン</h3>')
    b.append('<p>ユーザーごとにログインします。パスワードは<b>本人が初回ログイン時に設定</b>します(管理者がリセットすると、次回ログインで再設定)。</p>')
    b.append('<h3>権限(役割)</h3>')
    b.append(ROLECARDS)
    b.append('<div class="note"><b>原価の保護</b>: 原価(下代)や粗利は、パート権限には表示されません。</div>')

    b.append('<h2>2. レジ(売上登録)</h2>')
    b.append('<p>お客様を選び、明細を作り、支払を確定する画面です。</p>')
    b.append(img("register.png", "レジ画面"))
    b.append('<h3>明細の作り方(ボタン)</h3>')
    b.append('<table>'
             '<tr><th>ボタン</th><th>使う場面</th></tr>'
             '<tr><td>＋商品番号で追加(在庫品)</td><td>在庫の商品を番号で追加。スキャナまたは手入力。</td></tr>'
             '<tr><td>＋番号なしで追加</td><td>電池交換・レンズ・各種修理など、在庫品でないものを品名・金額で追加。</td></tr>'
             '<tr><td>＋受託品(催事)</td><td>メーカーの受託品をその場で追加(→ 12章)。</td></tr>'
             '<tr><td>💴 レジ入出金</td><td>代引手数料・収入印紙・両替・経費など、買い物と無関係な現金の出入り。</td></tr>'
             '</table>')
    b.append('<h3>金額・値引き</h3>')
    b.append('<p>各明細の<b>買上金額は書き換え可能</b>です。値引きはここで金額を下げて表現します。定価との差から割引率が表示されます。</p>')
    b.append('<h3>お会計</h3>')
    b.append('<ul>'
             '<li><b>会計担当</b>: レジを打つ人を毎回選びます(打ち手の意識づけのため毎回リセット)。</li>'
             '<li><b>支払方法</b>: 現金 / クレジット / PayPay / 掛売 / 分割。「＋支払方法を追加」で分割払い(複数方法)に対応。</li>'
             '<li><b>掛売</b>: 選ぶとその金額が<b>売掛残</b>になります(現金締めには数えません)。</li>'
             '<li><b>使用ポイント</b>: 会計でポイントを使う枠があります。</li>'
             '<li><b>お預かり・釣銭</b>: 現金分のお預かりを入れると釣銭が出ます。テンキーで入力できます。</li>'
             '<li><b>会計を確定</b>: 購入履歴へ記録、在庫品は在庫から引落、掛売は売掛へ計上まで自動。</li>'
             '</ul>')

    b.append('<h2>3. 顧客管理</h2>')
    b.append(img("customers.png", "顧客管理画面"))
    b.append('<h3>検索</h3>')
    b.append('<p>顧客名・カナ・電話番号・担当者(番号でも可)・ランク・誕生月で絞り込めます。カナ検索は半角/全角・大小文字を自動でそろえて照合します。</p>')
    b.append('<h3>顧客詳細(タブ)</h3>')
    b.append('<table>'
             '<tr><th>タブ</th><th>内容</th></tr>'
             '<tr><td>基本情報</td><td>住所・連絡先・担当・ランク・<b>登録日</b>・<b>指輪サイズ</b>・'
             '<b>ピアス穴</b>・<b>顧客メモ</b>・家族など。編集や家族の追加/修正/削除。</td></tr>'
             '<tr><td>購入・アプローチ履歴</td><td>買上の履歴と、お声がけ(来店/DM/TEL/手紙)の記録。</td></tr>'
             '<tr><td>入金管理</td><td>そのお客様の売掛と入金の状況。</td></tr>'
             '<tr><td>ポイント</td><td>ポイントの残高・加算/使用の履歴。</td></tr>'
             '<tr><td>メガネ処方箋</td><td>度数などの処方箋情報。</td></tr>'
             '</table>')
    b.append('<h3>新規登録</h3>'
             '<p>「＋新規顧客」から登録。郵便番号→住所の呼び出しに対応。</p>'
             '<div class="tip">ご家族が既にお客様として登録されている場合は、'
             '<b>「ご家族から住所をコピー」</b>で郵便番号・住所・電話・地区をまとめて写せます'
             '(写した後で直せます)。</div>')

    b.append('<h3>顧客メモ</h3>')
    b.append('<p>宝飾ナビに書かれていた<b>顧客メモ</b>(接客の申し送り)は、そのまま引き継いで'
             '基本情報タブに表示します。宝飾ナビと同じ順番で並びます。</p>')
    b.append('<div class="note"><b>いまは読むだけです。</b>実データの完全移行が終わるまで、'
             'トキワから書き換えられないようにしてあります。移行のときにメモを入れ直すため、'
             'トキワで書いた分が消えてしまうからです。移行後に書き込めるようにします。</div>')

    b.append('<h3>家族の登録</h3>')
    b.append('<p>基本情報の「＋家族を追加」から登録します。方法は2つあります。</p>'
             '<table><tr><th>方法</th><th>使う場面</th></tr>'
             '<tr><td>新規に入力</td><td>その家族が<b>お客様として登録されていない</b>場合。'
             '氏名・続柄・性別・生年月日を手で入力します。</td></tr>'
             '<tr><td>登録済みの顧客とリンク</td><td>その家族も<b>お客様として登録されている</b>場合。'
             '氏名・性別・生年月日は相手の顧客情報に自動で追随します。'
             '一覧の氏名から相手の顧客情報へ飛べます。</td></tr></table>')
    b.append('<h4>続柄は「両方向」を入れます</h4>')
    b.append('<p>「登録済みの顧客とリンク」では、続柄の欄が<b>2段</b>あります。'
             '家族関係は<b>双方向で1つの事実</b>なので、片側だけ入れると'
             '相手の顧客情報を開いた時に続柄がズレて見えてしまうためです。'
             'どちら向きの続柄かを間違えないよう、欄には<b>実際のお名前</b>が出ます。</p>'
             '<table><tr><th>欄</th><th>意味</th><th>例</th></tr>'
             '<tr><td>上段 … ◯◯ から見て △△ は</td><td>今開いているお客様から見た、相手の続柄</td><td>妻</td></tr>'
             '<tr><td>下段 … △△ から見て ◯◯ は</td><td>相手から見た、今開いているお客様の続柄</td><td>夫</td></tr>'
             '</table>')
    b.append('<p><b>上段を選ぶと、下段は自動で入ります。</b>自動で決まるのは次の場合だけです。</p>'
             '<table><tr><th>上段で選んだ続柄</th><th>下段に自動で入る続柄</th></tr>'
             '<tr><td>夫 / 妻</td><td>妻 / 夫</td></tr>'
             '<tr><td>長男・次男・長女・次女</td><td>父(お客様が男性)/ 母(お客様が女性)</td></tr>'
             '<tr><td>父 / 母</td><td><b>家族</b> … 何番目のお子様かはデータから決められないため</td></tr>'
             '</table>')
    b.append('<div class="note"><b>「家族」は、正しい続柄が決められない時の逃げ道です。</b>'
             '自動で「家族」が入った時は欄の下に注意書きが出ますので、分かる場合は正しい続柄を選び直してください。'
             '<b>空欄にはできません</b>(空欄だと「未入力」か「間違い」か区別できないため、最低でも「家族」が入ります)。</div>')
    b.append('<div class="tip">続柄を直す時も同じ2段の画面が出ます。'
             '<b>「修正」で両側まとめて</b>直り、<b>「削除」も両側から</b>消えます。'
             'どちらか一方のお客様で直せば、もう一方も合います。</div>')

    b.append('<h2>4. 検索・分析</h2>')
    b.append(img('search.png','検索・分析画面'))
    b.append('<table>'
             '<tr><th>タブ</th><th>内容</th></tr>'
             '<tr><td>詳細検索</td><td>顧客の属性 × 買った商品 × 処方箋を<b>掛け合わせ(AND)</b>で絞り込む横断検索。「同じ商品を買った人」「特定条件の人」を抽出。</td></tr>'
             '<tr><td>購入順位ランキング</td><td>買上金額などの順位付け。</td></tr>'
             '<tr><td>メガネ処方箋検索</td><td>処方箋の条件で顧客を探す。</td></tr>'
             '</table>')

    b.append('<h2>5. 売掛管理</h2>')
    b.append(img("receivables.png", "売掛管理画面"))
    b.append('<p>売掛(未回収残高)のあるお客様を、残高の多い順に一覧します。誰がいくら・件数・最古買上日・最終入金日が見えます。</p>')
    b.append('<ul>'
             '<li><b>入金</b>: 入金額と方法(現金/銀行振込/カード/その他)を記録。残高が減り、履歴に残ります。</li>'
             '<li><b>＋売掛を追加</b>: レジを通さない過去分(紙の売掛)を手入力。</li>'
             '<li><b>修正 / 削除</b>: 入力ミスの訂正用。</li>'
             '</ul>')
    b.append('<div class="note"><b>今後の予定</b>: 売掛を立てた「後から」の値引き・ポイント使用は、専用の操作として追加予定です(現金入金とは区別して扱います)。</div>')

    b.append('<h2>6. 商品・在庫(仕入登録)</h2>')
    b.append(img("products_purchase.png", "商品・在庫(仕入登録)画面"))
    b.append('<h3>在庫一覧</h3>')
    b.append(img('products_stock.png','商品・在庫(在庫一覧)画面'))
    b.append('<p>状態(在庫/売上/受託/返品)・仕入先・ジャンル(宝石/メガネ/時計/その他)で絞り込み。商品を開くと詳細・写真が見られ、修正できます。</p>')
    b.append('<div class="tip"><b>在庫数</b>は「状態＝在庫」の商品だけを数えます。売れた品・受託品は在庫数に混ざりません。</div>')
    b.append('<h3>仕入登録</h3>')
    b.append('<p>品名・分類・ブランド・地金・仕入先・仕入単価(下代)・上代・店舗などを入力します。宝石以外は宝飾専用の項目が隠れ、掛率・折数は自動計算です。商品写真もその場で撮る/選べます。</p>')

    b.append('<h2>7. 棚卸し</h2>')
    b.append(img("stocktake.png", "棚卸し画面"))
    b.append('<p>店頭・金庫の現物を1点ずつ「商品番号」で読み取り、在庫台帳と照合します。開始日時が記録されます。</p>')
    b.append('<ul>'
             '<li>スキャン/入力→「確認」で現物確認済みに。緑=確認、赤=注意(番号なし/売却済み)、既に確認済みの再スキャンはお知らせのみ。</li>'
             '<li>同じ番号の在庫が複数あるときは、スキャンのたびに1点ずつ確認します。</li>'
             '<li>最後まで「未確認」に残った在庫が<b>差異</b>(紛失・盗難・登録漏れの疑い)。<b>CSV出力</b>できます。「最初からやり直す」でリセット。</li>'
             '</ul>')
    b.append('<div class="note">棚卸しは<b>パート権限では使えません</b>。</div>')

    b.append('<h2>8. 修理伝票</h2>')
    b.append(img("repairs.png", "修理伝票画面"))
    b.append('<p>宝飾ナビには無かった新機能。お預かりした修理品を管理します。「＋新規預かり」でお客様・品物・内容・見込みを登録し、<b>写真</b>を撮って添付できます。預かり伝票を<b>印刷</b>して手渡し、状態(進行中/引渡済み)で管理します。</p>')

    b.append('<h3>会計した後で間違いに気づいたら</h3>')
    b.append('<p>お客様の<b>購入履歴</b>(顧客詳細)から直します。何を間違えたかで方法が違います。</p>'
             '<table><tr><th>間違えたもの</th><th>直し方</th></tr>'
             '<tr><td><b>お客様を取り違えた</b></td><td><b>「顧客変更」</b>で正しいお客様に付け替える'
             '(下記)。取消して打ち直す必要はありません</td></tr>'
             '<tr><td>金額・支払方法・担当者・売上日</td><td><b>「取消」</b>してから正しく打ち直す。'
             '金額は直接書き換えられません(売上集計・現金締め・ポイント・在庫が全部ずれるため)</td></tr>'
             '<tr><td>品名(番号なしの明細)</td><td>購入履歴の行を<b>ダブルクリック</b>して品名を直す'
             '(金額は変えられません)</td></tr>'
             '<tr><td>品名(在庫品)</td><td>商品・在庫の<b>商品の修正</b>から。売上側は自動で追随します</td></tr>'
             '</table>')
    b.append('<h4>お客様の付け替え(2026-08-17 追加)</h4>')
    b.append('<p>レジで<b>別のお客様を選んだまま会計してしまった</b>時に使います。'
             '購入履歴の<b>「顧客変更」</b>ボタンから、正しいお客様・担当者・理由を入れて実行します。</p>'
             '<ul>'
             '<li><b>金額・在庫・レシートは動きません。</b>持ち主だけが変わります</li>'
             '<li><b>ポイント・売掛・メガネ処方箋も一緒に移ります</b>(ポイント残高も両方調整されます)</li>'
             '<li><b>伝票まるごと動きます。</b>同じ会計の他の明細も一緒に移るので、'
             '実行前に画面に出る明細一覧を必ず確認してください</li>'
             '<li>記録は<b>両方のお客様のメモ</b>に残ります(日付・担当者・理由)</li>'
             '</ul>')
    b.append('<div class="note"><b>付け替えができない場合</b>: '
             '<b>取消済みの売上</b>と、<b>売掛に入金済みの記録がある売上</b>は付け替えられません。'
             '入金の記録は伝票に紐づいていないため一緒に動かせず、持ち主だけ変えると'
             '入金履歴とねじれてしまうからです。この場合は取消して打ち直してください。</div>')
    b.append('<div class="tip"><b>なぜ「取消して打ち直す」ではないのか</b>: 打ち直すと、'
             '<b>間違えた側のお客様の履歴に取消の記録が残ります</b>。'
             '「うちの母は買っていないのに」と見えてしまうため、付け替えを別に用意しました。</div>')

    b.append('<h2>9. 見積・請求</h2>')
    b.append('<p>品名・金額の明細を作り、見積書・請求書として出力します。在庫商品から明細に取り込むこともできます。</p>')

    b.append('<h2>10. 日報・帳票</h2>')
    b.append('<ul>'
             '<li><b>日報</b>: その日の売上・現金の締め。現金と、振込・カードなど非現金を分けて確認できます。掛売(未回収)は現金に数えません。</li>'
             '<li><b>売上伝票明細表</b>: 期間・担当などで売上明細を一覧。</li>'
             '</ul>')

    b.append('<h2>11. 設定・マスター</h2>')
    b.append(img('settings.png','設定・マスター画面'))
    b.append('<p><b>マスタ管理</b>: 担当者・仕入先・商品分類・ブランド・石種・地金・購入動機・保管場所・支払方法・顧客ランク・地区を1画面で管理します。仕入先にはジャンル(宝石/メガネ/時計/その他)を設定でき、在庫一覧の絞り込みに使えます。</p>')
    b.append('<p><b>ログインユーザーと権限(管理者のみ)</b>: ユーザーの追加、役割(管理者/社員/パート)の設定、パスワードのリセット。</p>')

    b.append('<h2>12. 受託(催事)の運用</h2>')
    b.append('<p>催事などで、メーカーの品(自店の在庫でない品)をその場でレジに通すための機能です。<b>売上が先・納品書は後</b>という流れに合わせています。</p>')
    b.append(flow([
        ("レジで「＋受託品(催事)」", None),
        ("メーカーを選び金額を入れる", "品名は任意(既定「受託品」)。"),
        ("通常どおり会計する", "会計すると売上になります。"),
        ("後日、納品書で精算", "原価・正式品番を入れます(今後対応予定)。"),
    ]))
    b.append('<div class="tip">受託品は<b>在庫数には数えません</b>(自店の持ち物でないため)。</div>')

    b.append('<h2>13. メンテナンス(バックアップ等)</h2>')
    b.append('<h3>バックアップ</h3>')
    b.append('<p>データはPC内のデータベース1ファイルにまとまっています。定期的にバックアップを取ってください(火災・故障・盗難に備え、店外にも複製が理想)。</p>')
    b.append('<p><code>python3 scripts/backup_db.py</code>(タイムスタンプ付きで複製)</p>')
    b.append('<h3>売掛のクリア(初期化)</h3>')
    b.append('<ul>'
             '<li><code>python3 scripts/clear_receivables.py</code> … 売掛残高のみ消去(入金履歴は残す)。実行前に自動バックアップ。</li>'
             '<li><code>--with-history</code> … 入金履歴も消す。 <code>--yes</code> … 確認省略。</li>'
             '<li>再取込で復活します。恒久的に空で始めるなら取込時に <code>import_csv.py --no-receivables</code>。</li>'
             '</ul>')
    b.append('<div class="note"><b>注意</b>: スクリプトはサーバーを止めてから実行してください。復元はバックアップファイルを <code>db/tokiwa.db</code> に戻します。</div>')

    b.append('<hr class="br"><p class="lead">このマニュアルは現時点の機能までを収録しています。機能追加に合わせて更新します。</p>')
    return wrap("トキワ 操作マニュアル(詳細版)", "".join(b))


def main():
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "manual-quick.html"), "w", encoding="utf-8") as f:
        f.write(build_quick())
    with open(os.path.join(DOCS, "manual-full.html"), "w", encoding="utf-8") as f:
        f.write(build_full())
    print("wrote docs/manual-quick.html, docs/manual-full.html")


if __name__ == "__main__":
    main()
