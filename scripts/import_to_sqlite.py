#!/usr/bin/env python3
"""data/demo/ のxlsxを読み、db/schema.sql から db/tokiwa.db を構築して流し込む。

再実行すると tokiwa.db を作り直す(冪等)。移行ロジックの叩き台。
"""
import openpyxl, glob, os, re, sqlite3, unicodedata, datetime

BASE = os.path.join(os.path.dirname(__file__), "..")
DEMO = os.path.join(BASE, "data", "demo")
SCHEMA = os.path.join(BASE, "db", "schema.sql")
DB = os.path.join(BASE, "db", "tokiwa.db")


def wb_rows(key):
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


def s(v):
    if v is None:
        return None
    t = str(v).replace("　", " ").strip()
    return t or None


# 宝飾ナビの「西暦和暦コード」の対応表(実データ移行時の振り分けに使用)
ERA_MAP = {"1": "明治", "2": "大正", "3": "昭和", "4": "平成", "5": "令和"}
ERA_BASE = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def dt(v, era_code=None):
    """日付 → YYYY-MM-DD。和暦表記(「36.5.4」+コード3、「昭和36.5.4」等)は西暦に変換"""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d")
    t = s(v)
    if not t:
        return None
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    era = ERA_MAP.get(s(era_code) or "")
    m = re.match(r"(?:(明治|大正|昭和|平成|令和))?\s*(\d{1,2})[.年/-](\d{1,2})[.月/-]?(\d{1,2})?", t)
    if m and (m.group(1) or era) and m.group(3):
        y = int(m.group(2)) + ERA_BASE[m.group(1) or era]
        return f"{y}-{int(m.group(3)):02d}-{int(m.group(4) or 1):02d}"
    return None


