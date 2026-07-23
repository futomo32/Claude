#!/usr/bin/env python3
"""トキワ操作マニュアル(簡潔版・詳細版)のHTMLを生成する。
図(フロー図)・大きめ文字・わかりやすさ重視。符丁の説明は含めない
(パート権限の人が見る可能性があるため)。PDF化は別途 Chromium で行う。

  python3 scripts/build_manual.py    # docs/manual-quick.html と docs/manual-full.html を生成
"""
import os

BASE = os.path.join(os.path.dirname(__file__), "..")
DOCS = os.path.join(BASE, "docs")

CSS = """
  :root{ --ink:#1a1c1f; --muted:#57606e; --line:#d6dce4; --accent:#7a1f2b; --accent2:#a83a48;
         --soft:#f6f2ef; --warn:#8a5a00; --warnbg:#fff6e0; --ok:#2f6f3e; --okbg:#eef6f0; --info:#2a5b8a; --infobg:#eef3f8; }
  *{ box-sizing:border-box; }
  html{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  body{ font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo",system-ui,sans-serif;
        color:var(--ink); line-height:1.85; margin:0; font-size:18px; background:#fff; }
  .page{ max-width:900px; margin:0 auto; padding:30px 34px; }
  h1{ font-size:40px; margin:0 0 6px; letter-spacing:.02em; }
  h2{ font-size:28px; margin:40px 0 14px; padding:10px 18px; background:var(--accent); color:#fff; border-radius:6px; }
  h3{ font-size:23px; margin:30px 0 10px; padding:4px 0 6px; border-bottom:3px solid var(--accent2); color:var(--accent); }
  h4{ font-size:19px; margin:18px 0 6px; }
  p{ margin:8px 0; }
  ul,ol{ margin:8px 0 12px; padding-left:1.5em; }
  li{ margin:5px 0; }
  b{ color:#111; }
  code{ background:var(--soft); padding:2px 7px; border-radius:4px; font-family:"SFMono-Regular",Consolas,Menlo,monospace; font-size:.92em; }
  table{ border-collapse:collapse; width:100%; margin:14px 0; font-size:17px; }
  th,td{ border:1px solid var(--line); padding:9px 12px; text-align:left; vertical-align:top; }
  th{ background:var(--soft); }
  .lead{ color:var(--muted); font-size:18px; }
  .note{ background:var(--warnbg); border-left:6px solid var(--warn); padding:12px 16px; margin:14px 0; border-radius:0 6px 6px 0; }
  .note b{ color:var(--warn); }
  .tip{ background:var(--okbg); border-left:6px solid var(--ok); padding:12px 16px; margin:14px 0; border-radius:0 6px 6px 0; }
  .tip b{ color:var(--ok); }
  .cover{ text-align:center; padding:150px 0 40px; }
  .cover .badge{ display:inline-block; background:var(--accent); color:#fff; font-size:20px; padding:6px 22px; border-radius:999px; margin-bottom:18px; letter-spacing:.15em; }
  .cover .sub{ color:var(--muted); font-size:20px; margin-top:10px; }
  .cover .ver{ margin-top:46px; color:var(--muted); font-size:16px; }
  /* メニューグリッド(図) */
  .menugrid{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0; }
  .menugrid .m{ flex:1 1 28%; min-width:170px; border:2px solid var(--line); border-radius:12px; padding:12px 14px; background:#fff; }
  .menugrid .m .ic{ font-size:1.7em; line-height:1; }
  .menugrid .m .nm{ font-weight:700; font-size:1.05em; }
  .menugrid .m .ds{ color:var(--muted); font-size:.82em; }
  /* フロー図(縦) */
  .flow{ margin:18px 0; }
  .flow .box{ border:2px solid var(--accent2); background:#fff; border-radius:12px; padding:12px 16px; font-size:1.05em; }
  .flow .box .n{ display:inline-block; background:var(--accent); color:#fff; border-radius:50%; width:1.7em; height:1.7em;
        line-height:1.7em; text-align:center; margin-right:.55em; font-weight:700; font-size:.9em; }
  .flow .box b{ color:var(--accent); }
  .flow .box small{ display:block; color:var(--muted); font-size:.82em; margin:2px 0 0 2.3em; line-height:1.6; }
  .flow .arrow{ text-align:center; color:var(--accent2); font-size:1.6em; line-height:1; margin:2px 0; }
  /* 役割カード(図) */
  .rolecards{ display:flex; gap:14px; flex-wrap:wrap; margin:14px 0; }
  .rolecards .rc{ flex:1 1 30%; min-width:210px; border-radius:12px; padding:14px 16px; border:2px solid; }
  .rc h4{ margin:0 0 6px; font-size:1.15em; }
  .rc.admin{ border-color:var(--ok); background:var(--okbg); }
  .rc.staff{ border-color:var(--info); background:var(--infobg); }
  .rc.part{ border-color:var(--warn); background:var(--warnbg); }
  .rc.admin h4{ color:var(--ok);} .rc.staff h4{ color:var(--info);} .rc.part h4{ color:var(--warn);}
  /* ボタン風の図 */
  .btnrow{ display:flex; flex-wrap:wrap; gap:10px; margin:12px 0; }
  .btnrow .bt{ border:2px solid var(--accent); color:var(--accent); border-radius:8px; padding:8px 14px; font-weight:700; background:#fff; }
  .chip{ display:inline-block; background:var(--soft); border:1px solid var(--line); border-radius:999px; padding:2px 12px; font-size:.9em; margin:2px; }
  .toc{ background:var(--soft); border:1px solid var(--line); border-radius:10px; padding:16px 26px; font-size:18px; }
  .toc a{ color:var(--ink); text-decoration:none; }
  hr.br{ border:0; border-top:2px dashed var(--line); margin:26px 0; }
  @media print{
    .page{ max-width:none; padding:0 4mm; }
    h2,h3,h4{ page-break-after:avoid; }
    table,.note,.tip,.flow .box,.menugrid .m,.rolecards .rc,.btnrow{ page-break-inside:avoid; }
    .page-break{ page-break-before:always; }
    a{ color:inherit; text-decoration:none; }
  }
"""


