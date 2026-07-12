#!/usr/bin/env python3
"""検証用のクリーンなサンプルDBを生成する(整合性のあるダミー100件)。

  python3 scripts/make_sample_data.py         # db/tokiwa.db を作り直す
  python3 scripts/make_sample_data.py 100      # 顧客件数を指定

現行データのノイズ(累計と明細の不一致・test商品・処方箋への宝石混入等)を排し、
「累計=購入合計」「ポイント残高=履歴と一致」「売掛=頭金+残高」が必ず合う
筋の通ったデータにする。画面の正しさを検証するための土台。

実データ移行時は、この生成部分を『実データから匿名化して抽出』に差し替えれば、
同じ構造で本番相当のサンプルを作れる。
"""
import os, random, sqlite3, sys, datetime

BASE = os.path.join(os.path.dirname(__file__), "..")
SCHEMA = os.path.join(BASE, "db", "schema.sql")
DB = os.path.join(BASE, "db", "tokiwa.db")

random.seed(20260711)  # 再現性

SURNAMES = [("佐藤", "ｻﾄｳ"), ("鈴木", "ｽｽﾞｷ"), ("高橋", "ﾀｶﾊｼ"), ("田中", "ﾀﾅｶ"), ("伊藤", "ｲﾄｳ"),
            ("渡辺", "ﾜﾀﾅﾍﾞ"), ("山本", "ﾔﾏﾓﾄ"), ("中村", "ﾅｶﾑﾗ"), ("小林", "ｺﾊﾞﾔｼ"), ("加藤", "ｶﾄｳ"),
            ("吉田", "ﾖｼﾀﾞ"), ("山田", "ﾔﾏﾀﾞ"), ("松本", "ﾏﾂﾓﾄ"), ("井上", "ｲﾉｳｴ"), ("木村", "ｷﾑﾗ"),
            ("清水", "ｼﾐｽﾞ"), ("山口", "ﾔﾏｸﾞﾁ"), ("池田", "ｲｹﾀﾞ"), ("橋本", "ﾊｼﾓﾄ"), ("石川", "ｲｼｶﾜ")]
FEMALE = [("花子", "ﾊﾅｺ"), ("美咲", "ﾐｻｷ"), ("由美", "ﾕﾐ"), ("恵子", "ｹｲｺ"), ("京子", "ｷｮｳｺ"),
          ("明美", "ｱｹﾐ"), ("裕子", "ﾕｳｺ"), ("智子", "ﾄﾓｺ"), ("陽子", "ﾖｳｺ"), ("直美", "ﾅｵﾐ"),
          ("さゆり", "ｻﾕﾘ"), ("千夏", "ﾁﾅﾂ"), ("麻衣", "ﾏｲ"), ("綾", "ｱﾔ"), ("優子", "ﾕｳｺ")]
MALE = [("太郎", "ﾀﾛｳ"), ("一郎", "ｲﾁﾛｳ"), ("健一", "ｹﾝｲﾁ"), ("誠", "ﾏｺﾄ"), ("大輔", "ﾀﾞｲｽｹ"),
        ("拓也", "ﾀｸﾔ"), ("浩二", "ｺｳｼﾞ"), ("隆", "ﾀｶｼ"), ("修", "ｵｻﾑ"), ("剛", "ﾂﾖｼ"),
        ("和彦", "ｶｽﾞﾋｺ"), ("博", "ﾋﾛｼ"), ("亮", "ﾘｮｳ"), ("翔", "ｼｮｳ"), ("学", "ﾏﾅﾌﾞ")]
CITIES = ["松本市中央", "松本市島立", "塩尻市広丘", "安曇野市豊科", "諏訪市高島", "岡谷市郷田", "松本市深志"]
STAFF = [("101", "三輪 祐加"), ("102", "簗瀬 智宏"), ("103", "田中 一槻"), ("104", "青木 康子")]