def n(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


JEWELRY_PAT = re.compile(
    r"ﾘﾝｸﾞ|リング|ﾈｯｸﾚｽ|ネックレス|ﾀﾞｲﾔ|ダイヤ|ｻﾌｧｲｱ|ﾋﾟｱｽ|ﾌﾞﾚｽ|ﾍﾟﾝﾀﾞ|ﾒﾉｰ|ﾙﾋﾞｰ|ｴﾒﾗﾙﾄﾞ|ﾊﾟｰﾙ|真珠|指輪|K1[048]|PT|SV")
POWER_COLS = ("SPH(右)", "SPH(左)", "CYL(右)", "CYL(左)", "AX(右)", "AX(左)",
              "ADD(右)", "ADD(左)", "PD遠(両)", "PD近(両)")


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(open(SCHEMA, encoding="utf-8").read())
    # 一括移行中はFKを一旦オフにし(投入順序に依存しないため)、最後に整合性を検査する
    con.execute("PRAGMA foreign_keys = OFF")
    cur = con.cursor()
    log = {}

    # ── マスター(店舗・担当者)を各台帳から収集 ──
    stores, staff = {}, {}
    for r in wb_rows("顧客台帳"):
        sc, sn = s(r.get("店舗コード")), s(r.get("店舗名称"))
        if sc:
            stores[sc] = sn
        stc, stn = s(r.get("担当者コード")), s(r.get("担当者"))
        if stc:
            staff[stc] = (stn, sc)
    cur.executemany("INSERT OR IGNORE INTO stores VALUES (?,?)", list(stores.items()))
    cur.executemany("INSERT OR IGNORE INTO staff(staff_code,name,store_code) VALUES (?,?,?)",
                    [(k, v[0], v[1]) for k, v in staff.items()])
    log["stores"], log["staff"] = len(stores), len(staff)

    # ── 顧客 + メモ ──
    custs, memos = [], []
    seen = set()
    for r in wb_rows("顧客台帳"):
        cid = s(r.get("顧客id"))
        if not cid or cid in seen:
            continue
        seen.add(cid)
        custs.append((
            cid, s(r.get("顧客名")), s(r.get("顧客名(フリガナ)")), s(r.get("顧客tel")), s(r.get("顧客tel2")),
            s(r.get("郵便番号")), s(r.get("住所1")), s(r.get("性別")),
            dt(r.get("生年月日"), r.get("西暦和暦コード")), dt(r.get("結婚記念日"), r.get("結婚西暦和暦コード")),
            s(r.get("顧客ランク")), s(r.get("dm送付有無")), s(r.get("eメール")),
            s(r.get("指1リングサイズ")), s(r.get("ピアス穴有無")),
            s(r.get("担当者コード")), s(r.get("担当者")), s(r.get("店舗コード")), dt(r.get("登録日")),
        ))
        for i in range(1, 11):
            body = s(r.get(f"顧客メモ{i:02d}"))
            if body:
                memos.append((cid, i, body, dt(r.get("顧客メモ処理日"))))
    cur.executemany("""INSERT INTO customers
      (customer_id,name,kana,tel,tel2,postal,address,gender,birthday,wedding_day,
       rank,dm_ok,email,ring_size,pierce,staff_code,staff_name,store_code,registered_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", custs)
    cur.executemany("INSERT INTO customer_memos(customer_id,seq,body,updated_at) VALUES (?,?,?,?)", memos)
    log["customers"], log["memos"] = len(custs), len(memos)

    # ── 家族(存在する顧客のみ) ──
    fam = []
    for r in wb_rows("家族台帳"):
        cid = s(r.get("顧客id"))
        if cid in seen:
            fam.append((cid, s(r.get("家族名")), s(r.get("続柄")), s(r.get("性別")), dt(r.get("生年月日"))))
    cur.executemany("INSERT INTO customer_families(customer_id,name,relation,gender,birthday) VALUES (?,?,?,?,?)", fam)
    log["families"] = len(fam)

    # ── 商品 ──
    prods, pseen = [], set()
    for r in wb_rows("商品台帳"):
        pk = s(r.get("商品キー"))
        if not pk or pk in pseen:
            continue
        pseen.add(pk)
        prods.append((
            pk, s(r.get("商品番号")), s(r.get("商品名")), s(r.get("商品情報")), s(r.get("大分類名")),
            s(r.get("仕入れ先名称")), n(r.get("仕入単価")), n(r.get("上代価格")), s(r.get("状態区分")),
            s(r.get("保管場所(店舗名称)")), s(r.get("中石名称")), s(r.get("中石重量")),
            s(r.get("color名称")), s(r.get("clarity名称")), s(r.get("cut名称")), s(r.get("鑑別書no")),
            1 if s(r.get("メガネ商品")) == "メガネ" else 0, dt(r.get("登録日")),
        ))
    cur.executemany("""INSERT INTO products
      (product_key,product_no,name,info,category,supplier,cost_price,list_price,state,
       location,center_stone,center_carat,color,clarity,cut,cert_no,is_glasses,registered_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", prods)
    log["products"] = len(prods)

    # ── 売上: 販売台帳を伝票ヘッダ+明細に分割 ──
    #   グループキー = 伝票番号(空欄は 顧客id+販売日+連番 で合成)
    slips, lines = {}, []
    synth = 0
    for r in wb_rows("販売台帳"):
        cid = s(r.get("顧客id"))
        slip_no = s(r.get("伝票番号"))
        sold = dt(r.get("販売日"))
        if slip_no:
            gkey = "N:" + slip_no
        else:
            synth += 1
            gkey = f"S:{cid}:{sold}:{synth}"
        if gkey not in slips:
            slips[gkey] = dict(
                slip_no=slip_no, customer_id=cid if cid in seen else None,
                staff_code=s(r.get("担当/販売者コード")), staff_name=s(r.get("担当/販売者")),
                store_code=s(r.get("販売店舗コード")), sold_at=sold,
                pay_method=s(r.get("掛売区分/種別")), credit_kind=s(r.get("クレジット種別区分")),
                motive=s(r.get("購入動機")), place=s(r.get("購入場所")),
                used=n(r.get("使用ポイント")) or 0, earned=n(r.get("加算ポイント")) or 0,
                lines=[])
        pk = s(r.get("商品キー"))
        slips[gkey]["lines"].append((
            pk if pk in pseen else None,
            None if pk in pseen else s(r.get("商品名")),
            s(r.get("商品情報")), n(r.get("定価")), n(r.get("販売価格/買上金額")),
            n(r.get("消費税")), s(r.get("割引率")),
        ))
    for gk, sl in slips.items():
        cur.execute("""INSERT INTO sales_slips
          (slip_no,customer_id,staff_code,staff_name,store_code,sold_at,pay_method,credit_kind,motive,place,used_points,earned_points)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          (sl["slip_no"], sl["customer_id"], sl["staff_code"], sl["staff_name"], sl["store_code"],
           sl["sold_at"], sl["pay_method"], sl["credit_kind"], sl["motive"], sl["place"], sl["used"], sl["earned"]))
        sid = cur.lastrowid
        for ln in sl["lines"]:
            rate = None
            try:
                rate = float(str(ln[6]).replace("%", "")) if ln[6] else None
            except ValueError:
                rate = None
            cur.execute("""INSERT INTO sale_lines
              (slip_id,product_key,free_name,info,list_price,amount,tax,discount_rate)
              VALUES (?,?,?,?,?,?,?,?)""",
              (sid, ln[0], ln[1], ln[2], ln[3], ln[4], ln[5], rate))
    log["slips"], log["lines"], log["synth_slips"] = len(slips), sum(len(v["lines"]) for v in slips.values()), synth

    # ── 売掛 ──
    recv, recve = [], []
    for r in wb_rows("売掛台帳"):
        cid = s(r.get("顧客id"))
        if cid in seen:
            recv.append((cid, s(r.get("商品キー")), s(r.get("商品名")), dt(r.get("買上日付")),
                         n(r.get("頭金")), n(r.get("残高")), dt(r.get("最終入金日付"))))
    for r in wb_rows("売掛履歴"):
        cid = s(r.get("顧客id"))
        if cid in seen:
            recve.append((cid, s(r.get("売掛処理区分")), dt(r.get("日付")), s(r.get("商品名")),
                          n(r.get("購入金額")), n(r.get("入金・頭金")), s(r.get("備考１"))))
    cur.executemany("""INSERT INTO receivables(customer_id,product_key,product_name,bought_at,down_payment,balance,last_paid_at)
                       VALUES (?,?,?,?,?,?,?)""", recv)
    cur.executemany("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid,note)
                       VALUES (?,?,?,?,?,?,?)""", recve)
    log["receivables"], log["receivable_entries"] = len(recv), len(recve)

    # ── ポイント(取引 + 残高) ──
    ptx, pbal = [], []
    for r in wb_rows("ポイント台帳"):
        cid = s(r.get("顧客id"))
        if cid in seen:
            pbal.append((cid, n(r.get("現残ポイント")) or 0, dt(r.get("更新日")) or dt(r.get("処理日付"))))
    for r in wb_rows("ポイントカード履歴"):
        cid = s(r.get("顧客id"))
        if cid in seen:
            add, use = n(r.get("付与・加算ポイント数")) or 0, n(r.get("使用ポイント数")) or 0
            ptx.append((cid, s(r.get("ポイント付与区分")), add - use, add, use,
                        n(r.get("残ポイント数")), s(r.get("商品名")), dt(r.get("処理日付"))))
    cur.executemany("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,use_points,balance,product_name,occurred_at)
                       VALUES (?,?,?,?,?,?,?,?)""", ptx)
    cur.executemany("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)", pbal)
    log["point_tx"], log["point_balances"] = len(ptx), len(pbal)

    # ── アプローチ履歴 ──
    ap = []
    for r in wb_rows("アプローチ履歴"):
        cid = s(r.get("顧客id"))
        if cid in seen:
            ap.append((cid, dt(r.get("アプローチ日(登録日)")), s(r.get("アプローチ内容")),
                       s(r.get("メッセージタイトル")), s(r.get("担当者"))))
    cur.executemany("""INSERT INTO approach_history(customer_id,approach_date,kind,title,staff_name)
                       VALUES (?,?,?,?,?)""", ap)
    log["approach"] = len(ap)

    # ── 処方箋(宝飾品誤登録の判定つき) ──
    item_flag = {s(r.get("商品キー")): s(r.get("メガネ商品")) for r in wb_rows("商品台帳")}
    rx, rx_drop = [], 0
    for r in wb_rows("処方箋"):
        cid = s(r.get("顧客id"))
        if cid not in seen:
            continue
        has_power = any(s(r.get(k)) for k in POWER_COLS)
        misassign = False
        is_glasses = False
        for id_col, name_col in (("商品ID(レンズ)", "商品名(レンズ)"), ("商品ID(フレーム)", "商品名(フレーム)")):
            fl = item_flag.get(s(r.get(id_col)), None)
            name = s(r.get(name_col)) or ""
            if fl == "メガネ":
                is_glasses = True
            if fl == "宝石・時計" or JEWELRY_PAT.search(name):
                misassign = True
        if not is_glasses and not has_power:
            rx_drop += 1
            continue
        rx.append((
            cid, s(r.get("処方箋No.")), s(r.get("用途名称")),
            s(r.get("商品名(レンズ)")), s(r.get("商品名(フレーム)")),
            s(r.get("商品ID(レンズ)")), s(r.get("商品ID(フレーム)")),
            s(r.get("SPH(右)")), s(r.get("SPH(左)")), s(r.get("CYL(右)")), s(r.get("CYL(左)")),
            s(r.get("AX(右)")), s(r.get("AX(左)")), s(r.get("ADD(右)")), s(r.get("ADD(左)")),
            s(r.get("PD遠(右)")), s(r.get("PD遠(左)")), s(r.get("PD遠(両)")),
            s(r.get("PD近(右)")), s(r.get("PD近(左)")), s(r.get("PD近(両)")),
            n(r.get("合計定価")), n(r.get("合計売値")), s(r.get("対応者名")), dt(r.get("処理日付")),
            1 if misassign else 0,
        ))
    cur.executemany("""INSERT INTO prescriptions
      (customer_id,rx_no,purpose,lens_name,frame_name,lens_key,frame_key,
       sph_r,sph_l,cyl_r,cyl_l,ax_r,ax_l,add_r,add_l,
       pd_far_r,pd_far_l,pd_far_both,pd_near_r,pd_near_l,pd_near_both,
       total_list,total_sell,handler,rx_date,jewelry_misassign)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rx)
    log["prescriptions"], log["rx_dropped"] = len(rx), rx_drop

    cur.execute("INSERT INTO schema_migrations(version,note) VALUES (1,'初期スキーマ+デモデータ移行')")
    con.commit()

    # ── 検証: 集計クエリ ──
    print("== 取り込み件数 ==")
    for k, v in log.items():
        print(f"  {k:20s}: {v:,}")

    # ── 参照整合性チェック(孤立データの検出) ──
    violations = cur.execute("PRAGMA foreign_key_check").fetchall()
    print(f"\n== 参照整合性 ==")
    if violations:
        from collections import Counter
        vc = Counter((v[0], v[2]) for v in violations)
        print(f"  孤立参照 {len(violations):,}件(移行時に要確認):")
        for (tbl, parent), cnt in vc.most_common():
            print(f"    {tbl} → {parent}: {cnt:,}件")
    else:
        print("  問題なし")
    print("\n== 検証クエリ ==")
    for label, sql in [
        ("在庫状態の商品数", "SELECT state, COUNT(*) FROM products GROUP BY state ORDER BY 2 DESC"),
        ("売上明細から算出した購入額上位3顧客",
         """SELECT c.customer_id, c.name, SUM(l.amount) tot
            FROM sale_lines l JOIN sales_slips s ON l.slip_id=s.slip_id
            JOIN customers c ON s.customer_id=c.customer_id
            WHERE l.amount IS NOT NULL GROUP BY c.customer_id ORDER BY tot DESC LIMIT 3"""),
        ("宝飾品が誤登録された処方箋", "SELECT COUNT(*) FROM prescriptions WHERE jewelry_misassign=1"),
    ]:
        print(f"[{label}]")
        for row in cur.execute(sql):
            print("   ", row)
    con.close()
    print(f"\nDB作成: {DB} ({os.path.getsize(DB)/1024/1024:.1f}MB)")


if __name__ == "__main__":
    main()