def wrap(title, body):
    return ("<!DOCTYPE html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{title}</title><style>{CSS}</style></head><body><div class=\"page\">"
            f"{body}</div></body></html>\n")


def flow(steps):
    """steps=[(タイトル, 補足 or None), ...] を縦フロー図に。"""
    out = ["<div class=\"flow\">"]
    for i, (t, s) in enumerate(steps):
        if i:
            out.append("<div class=\"arrow\">▼</div>")
        sm = f"<small>{s}</small>" if s else ""
        out.append(f"<div class=\"box\"><span class=\"n\">{i+1}</span><b>{t}</b>{sm}</div>")
    out.append("</div>")
    return "".join(out)


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


# ============================================================ 簡潔版
def build_quick():
    b = []
    b.append('<div class="cover"><div class="badge">簡潔版</div>'
             '<h1>トキワ かんたん操作ガイド</h1>'
             '<div class="sub">宝石・メガネ・時計 ヤナセ 「トキワ」</div>'
             '<div class="sub">よく使う操作だけ・図でわかる</div>'
             '<div class="ver">現時点の機能まで ／ 2026-07-23</div></div>')
    b.append('<div class="page-break"></div>')

    b.append('<h2>画面メニュー</h2>')
    b.append('<p class="lead">左のメニューで画面を切り替えます。</p>')
    b.append(MENUGRID)
    b.append('<div class="note"><b>権限がパートの人</b>は、原価(下代)・粗利・商品在庫画面・設定は表示されません。</div>')

    b.append('<div class="page-break"></div>')
    b.append('<h2>1. レジで会計する</h2>')
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
    b.append(flow([
        ("「👤 顧客管理」を開く", None),
        ("カナ・電話などで検索", "半角/全角・大小文字は気にしなくてOK。"),
        ("顧客を開く", "基本情報／購入履歴／入金／ポイント／処方箋のタブ。"),
        ("新規は「＋新規顧客」", "郵便番号から住所を呼び出せます。"),
    ]))

    b.append('<h2>3. 売掛の入金を記録する</h2>')
    b.append(flow([
        ("「💳 売掛管理」を開く", "残高の多い順に並びます。"),
        ("お客様の「入金」を押す", None),
        ("入金額と方法を入れる", "現金/銀行振込/カード/その他。"),
        ("残高が自動で減る", "入金履歴に1行残ります。"),
    ]))

    b.append('<div class="page-break"></div>')
    b.append('<h2>4. 商品を登録する</h2>')
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
    b.append(flow([
        ("「🔧 修理伝票」→「＋新規預かり」", None),
        ("お客様・品物・内容を入力", "写真も撮って添付できます。"),
        ("預かり伝票を印刷して渡す", "進行中/引渡済みで管理。"),
    ]))

    b.append('<h2>7. 棚卸しをする</h2>')
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
    b.append('<div class="cover"><div class="badge">詳細版</div>'
             '<h1>トキワ 操作マニュアル</h1>'
             '<div class="sub">宝石・メガネ・時計 ヤナセ 「トキワ」</div>'
             '<div class="sub">画面ごとのくわしい説明</div>'
             '<div class="ver">現時点の機能まで ／ 2026-07-23</div></div>')
    b.append('<div class="page-break"></div>')

    b.append('<h2 id="toc">目次</h2><div class="toc"><ol>'
             '<li>全体像・ログイン・権限</li>'
             '<li>レジ(売上登録)</li>'
             '<li>顧客管理</li>'
             '<li>検索・分析</li>'
             '<li>売掛管理</li>'
             '<li>商品・在庫(仕入登録)</li>'
             '<li>棚卸し</li>'
             '<li>修理伝票</li>'
             '<li>見積・請求</li>'
             '<li>日報・帳票</li>'
             '<li>設定・マスター</li>'
             '<li>受託(催事)の運用</li>'
             '<li>メンテナンス(バックアップ等)</li>'
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

    b.append('<div class="page-break"></div>')
    b.append('<h2>2. レジ(売上登録)</h2>')
    b.append('<p>お客様を選び、明細を作り、支払を確定する画面です。基本の流れは次のとおりです。</p>')
    b.append(flow([
        ("お客様を選ぶ", "カナ・電話で検索、または「＋新規顧客」。"),
        ("明細を作る", "在庫品・番号なし・受託品を追加。"),
        ("会計担当・支払方法を決める", None),
        ("会計を確定", "履歴・在庫引落・売掛計上まで自動。"),
    ]))
    b.append('<h3>明細の作り方(ボタン)</h3>')
    b.append('<div class="btnrow"><div class="bt">＋商品番号で追加</div><div class="bt">＋番号なしで追加</div>'
             '<div class="bt">＋受託品(催事)</div><div class="bt">💴 レジ入出金</div></div>')
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

    b.append('<div class="page-break"></div>')
    b.append('<h2>3. 顧客管理</h2>')
    b.append('<h3>検索</h3>')
    b.append('<p>顧客名・カナ・電話番号・担当者(番号でも可)・ランク・誕生月で絞り込めます。カナ検索は半角/全角・大小文字を自動でそろえて照合します。</p>')
    b.append('<h3>顧客詳細(タブ)</h3>')
    b.append('<table>'
             '<tr><th>タブ</th><th>内容</th></tr>'
             '<tr><td>基本情報</td><td>住所・連絡先・担当・ランク・家族など。編集や家族の追加/修正/削除。</td></tr>'
             '<tr><td>購入・アプローチ履歴</td><td>買上の履歴と、お声がけ(来店/DM/TEL/手紙)の記録。</td></tr>'
             '<tr><td>入金管理</td><td>そのお客様の売掛と入金の状況。</td></tr>'
             '<tr><td>ポイント</td><td>ポイントの残高・加算/使用の履歴。</td></tr>'
             '<tr><td>メガネ処方箋</td><td>度数などの処方箋情報。</td></tr>'
             '</table>')
    b.append('<h3>新規登録</h3><p>「＋新規顧客」から登録。郵便番号→住所の呼び出しに対応。</p>')

    b.append('<h2>4. 検索・分析</h2>')
    b.append('<table>'
             '<tr><th>タブ</th><th>内容</th></tr>'
             '<tr><td>詳細検索</td><td>顧客の属性 × 買った商品 × 処方箋を<b>掛け合わせ(AND)</b>で絞り込む横断検索。「同じ商品を買った人」「特定条件の人」を抽出。</td></tr>'
             '<tr><td>購入順位ランキング</td><td>買上金額などの順位付け。</td></tr>'
             '<tr><td>メガネ処方箋検索</td><td>処方箋の条件で顧客を探す。</td></tr>'
             '</table>')

    b.append('<div class="page-break"></div>')
    b.append('<h2>5. 売掛管理</h2>')
    b.append('<p>売掛(未回収残高)のあるお客様を、残高の多い順に一覧します。誰がいくら・件数・最古買上日・最終入金日が見えます。</p>')
    b.append(flow([
        ("お客様を開く", "残高の多い順に並びます。"),
        ("「入金」を押す", None),
        ("入金額と方法を入れる", "現金/銀行振込/カード/その他。"),
        ("残高が減り履歴に残る", None),
    ]))
    b.append('<ul>'
             '<li><b>＋売掛を追加</b>: レジを通さない過去分(紙の売掛)を手入力。</li>'
             '<li><b>修正 / 削除</b>: 入力ミスの訂正用。</li>'
             '</ul>')
    b.append('<div class="note"><b>今後の予定</b>: 売掛を立てた「後から」の値引き・ポイント使用は、専用の操作として追加予定です(現金入金とは区別して扱います)。</div>')

    b.append('<h2>6. 商品・在庫(仕入登録)</h2>')
    b.append('<h3>在庫一覧</h3>')
    b.append('<p>状態(在庫/売上/受託/返品)・仕入先・ジャンル(宝石/メガネ/時計/その他)で絞り込み。商品を開くと詳細・写真が見られ、修正できます。</p>')
    b.append('<div class="tip"><b>在庫数</b>は「状態＝在庫」の商品だけを数えます。売れた品・受託品は在庫数に混ざりません。</div>')
    b.append('<h3>仕入登録</h3>')
    b.append(flow([
        ("「仕入登録」タブを開く", None),
        ("品名・分類・仕入先・価格を入力", "宝石以外は宝飾専用の項目が隠れます。"),
        ("「登録」する", "掛率・折数は自動計算。写真も付けられます。"),
    ]))

    b.append('<div class="page-break"></div>')
    b.append('<h2>7. 棚卸し</h2>')
    b.append('<p>店頭・金庫の現物を1点ずつ「商品番号」で読み取り、在庫台帳と照合します。</p>')
    b.append(flow([
        ("棚卸しを開く", "開始日時が記録されます。"),
        ("現物を1点ずつスキャン", "商品番号を読み取り→「確認」。"),
        ("差異を確認する", "未確認に残った在庫が差異(紛失・盗難・登録漏れの疑い)。"),
        ("CSVに出す / やり直す", "「最初からやり直す」で記録をリセット。"),
    ]))
    b.append('<ul>'
             '<li>緑=確認済み、赤=注意(番号なし/売却済み)、既に確認済みの再スキャンはお知らせのみ。</li>'
             '<li>同じ番号の在庫が複数あるときは、スキャンのたびに1点ずつ確認します。</li>'
             '</ul>')
    b.append('<div class="note">棚卸しは<b>パート権限では使えません</b>。</div>')

    b.append('<h2>8. 修理伝票</h2>')
    b.append('<p>宝飾ナビには無かった新機能。お預かりした修理品を管理します。</p>')
    b.append('<ul>'
             '<li>「＋新規預かり」でお客様・品物・内容・見込みなどを登録。</li>'
             '<li><b>写真</b>を撮って添付(お預かり品の状態記録)。</li>'
             '<li>預かり伝票を<b>印刷</b>してお渡し。</li>'
             '<li>状態(進行中/引渡済み)で絞り込み・管理。</li>'
             '</ul>')

    b.append('<div class="page-break"></div>')
    b.append('<h2>9. 見積・請求</h2>')
    b.append('<p>品名・金額の明細を作り、見積書・請求書として出力します。在庫商品から明細に取り込むこともできます。</p>')

    b.append('<h2>10. 日報・帳票</h2>')
    b.append('<ul>'
             '<li><b>日報</b>: その日の売上・現金の締め。現金と、振込・カードなど非現金を分けて確認できます。掛売(未回収)は現金に数えません。</li>'
             '<li><b>売上伝票明細表</b>: 期間・担当などで売上明細を一覧。</li>'
             '</ul>')

    b.append('<h2>11. 設定・マスター</h2>')
    b.append('<h3>マスタ管理</h3>')
    b.append('<p>担当者・仕入先・商品分類・ブランド・石種・地金・購入動機・保管場所・支払方法・顧客ランク・地区を1画面で管理します。仕入先にはジャンル(宝石/メガネ/時計/その他)を設定でき、在庫一覧の絞り込みに使えます。</p>')
    b.append('<h3>ログインユーザーと権限(管理者のみ)</h3>')
    b.append('<p>ユーザーの追加、役割(管理者/社員/パート)の設定、パスワードのリセット。</p>')

    b.append('<div class="page-break"></div>')
    b.append('<h2>12. 受託(催事)の運用</h2>')
    b.append('<p>催事などで、メーカーの品(自店の在庫でない品)をその場でレジに通すための機能です。<b>売上が先・納品書は後</b>という流れに合わせています。</p>')
    b.append(flow([
        ("レジで「＋受託品(催事)」", None),
        ("メーカーを選び金額を入れる", "品名は任意(既定「受託品」)。"),
        ("通常どおり会計する", "会計すると売上になります。"),
        ("後日、納品書で精算", "原価・正式品番を入れます(今後対応予定)。"),
    ]))
    b.append('<ul>'
             '<li>受託品は<b>在庫数には数えません</b>(自店の持ち物でないため)。</li>'
             '</ul>')

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
