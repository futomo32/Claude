#!/usr/bin/env python3
"""data/demo/ のxlsxを読み、tokiwa-ui.html の <script id="tokiwa-data"> にデモデータを埋め込む。"""
import openpyxl, glob, json, os, re, unicodedata, datetime

BASE = os.path.join(os.path.dirname(__file__), "..")
DEMO = os.path.join(BASE, "data", "demo")
HTML = os.path.join(BASE, "tokiwa-ui.html")


def wb_rows(key):
    """ファイル名(NFC正規化)にkeyを含むxlsxを辞書行のリストで返す"""
    for p in glob.glob(os.path.join(DEMO, "*.xlsx")):
        if key in unicodedata.normalize("NFC", os.path.basename(p)):
            wb = openpyxl.load_workbook(p, read_only=True)
            ws = wb.worksheets[0]
            it = ws.iter_rows(values_only=True)
            header = [str(h) if h is not None else "" for h in next(it)]
            rows = [dict(zip(header, r)) for r in it]
            wb.close()
            return rows
    raise FileNotFoundError(key)


def s(v, limit=None):
    """文字列化(全角スペース→半角、None→空)"""
    if v is None:
        return ""
    t = str(v).replace("　", " ").strip()
    if limit and len(t) > limit:
        t = t[: limit - 1] + "…"
    return t