# 宝飾品テンプレ (分類, 品名, 中石, 上代下限, 上代上限)
JEWELRY = [
    ("リング", "Pt900 ダイヤリング", "ダイヤ", 220000, 780000),
    ("リング", "K18 ルビーリング", "ルビー", 120000, 380000),
    ("リング", "Pt950 エメラルドリング", "エメラルド", 260000, 620000),
    ("ネックレス", "Pt ダイヤネックレス", "ダイヤ", 150000, 480000),
    ("ネックレス", "あこや真珠ネックレス", "真珠", 120000, 300000),
    ("ネックレス", "K18 サファイアペンダント", "サファイア", 90000, 260000),
    ("ピアス", "K18 ダイヤピアス", "ダイヤ", 45000, 180000),
    ("ピアス", "あこや真珠ピアス", "真珠", 38000, 120000),
    ("ブレスレット", "K18 テニスブレスレット", "ダイヤ", 180000, 520000),
    ("時計", "機械式腕時計", None, 200000, 900000),
]
FRAMES = [("シャルマン ラインアート XL1483", 47300), ("シャルマン ラインアート XL1061", 44000),
          ("チタンフレーム TX-204", 35200), ("ボストン型フレーム BR-88", 28000)]
LENSES = [("ニコン 1.60非球面 UVカット", 39600), ("HOYA 1.55 室内用累進", 28600),
          ("セイコー 1.67非球面", 33000), ("東海 1.74両面非球面", 52000)]
PURPOSES = ["遠近両用", "中近(室内用)", "遠用", "近用"]


def d(y, m=None, day=None):
    m = m or random.randint(1, 12)
    day = day or random.randint(1, 28)
    return f"{y:04d}-{m:02d}-{day:02d}"


