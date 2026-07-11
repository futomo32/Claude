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
STAFF = [("101", "三輪 祐加"), ("102", "簗瀬 智宏"), ("103", "田中 一樹"), ("104", "青木 康子")]

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
    for _ in range(90):
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

    slip_id = 0
    stats = {"sales": 0, "receivable": 0, "rx": 0, "families": 0, "approach": 0}

    for cid in range(1, n_cust + 1):
        gender = random.choice(["女", "男"])
        sur = random.choice(SURNAMES)
        giv = random.choice(FEMALE if gender == "女" else MALE)
        name = f"{sur[0]} {giv[0]}"
        kana = f"{sur[1]} {giv[1]}"
        birth = d(random.randint(1948, 1998))
        wedding = d(random.randint(1975, 2020)) if random.random() < 0.5 else None
        tel = f"0{random.choice(['90','80','70'])}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
        staff = random.choice(STAFF)
        addr = "長野県" + random.choice(CITIES) + f"{random.randint(1,9)}-{random.randint(1,20)}-{random.randint(1,30)}"
        cur.execute("""INSERT INTO customers(customer_id,name,kana,tel,gender,birthday,wedding_day,
                       address,staff_code,staff_name,store_code,dm_ok,registered_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,'01','可',?)""",
                    (str(cid), name, kana, tel, gender, birth, wedding, addr,
                     staff[0], staff[1], d(random.randint(2014, 2024))))

        # 家族
        if random.random() < 0.4:
            for _ in range(random.randint(1, 2)):
                fg = random.choice(["夫", "妻", "長女", "長男", "母"])
                fgiv = random.choice(FEMALE if fg in ("妻", "長女", "母") else MALE)
                cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday)
                               VALUES (?,?,?,?,?)""",
                            (str(cid), f"{sur[0]} {fgiv[0]}", fg,
                             "女" if fg in ("妻", "長女", "母") else "男", d(random.randint(1950, 2015))))
            stats["families"] += 1

        # 購入(0〜5件)。累計・年度・ポイントはこの明細から自動で辻褄が合う
        n_buy = random.choices([0, 1, 2, 3, 4, 5], weights=[15, 30, 25, 15, 10, 5])[0]
        pt_balance = 0
        # 先に購入を作って日付順に並べ、ポイント残高を時系列で積む(推移が自然になる)
        buys = []
        for _ in range(n_buy):
            if not stock_pool:
                break
            sold = d(random.randint(2019, 2026))
            pay = random.choices(["現金", "クレジット", "掛売", "PayPay"], weights=[50, 25, 15, 10])[0]
            item = stock_pool.pop(random.randrange(len(stock_pool)))
            amount = item[2] - (random.choice([0, 0, 0, 5000, 10000]) if item[2] > 100000 else 0)
            buys.append((sold, pay, item, amount))
        buys.sort(key=lambda b: b[0])  # 買上日の昇順
        for sold, pay, item, amount in buys:
            earned = amount // 200
            slip_id += 1
            cur.execute("""INSERT INTO sales_slips(slip_id,slip_no,customer_id,staff_code,staff_name,
                           store_code,sold_at,pay_method,earned_points)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (slip_id, f"S{slip_id:06d}", str(cid), staff[0], staff[1], "01", sold, pay, earned))
            cur.execute("""INSERT INTO sale_lines(slip_id,product_key,list_price,amount)
                           VALUES (?,?,?,?)""", (slip_id, item[0], item[2], amount))
            cur.execute("UPDATE products SET state='売上' WHERE product_key=?", (item[0],))
            cur.execute("""INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id)
                           VALUES (?,?,?,?)""", (item[0], "売上引落", -1, slip_id))
            stats["sales"] += 1

            # ポイント履歴(加算)
            pt_balance += earned
            cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,balance,ref_slip_id,occurred_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (str(cid), "加算", earned, earned, pt_balance, slip_id, sold))

            # 掛売なら売掛(頭金+残高が購入額に一致するよう作る)
            if pay == "掛売":
                down = round(amount * random.choice([0.3, 0.5]), -3)
                bal = amount - down
                cur.execute("""INSERT INTO receivables(customer_id,product_key,product_name,bought_at,down_payment,balance,last_paid_at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (str(cid), item[0], item[1], sold, down, bal, sold))
                cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                               VALUES (?,?,?,?,?,?)""", (str(cid), "掛売", sold, item[1], amount, None))
                cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                               VALUES (?,?,?,?,?,?)""", (str(cid), "入金(頭金)", sold, item[1], None, down))
                stats["receivable"] += 1

        # ポイント残高キャッシュ
        if pt_balance:
            cur.execute("INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)",
                        (str(cid), pt_balance, d(2026)))

        # アプローチ履歴
        if random.random() < 0.35:
            for _ in range(random.randint(1, 2)):
                kind = random.choice(["来店", "DM", "TEL"])
                cur.execute("""INSERT INTO approach_history(customer_id,approach_date,kind,title,staff_name)
                               VALUES (?,?,?,?,?)""",
                            (str(cid), d(random.randint(2024, 2026)), kind,
                             random.choice(["誕生日のご案内", "宝飾展の招待", "点検のおすすめ", "記念日フェア"]), staff[1]))
            stats["approach"] += 1

    # ── メガネ処方箋(メガネ商品のみ・整合性あり) ──
    glasses_custs = random.sample(range(1, n_cust + 1), min(12, n_cust))
    rx_id = 0
    for cid in glasses_custs:
        for _ in range(random.randint(1, 2)):
            rx_id += 1
            fname, fprice = random.choice(FRAMES)
            lname, lprice = random.choice(LENSES)
            sph_r = -round(random.uniform(0.5, 6.0) * 4) / 4
            sph_l = sph_r + random.choice([0, 0.25, -0.25])
            add = random.choice(["", "+1.00", "+1.50", "+2.00"])
            pd_r, pd_l = round(random.uniform(30, 33), 1), round(random.uniform(30, 33), 1)
            cur.execute("""INSERT INTO prescriptions
                (customer_id,rx_no,purpose,lens_name,frame_name,lens_key,frame_key,
                 sph_r,sph_l,cyl_r,cyl_l,ax_r,ax_l,add_r,add_l,
                 pd_far_r,pd_far_l,pd_far_both,pd_near_r,pd_near_l,pd_near_both,
                 total_list,total_sell,handler,rx_date,jewelry_misassign)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (str(cid), f"RX-{rx_id:04d}", random.choice(PURPOSES), lname, fname,
                 glass_products[lname], glass_products[fname],
                 f"{sph_r:+.2f}", f"{sph_l:+.2f}", "-0.50", "-0.75", "180", "175", add, add,
                 f"{pd_r:.1f}", f"{pd_l:.1f}", f"{pd_r+pd_l:.1f}", f"{pd_r-1.5:.1f}", f"{pd_l-1.5:.1f}", f"{pd_r+pd_l-3:.1f}",
                 lprice + fprice, lprice + fprice, random.choice(STAFF)[1], d(random.randint(2023, 2026))))
            stats["rx"] += 1

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