def d(v):
    """日付 → YYYY/MM/DD"""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y/%m/%d")
    t = s(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    return f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else t[:10]


def n(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return 0


def grp(dic, key, item):
    dic.setdefault(key, []).append(item)


# ── 顧客 [id, 名前, カナ, TEL, 担当, 住所, 生年月日, 性別, 累計, 2026年度, 結婚記念日]
customers = []
for r in wb_rows("顧客台帳"):
    addr = s(r.get("住所1"), 30)
    customers.append([
        s(r.get("顧客id")), s(r.get("顧客名"), 20), s(r.get("顧客名(フリガナ)"), 20),
        s(r.get("顧客tel")), s(r.get("担当者"), 10), addr,
        d(r.get("生年月日")), s(r.get("性別")), n(r.get("累計")), n(r.get("2026年度")),
        d(r.get("結婚記念日")),
    ])

# ── 売上 [日付, 商品名, 商品情報, 金額, 支払, 担当]
sales = {}
for r in wb_rows("販売台帳"):
    grp(sales, s(r.get("顧客id")), [
        d(r.get("販売日")), s(r.get("商品名"), 24), s(r.get("商品情報"), 18),
        n(r.get("販売価格/買上金額")), s(r.get("掛売区分/種別"), 8), s(r.get("担当/販売者"), 10),
    ])
for v in sales.values():
    v.sort(key=lambda x: x[0], reverse=True)

# ── 家族 [氏名, 続柄, 性別, 生年月日]
families = {}
for r in wb_rows("家族台帳"):
    grp(families, s(r.get("顧客id")), [
        s(r.get("家族名"), 16), s(r.get("続柄")), s(r.get("性別")), d(r.get("生年月日")),
    ])

# ── ポイント残高 / 履歴 [日付, 区分, 加算, 使用, 残]
points = {}
for r in wb_rows("ポイント台帳"):
    points[s(r.get("顧客id"))] = n(r.get("現残ポイント"))
point_tx = {}
for r in wb_rows("ポイントカード履歴"):
    grp(point_tx, s(r.get("顧客id")), [
        d(r.get("処理日付")), s(r.get("ポイント付与区分"), 8),
        n(r.get("付与・加算ポイント数")), n(r.get("使用ポイント数")), n(r.get("残ポイント数")),
    ])
for v in point_tx.values():
    v.sort(key=lambda x: x[0], reverse=True)

# ── 売掛 [商品名, 買上日, 頭金, 残高, 最終入金日] / 履歴 [日付, 区分, 商品名, 購入金額, 入金]
urikake = {}
for r in wb_rows("売掛台帳"):
    grp(urikake, s(r.get("顧客id")), [
        s(r.get("商品名"), 20), d(r.get("買上日付")), n(r.get("頭金")), n(r.get("残高")), d(r.get("最終入金日付")),
    ])
urikake_hist = {}
for r in wb_rows("売掛履歴"):
    grp(urikake_hist, s(r.get("顧客id")), [
        d(r.get("日付")), s(r.get("売掛処理区分"), 8), s(r.get("商品名"), 20),
        n(r.get("購入金額")), n(r.get("入金・頭金")),
    ])
for v in urikake_hist.values():
    v.sort(key=lambda x: x[0], reverse=True)

# ── アプローチ [日付, 種別, 内容, 担当]
approach = {}
for r in wb_rows("アプローチ履歴"):
    grp(approach, s(r.get("顧客id")), [
        d(r.get("アプローチ日(登録日)")), s(r.get("アプローチ内容"), 10),
        s(r.get("メッセージタイトル"), 30), s(r.get("担当者"), 10),
    ])
for v in approach.values():
    v.sort(key=lambda x: x[0], reverse=True)

# ── 処方箋 [No, 用途, レンズ, フレーム, 売値計, 定価計, sphR..addL, pd遠R/L/両, pd近R/L/両, 対応者, 処方日]
# 振り分けルール:
#   商品台帳の「メガネ商品」フラグは未設定が7,030件中5,471件と多く単独では不十分なため、
#   フラグ(宝石・時計)+商品名の宝飾語パターンの両方で宝飾品の誤紐づけを検出する。
#   ・度数入力がなく、メガネ商品にも紐づかない行 → 除外(ゴミデータ)
#   ・宝飾品が紐づくが度数がある行 → 残して名前に "!" を付け「誤登録」表示
item_flag = {}
for r in wb_rows("商品台帳"):
    item_flag[s(r.get("商品キー"))] = s(r.get("メガネ商品"))

POWER_COLS = ("SPH(右)", "SPH(左)", "CYL(右)", "CYL(左)", "AX(右)", "AX(左)",
              "ADD(右)", "ADD(左)", "PD遠(両)", "PD近(両)")
JEWELRY_PAT = re.compile(
    r"ﾘﾝｸﾞ|リング|ﾈｯｸﾚｽ|ネックレス|ﾀﾞｲﾔ|ダイヤ|ｻﾌｧｲｱ|ﾋﾟｱｽ|ﾌﾞﾚｽ|ﾍﾟﾝﾀﾞ|ﾒﾉｰ|ﾙﾋﾞｰ|ｴﾒﾗﾙﾄﾞ|ﾊﾟｰﾙ|真珠|指輪|K1[048]|PT|SV")

rx = {}
rx_kept = rx_warned = rx_dropped = 0
for r in wb_rows("処方箋"):
    has_power = any(s(r.get(k)) for k in POWER_COLS)
    is_glasses = False
    has_jewelry = False
    names = {}
    for part, id_col, name_col in (("lens", "商品ID(レンズ)", "商品名(レンズ)"),
                                   ("frame", "商品ID(フレーム)", "商品名(フレーム)")):
        pid = s(r.get(id_col))
        fl = item_flag.get(pid, "")
        name = s(r.get(name_col), 22)
        # 名前の宝飾語パターンを優先(IDがメガネ商品を指していても名前欄が宝飾品なら要確認とする)
        jewelry = fl == "宝石・時計" or bool(JEWELRY_PAT.search(name))
        if fl == "メガネ":
            is_glasses = True
        if jewelry:
            has_jewelry = True
            if name:
                name = "!" + name  # 宝飾品が誤って紐づいている印
        names[part] = name
    if not is_glasses and not has_power:
        rx_dropped += 1
        continue
    if has_jewelry:
        rx_warned += 1
    rx_kept += 1
    grp(rx, s(r.get("顧客id")), [
        s(r.get("処方箋No.")), s(r.get("用途名称"), 12),
        names["lens"], names["frame"],
        n(r.get("合計売値")), n(r.get("合計定価")),
        s(r.get("SPH(右)")), s(r.get("SPH(左)")), s(r.get("CYL(右)")), s(r.get("CYL(左)")),
        s(r.get("AX(右)")), s(r.get("AX(左)")), s(r.get("ADD(右)")), s(r.get("ADD(左)")),
        s(r.get("PD遠(右)")), s(r.get("PD遠(左)")), s(r.get("PD遠(両)")),
        s(r.get("PD近(右)")), s(r.get("PD近(左)")), s(r.get("PD近(両)")),
        s(r.get("対応者名"), 10), d(r.get("処理日付")),
    ])

# ── 商品 [番号, 名称, 分類, 上代, 状態, 保管場所, 中石]
products = []
for r in wb_rows("商品台帳"):
    stone = s(r.get("中石名称"), 10)
    w = s(r.get("中石重量"))
    if stone and w:
        stone += f" {w}ct"
    products.append([
        s(r.get("商品番号")), s(r.get("商品名"), 24), s(r.get("大分類名"), 12),
        n(r.get("上代価格")), s(r.get("状態区分")), s(r.get("保管場所(店舗名称)"), 10), stone,
    ])

data = dict(customers=customers, sales=sales, families=families, points=points,
            pointTx=point_tx, urikake=urikake, urikakeHist=urikake_hist,
            approach=approach, rx=rx, products=products)
blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

src = open(HTML, encoding="utf-8").read()
new = re.sub(
    r'<script id="tokiwa-data">.*?</script>',
    lambda m: '<script id="tokiwa-data">window.TOKIWA_DATA=' + blob + ';</script>',
    src, count=1, flags=re.S)
open(HTML, "w", encoding="utf-8").write(new)
print(f"customers={len(customers)} products={len(products)} sales_cust={len(sales)}")
print(f"処方箋: 表示={rx_kept}件(うち商品誤登録の警告付き={rx_warned}件) / 除外={rx_dropped}件")
print(f"data size={len(blob)/1024:.0f}KB, html size={len(new)/1024:.0f}KB")