def main():
    n_cust = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(open(SCHEMA, encoding="utf-8").read())
    con.execute("PRAGMA foreign_keys = OFF")
    cur = con.cursor()

    cur.execute("INSERT INTO stores VALUES ('01','本店')")
    for code, name in STAFF:
        cur.execute("INSERT INTO staff(staff_code,name,store_code) VALUES (?,?,'01')", (code, name))

    # ── 商品カタログ(在庫プール) ──
    pkey = 1000
    stock_pool = []          # 販売に回せる在庫宝飾品 [(product_key, name, price)]
    for _ in range(360):     # 売却分を差し引いても在庫が潤沢に残るよう多めに生成
        cat, base, stone, lo, hi = random.choice(JEWELRY)
        price = round(random.randint(lo, hi), -3)
        pkey += 1
        carat = f"{random.uniform(0.2, 1.5):.2f}" if stone in ("ダイヤ", "エメラルド", "ルビー", "サファイア") else None
        cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,
                       state,location,center_stone,center_carat,is_glasses)
                       VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                    (str(pkey), str(pkey), base, cat, price, int(price * 0.55), "在庫",
                     random.choice(["ショーケースA", "ショーケースB", "金庫"]), stone, carat))
        stock_pool.append((str(pkey), base, price))
    # メガネ商品(レンズ・フレーム)
    glass_products = {}
    for name, price in FRAMES + LENSES:
        pkey += 1
        is_lens = (name, price) in LENSES
        cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,
                       state,location,is_glasses) VALUES (?,?,?,?,?,?,?,?,1)""",
                    (str(pkey), str(pkey), name, "メガネ", price, int(price * 0.5), "在庫", "メガネ棚"))
        glass_products[name] = str(pkey)

    FRAME_PRICE = dict(FRAMES)
    LENS_PRICE = dict(LENSES)
    slip = [0]
    rx_seq = [0]
    stats = {"personas": 0, "sales": 0, "receivable": 0, "rx": 0, "families": 0, "approach": 0}

    def add_customer(cid, name, kana, gender, birthday, wedding=None, staff=None, is_test=0, note=None):
        staff = staff or random.choice(STAFF)
        tel = f"0{random.choice(['90','80','70'])}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
        postal = f"39{random.randint(0,9)}-{random.randint(0,9999):04d}"
        addr = "長野県" + random.choice(CITIES) + f"{random.randint(1,9)}-{random.randint(1,20)}-{random.randint(1,30)}"
        addr2 = f"コーポ常盤{random.randint(1,5)}0{random.randint(1,8)}号室" if random.random() < 0.3 else None
        cur.execute("""INSERT INTO customers(customer_id,name,kana,tel,gender,birthday,wedding_day,
                       postal,address,address2,staff_code,staff_name,store_code,dm_ok,registered_at,is_test,note)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'01','可',?,?,?)""",
                    (str(cid), name, kana, tel, gender, birthday, wedding, postal, addr, addr2,
                     staff[0], staff[1], d(random.randint(2014, 2024)), is_test, note))
        return staff

    def add_family(cid, sur, members):
        for fgiv, rel, g in members:
            cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday)
                           VALUES (?,?,?,?,?)""", (str(cid), f"{sur} {fgiv}", rel, g, d(random.randint(1950, 2015))))
        stats["families"] += 1

    def add_approach(cid, staff, entries):
        for dt, kind, title in entries:
            cur.execute("""INSERT INTO approach_history(customer_id,approach_date,kind,title,staff_name)
                           VALUES (?,?,?,?,?)""", (str(cid), dt, kind, title, staff[1]))
        stats["approach"] += 1

    def record_sales(cid, staff, buys, set_balance=True):
        """buys=[(sold,pay,item,amount)]。日付順に売上・在庫引落・ポイント加算・売掛を記録"""
        buys.sort(key=lambda b: b[0])
        added = 0
        for sold, pay, item, amount in buys:
            earned = amount // 200
            slip[0] += 1
            sid = slip[0]
            cur.execute("""INSERT INTO sales_slips(slip_id,slip_no,customer_id,staff_code,staff_name,
                           store_code,sold_at,pay_method,earned_points) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (sid, f"S{sid:06d}", str(cid), staff[0], staff[1], "01", sold, pay, earned))
            cur.execute("INSERT INTO sale_lines(slip_id,product_key,list_price,amount) VALUES (?,?,?,?)",
                        (sid, item[0], item[2], amount))
            cur.execute("UPDATE products SET state='売上' WHERE product_key=?", (item[0],))
            cur.execute("INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id) VALUES (?,?,?,?)",
                        (item[0], "売上引落", -1, sid))
            stats["sales"] += 1
            added += earned
            cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,balance,ref_slip_id,occurred_at)
                           VALUES (?,?,?,?,?,?,?)""", (str(cid), "加算", earned, earned, added, sid, sold))
            if pay == "掛売":
                down = round(amount * random.choice([0.3, 0.5]), -3)
                cur.execute("""INSERT INTO receivables(customer_id,product_key,product_name,bought_at,down_payment,balance,last_paid_at)
                               VALUES (?,?,?,?,?,?,?)""", (str(cid), item[0], item[1], sold, down, amount - down, sold))
                cur.execute("INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid) VALUES (?,?,?,?,?,?)",
                            (str(cid), "掛売", sold, item[1], amount, None))
                cur.execute("INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid) VALUES (?,?,?,?,?,?)",
                            (str(cid), "入金(頭金)", sold, item[1], None, down))
                stats["receivable"] += 1
        if set_balance and added:
            cur.execute("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)",
                        (str(cid), added, d(2026)))
        return added

    def take(n):
        out = []
        for _ in range(n):
            if stock_pool:
                out.append(stock_pool.pop(random.randrange(len(stock_pool))))
        return out

    def add_rx(cid, purpose, sph_r, add, when):
        rx_seq[0] += 1
        fname, fprice = random.choice(FRAMES)
        lname, lprice = random.choice(LENSES)
        pd_far = round(random.uniform(60, 66), 1)      # PDは両眼値が基本
        pd_near = round(pd_far - 3, 1)
        naked = random.choice(["0.1", "0.2", "0.3", "0.5"])
        corrected = random.choice(["1.0", "1.2", "1.5"])
        cur.execute("""INSERT INTO prescriptions
            (customer_id,rx_no,purpose,lens_name,frame_name,lens_key,frame_key,
             sph_r,sph_l,cyl_r,cyl_l,ax_r,ax_l,add_r,add_l,
             pd_far_both,pd_near_both,naked_both,corrected_both,
             total_list,total_sell,handler,rx_date,jewelry_misassign)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (str(cid), f"RX-{rx_seq[0]:04d}", purpose, lname, fname, glass_products[lname], glass_products[fname],
             f"{sph_r:+.2f}", f"{sph_r+0.25:+.2f}", "-0.50", "-0.75", "180", "175", add, add,
             f"{pd_far:.1f}", f"{pd_near:.1f}", naked, corrected,
             lprice + fprice, lprice + fprice, random.choice(STAFF)[1], when))
        stats["rx"] += 1

    # ══ 検証用ペルソナ(名前が用途を表す。顧客管理の「テスト顧客」から呼び出せる)══
    S = STAFF
    # 1) メガネ太郎 — 処方箋確認
    st = add_customer(1, "メガネ 太郎", "ﾒｶﾞﾈ ﾀﾛｳ", "男", d(1968, 3, 3), staff=S[0], is_test=1, note="処方箋確認")
    fk = [(glass_products[f], f, FRAME_PRICE[f]) for f in FRAME_PRICE]
    record_sales(1, st, [("2024-05-10", "現金", fk[0], fk[0][2]), ("2022-09-14", "クレジット", fk[1], fk[1][2])])
    add_rx(1, "遠近両用", -2.25, "+1.50", "2025-09-14")
    add_rx(1, "中近(室内用)", -2.00, "+1.25", "2023-04-02")
    add_rx(1, "遠用", -3.00, "", "2021-06-18")

    # 2) ポイント花子 — ポイント確認(加算+使用、残高が一致)
    st = add_customer(2, "ポイント 花子", "ﾎﾟｲﾝﾄ ﾊﾅｺ", "女", d(1975, 8, 20), staff=S[0], is_test=1, note="ポイント確認")
    # 購入日は全て使用日(2026-06-01)より前にし、時系列で残高が正しく推移するようにする
    pt_dates = ["2021-09-10", "2023-02-01", "2024-07-17", "2025-03-04", "2025-11-20"]
    added = record_sales(2, st, [(dt, "現金", it, it[2]) for dt, it in zip(pt_dates, take(5))], set_balance=False)
    cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,use_points,balance,occurred_at)
                   VALUES (?,?,?,?,?,?)""", ("2", "使用", -1000, 1000, added - 1000, "2026-06-01"))
    cur.execute("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)", ("2", added - 1000, "2026-06-01"))

    # 3) 売掛次郎 — 入金管理(売掛)確認
    st = add_customer(3, "売掛 次郎", "ｳﾘｶｹ ｼﾞﾛｳ", "男", d(1962, 1, 15), staff=S[1], is_test=1, note="入金管理(売掛)確認")
    record_sales(3, st, [("2026-03-05", "掛売", take(1)[0], 560000), ("2025-11-20", "掛売", take(1)[0], 280000)])

    # 4) 購入歴子 — 購入履歴確認(多数・高額)
    st = add_customer(4, "購入 歴子", "ｺｳﾆｭｳ ﾚｷｺ", "女", d(1958, 12, 1), d(1985, 6, 10), staff=S[0], is_test=1, note="購入履歴確認")
    record_sales(4, st, [(d(y), random.choice(["現金", "クレジット"]), it, it[2]) for y, it in zip([2019, 2020, 2021, 2023, 2024, 2026], take(6))])

    # 5) 家族丸 — 家族情報確認
    st = add_customer(5, "家族 丸", "ｶｿﾞｸ ﾏﾙ", "男", d(1965, 2, 20), d(1992, 11, 3), staff=S[2], is_test=1, note="家族情報確認")
    add_family(5, "家族", [("桃子", "妻", "女"), ("一郎", "長男", "男"), ("美咲", "長女", "女"), ("松子", "母", "女")])
    record_sales(5, st, [("2024-11-03", "現金", take(1)[0], 128000)])

    # 6) 新規子 — 新規/空データ確認(履歴なしの見え方)
    add_customer(6, "新規 子", "ｼﾝｷﾞ ｺ", "女", d(1990, 1, 1), staff=S[3], is_test=1, note="新規/空データ確認")

    # 7) 声がけ子 — お声がけ/アプローチ確認(誕生日が近い)
    st = add_customer(7, "声がけ 子", "ｺｴｶｹ ｺ", "女", d(1970, 7, 15), d(2000, 9, 20), staff=S[1], is_test=1, note="お声がけ/アプローチ確認")
    add_approach(7, st, [("2026-06-22", "TEL", "誕生月のご案内"), ("2026-05-10", "DM", "夏の宝飾展 招待状"), ("2026-03-01", "来店", "リング点検・次回記念日を提案")])
    record_sales(7, st, [("2025-09-20", "現金", take(1)[0], 96000)])
    stats["personas"] = 7

    # ══ フィラー顧客(is_test=0)══
    for cid in range(8, n_cust + 1):
        gender = random.choice(["女", "男"])
        sur = random.choice(SURNAMES)
        giv = random.choice(FEMALE if gender == "女" else MALE)
        wedding = d(random.randint(1975, 2020)) if random.random() < 0.5 else None
        st = add_customer(cid, f"{sur[0]} {giv[0]}", f"{sur[1]} {giv[1]}", gender,
                          d(random.randint(1948, 1998)), wedding)
        if random.random() < 0.4:
            fg = random.choice([("妻", "女"), ("長女", "女"), ("長男", "男"), ("母", "女")])
            add_family(cid, sur[0], [(random.choice(FEMALE if fg[1] == "女" else MALE)[0], fg[0], fg[1])])
        n_buy = random.choices([0, 1, 2, 3, 4, 5], weights=[15, 30, 25, 15, 10, 5])[0]
        buys = []
        for it in take(n_buy):
            amount = it[2] - (random.choice([0, 0, 0, 5000, 10000]) if it[2] > 100000 else 0)
            buys.append((d(random.randint(2019, 2026)),
                         random.choices(["現金", "クレジット", "掛売", "PayPay"], weights=[50, 25, 15, 10])[0], it, amount))
        record_sales(cid, st, buys)
        if random.random() < 0.3:
            add_approach(cid, st, [(d(random.randint(2024, 2026)), random.choice(["来店", "DM", "TEL"]),
                                    random.choice(["誕生日のご案内", "宝飾展の招待", "点検のおすすめ"]))])

    # フィラーにも数名メガネ処方箋(ペルソナ以外)
    for cid in random.sample(range(8, n_cust + 1), min(8, max(0, n_cust - 7))):
        add_rx(cid, random.choice(PURPOSES), -round(random.uniform(0.5, 6.0) * 4) / 4,
               random.choice(["", "+1.00", "+1.50"]), d(random.randint(2023, 2026)))

    cur.execute("INSERT INTO schema_migrations(version,note) VALUES (1,'サンプルデータ生成')")
    con.commit()

    # ── 整合性の自己検証 ──
    print(f"== サンプルデータ生成 (顧客{n_cust}件) ==")
    for k, v in stats.items():
        print(f"  {k:12s}: {v}")
    print("\n== 整合性チェック(合っていれば OK) ==")
    # 累計 = 明細合計 は build_blob が明細から算出するので構造的に一致。ここでは代表例を表示
    sample = cur.execute("""
        SELECT c.customer_id, c.name, COUNT(l.line_id) n, COALESCE(SUM(l.amount),0) total
        FROM customers c LEFT JOIN sales_slips s ON s.customer_id=c.customer_id
        LEFT JOIN sale_lines l ON l.slip_id=s.slip_id
        GROUP BY c.customer_id HAVING n>0 ORDER BY total DESC LIMIT 3""").fetchall()
    for r in sample:
        pb = cur.execute("SELECT balance FROM point_balances WHERE customer_id=?", (r[0],)).fetchone()
        ptx = cur.execute("SELECT COALESCE(SUM(add_points-use_points),0) FROM point_transactions WHERE customer_id=?", (r[0],)).fetchone()
        ok = "OK" if (pb and pb[0] == ptx[0]) else "!!"
        print(f"  {r[1]}: 購入{r[2]}件 累計¥{r[3]:,} / pt残高={pb[0] if pb else 0} 履歴合計={ptx[0]} [{ok}]")
    # 売掛の整合性
    bad = cur.execute("""SELECT COUNT(*) FROM receivable_entries WHERE entry_type='掛売'""").fetchone()[0]
    print(f"  売掛発生 {bad}件(各件に頭金入金が対)")
    # 処方箋に宝飾品混入がないこと
    mis = cur.execute("SELECT COUNT(*) FROM prescriptions WHERE jewelry_misassign=1").fetchone()[0]
    print(f"  処方箋への宝飾品混入: {mis}件(0であるべき)")
    print(f"\nDB作成: {DB} ({os.path.getsize(DB)/1024:.0f}KB)")
    con.close()


if __name__ == "__main__":
    main()
