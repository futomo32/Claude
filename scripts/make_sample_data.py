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
        cat = "メガネレンズ" if is_lens else "メガネフレーム"   # フレーム/レンズを分類で区別
        cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,
                       state,location,is_glasses) VALUES (?,?,?,?,?,?,?,?,1)""",
                    (str(pkey), str(pkey), name, cat, price, int(price * 0.5), "在庫", "メガネ棚"))
        glass_products[name] = str(pkey)

    FRAME_PRICE = dict(FRAMES)
    LENS_PRICE = dict(LENSES)
    slip = [0]
    rx_seq = [0]
    repair_seq = [0]
    stats = {"personas": 0, "sales": 0, "receivable": 0, "rx": 0, "families": 0, "approach": 0, "repairs": 0}

    def add_customer(cid, name, kana, gender, birthday, wedding=None, staff=None, is_test=0, note=None):
        staff = staff or random.choice(STAFF)
        tel = f"0{random.choice(['90','80','70'])}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
        postal = f"39{random.randint(0,9)}-{random.randint(0,9999):04d}"
        addr = "長野県" + random.choice(CITIES) + f"{random.randint(1,9)}-{random.randint(1,20)}-{random.randint(1,30)}"
        addr2 = f"コーポ常盤{random.randint(1,5)}0{random.randint(1,8)}号室" if random.random() < 0.3 else None
        cur.execute("""INSERT INTO customers(customer_id,name,kana,tel,gender,birthday,wedding_day,
                       postal,address,address2,staff_code,staff_name,store_code,dm_ok,registered_at,is_test,note)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'01','送る',?,?,?)""",
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
             lens_price,frame_price,total_list,total_sell,handler,rx_date,jewelry_misassign)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (str(cid), f"RX-{rx_seq[0]:04d}", purpose, lname, fname, glass_products[lname], glass_products[fname],
             f"{sph_r:+.2f}", f"{sph_r+0.25:+.2f}", "-0.50", "-0.75", "180", "175", add, add,
             f"{pd_far:.1f}", f"{pd_near:.1f}", naked, corrected,
             lprice, fprice, lprice + fprice, lprice + fprice, random.choice(STAFF)[1], when))
        stats["rx"] += 1

    def add_repair_seed(cid, item_name, issue, estimate, received_at, promised_at, status, staff, note=None):
        repair_seq[0] += 1
        completed_at = promised_at if status == "引渡済み" else None
        cur.execute("""INSERT INTO repairs
            (repair_no,customer_id,item_name,issue,estimate,received_at,promised_at,status,completed_at,staff_name,note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (f"R-{repair_seq[0]:06d}", str(cid), item_name, issue, estimate,
             received_at, promised_at, status, completed_at, staff, note))
        stats["repairs"] += 1

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

    # 8) 修理 実子 — 修理伝票の進捗確認(預かり中/修理中/連絡済み/引渡済み)
    st = add_customer(8, "修理 実子", "ｼｭｳﾘ ﾐﾂｺ", "女", d(1980, 4, 10), staff=S[2], is_test=1, note="修理伝票確認")
    add_repair_seed(8, "ネックレス", "チェーン切れ", 3000, "2026-06-20", "2026-07-11", "連絡済み", S[2][1], "急ぎ希望")
    add_repair_seed(8, "指輪", "サイズ直し(9号→11号)", 2000, "2026-07-05", "2026-07-18", "修理中", S[0][1])
    add_repair_seed(8, "腕時計", "電池交換", 1320, "2026-07-11", "2026-07-11", "預かり中", S[1][1])
    add_repair_seed(8, "ピアス", "キャッチ紛失", 500, "2026-05-01", "2026-05-10", "引渡済み", S[2][1])
    stats["personas"] = 8

    # ══ フィラー顧客(is_test=0)══
    for cid in range(9, n_cust + 1):
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
    for cid in random.sample(range(9, n_cust + 1), min(8, max(0, n_cust - 8))):
        add_rx(cid, random.choice(PURPOSES), -round(random.uniform(0.5, 6.0) * 4) / 4,
               random.choice(["", "+1.00", "+1.50"]), d(random.randint(2023, 2026)))

    # フィラーにも数件の修理伝票(進行中・完了それぞれ)
    REPAIR_ITEMS = [("指輪", "サイズ直し", 2000), ("ネックレス", "チェーン修理", 3500),
                     ("腕時計", "電池交換", 1320), ("ピアス", "キャッチ交換", 800),
                     ("メガネ", "ネジ緩み調整", 500)]
    for cid in random.sample(range(9, n_cust + 1), min(10, max(0, n_cust - 8))):
        item, issue, price = random.choice(REPAIR_ITEMS)
        status = random.choice(["預かり中", "修理中", "連絡済み", "引渡済み"])
        received = d(random.randint(2026, 2026), random.randint(1, 7))
        promised = d(2026, min(random.randint(1, 7) + 1, 12), random.randint(1, 28))
        add_repair_seed(cid, item, issue, price, received, promised, status,
                        random.choice(STAFF)[1])

    # ── 本日(2026-07-11)の営業サンプル(ホーム/日報のデモが空にならないように) ──
    # 実行日を「今日」とする(2026-08-10 変更。固定日付だと本日の日報・ホームタイル・
    # お声がけ・日またぎ返品など「今日」を使う機能がテストできないため)
    TODAY = datetime.date.today().isoformat()

    def record_today(cid, staff, pay, item, amount):
        slip[0] += 1
        sid = slip[0]
        earned = amount // 200
        cur.execute("""INSERT INTO sales_slips(slip_id,slip_no,customer_id,staff_code,staff_name,
                       store_code,sold_at,pay_method,earned_points) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sid, f"S{sid:06d}", str(cid), staff[0], staff[1], "01", TODAY, pay, earned))
        cur.execute("INSERT INTO sale_lines(slip_id,product_key,list_price,amount) VALUES (?,?,?,?)",
                    (sid, item[0], item[2], amount))
        cur.execute("UPDATE products SET state='売上' WHERE product_key=?", (item[0],))
        cur.execute("INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id) VALUES (?,?,?,?)",
                    (item[0], "売上引落", -1, sid))
        row = cur.execute("SELECT balance FROM point_balances WHERE customer_id=?", (str(cid),)).fetchone()
        bal = (row[0] if row else 0) + earned
        cur.execute("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)",
                    (str(cid), bal, TODAY))
        cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,balance,ref_slip_id,occurred_at)
                       VALUES (?,?,?,?,?,?,?)""", (str(cid), "加算", earned, earned, bal, sid, TODAY))
        stats["sales"] += 1

    today_stock = take(3)
    if len(today_stock) == 3:
        record_today(9, STAFF[0], "現金", today_stock[0], today_stock[0][2])
        record_today(10, STAFF[2], "クレジット", today_stock[1], today_stock[1][2])
        record_today(11, STAFF[1], "PayPay", today_stock[2], 6160)
    # 本日の売掛入金(売掛次郎の残高へ一部入金)
    rc = cur.execute("SELECT id,balance FROM receivables WHERE customer_id='3' AND balance>0 ORDER BY balance DESC LIMIT 1").fetchone()
    if rc:
        pay_amt = min(100000, rc[1])
        cur.execute("UPDATE receivables SET balance=balance-?, last_paid_at=? WHERE id=?", (pay_amt, TODAY, rc[0]))
        cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                       VALUES (?,?,?,?,?,?)""", ("3", "入金", TODAY, "売掛入金", None, pay_amt))

    # ── 最終テスト用シナリオ(2026-08-10 追加。v0.34系の新機能・修正の検証用) ──
    # ペルソナ9001〜9008番(ランダム顧客の番号帯と衝突しない)。名前が「何のテスト用か」を表す。全員 is_test=1。
    today_d = datetime.date.today()
    yesterday = (today_d - datetime.timedelta(days=1)).isoformat()

    def mday(offset):
        """今月内で今日からoffset日後の日付(28日を超えないよう丸める)"""
        day = min(28, today_d.day + offset)
        return f"{today_d.year:04d}-{today_d.month:02d}-{day:02d}"

    # §20 お声がけ: 誕生日(今月・今日以降)/結婚記念日/ポイント失効間近/修理納期
    add_customer(9001, "誕生日 未来子", "ﾀﾝｼﾞｮｳﾋﾞ ﾐｷｺ", "女", f"1970-{mday(5)[5:]}",
                 staff=S[0], is_test=1, note="お声がけ確認(今月の誕生日)")
    add_customer(9002, "記念日 夫婦子", "ｷﾈﾝﾋﾞ ﾌｳﾌｺ", "女", d(1965, 1, 10), f"1990-{mday(2)[5:]}",
                 staff=S[1], is_test=1, note="お声がけ確認(今月の結婚記念日)")
    add_customer(9003, "失効 間近子", "ｼｯｺｳ ﾏｼﾞｶｺ", "女", d(1972, 2, 2),
                 staff=S[2], is_test=1, note="お声がけ確認(ポイント失効間近)")
    # 失効日=5日後になるよう最終購入日を逆算(失効=最終購入+5年。表示12件の上位に入れる)
    expiry_target = today_d + datetime.timedelta(days=5)
    try:
        old_buy = expiry_target.replace(year=expiry_target.year - 5).isoformat()
    except ValueError:  # 2/29 対策
        old_buy = expiry_target.replace(year=expiry_target.year - 5, day=28).isoformat()
    cur.execute("""INSERT INTO sales_slips(slip_id,customer_id,staff_name,store_code,sold_at,pay_method)
                   VALUES (9101,'9003',?, '01', ?, '現金')""", (S[2][1], old_buy))
    cur.execute("INSERT INTO sale_lines(slip_id,free_name,amount) VALUES (9101,'昔の指輪',80000)")
    cur.execute("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES ('9003',1200,?)", (old_buy,))
    add_customer(9004, "納期 遅男", "ﾉｳｷ ｵｸﾚｵ", "男", d(1960, 3, 3),
                 staff=S[0], is_test=1, note="お声がけ確認(修理納期・遅れ)")
    add_repair_seed(9004, "ネックレス糸替え", "糸のゆるみ", 2000, yesterday,
                    (today_d - datetime.timedelta(days=2)).isoformat(), "修理中", S[0][1], "納期超過の表示確認")
    add_repair_seed(9004, "指輪サイズ直し", "9号→11号", 3000, yesterday,
                    (today_d + datetime.timedelta(days=3)).isoformat(), "預かり中", S[1][1])
    # §7/§20 DM不可: 死去(ＳＳＳ住所)と「送らない」— ラベル・B2・お声がけに出ないこと
    add_customer(9005, "死去 出ない子", "ｼｷｮ ﾃﾞﾅｲｺ", "女", f"1940-{mday(3)[5:]}",
                 staff=S[1], is_test=1, note="DM不可確認(住所ＳＳＳ・誕生日今月でもお声がけに出ない)")
    cur.execute("UPDATE customers SET address='ＳＳＳ'||address WHERE customer_id='9005'")
    add_customer(9006, "送らない 子", "ｵｸﾗﾅｲ ｺ", "女", f"1955-{mday(4)[5:]}",
                 staff=S[2], is_test=1, note="DM不可確認(区分=送らない)")
    cur.execute("UPDATE customers SET dm_ok='送らない' WHERE customer_id='9006'")
    # §7-9 B2の必須チェック: 電話なし
    add_customer(9007, "電話 なし子", "ﾃﾞﾝﾜ ﾅｼｺ", "女", d(1985, 5, 5),
                 staff=S[0], is_test=1, note="B2確認(電話未登録→除外案内)")
    cur.execute("UPDATE customers SET tel=NULL WHERE customer_id='9007'")
    # §11 日またぎ返品 + §21 保証書(10万以上=A4) + 同番号別商品(v0.34.9の確認):
    #   昨日、同じ商品番号を持つ2商品のうちAをリング15万円で販売。今日取り消すと
    #   「昨日の日報はそのまま・今日にマイナス行」を確認できる。Bは在庫のまま。
    add_customer(9008, "返品 予定子", "ﾍﾝﾋﾟﾝ ﾖﾃｲｺ", "女", d(1978, 6, 6),
                 staff=S[1], is_test=1, note="日またぎ返品確認(昨日の売上を今日取消す)")
    cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,state,center_stone)
                   VALUES ('01-90001','90001','ダイヤリングA(同番号テスト)','宝石',150000,60000,'売上','ダイヤ')""")
    cur.execute("""INSERT INTO products(product_key,product_no,name,category,list_price,cost_price,state,center_stone)
                   VALUES ('01-90002','90001','ルビーリングB(同番号テスト)','宝石',80000,30000,'在庫','ルビー')""")
    cur.execute("""INSERT INTO sales_slips(slip_id,customer_id,staff_name,store_code,sold_at,pay_method)
                   VALUES (9102,'9008',?, '01', ?, '現金')""", (S[1][1], yesterday))
    cur.execute("INSERT INTO sale_lines(slip_id,product_key,list_price,amount) VALUES (9102,'01-90001',150000,150000)")
    cur.execute("INSERT INTO sale_payments(slip_id,method,amount) VALUES (9102,'現金',150000)")
    stats["personas"] += 8

    # ── お声がけのノイズ整理 ──
    # 乱数生成の修理は納期が固定日付のため、実行日によっては全部「納期遅れ」になり、
    # お声がけ(表示12件)をテスト用ペルソナより先に埋め尽くしてしまう。
    # 修理画面の確認用に「修理 実子」(8番)の進行中の修理は納期を未来に寄せて残し、
    # それ以外の古い納期は引渡済みにする。納期遅れの検証は9004(納期 遅男)の1件に集約。
    cur.execute("UPDATE repairs SET promised_at=? WHERE customer_id='8' AND status<>'引渡済み'",
                ((today_d + datetime.timedelta(days=7)).isoformat(),))
    cur.execute("""UPDATE repairs SET status='引渡済み', completed_at=promised_at
                   WHERE customer_id NOT IN ('8','9004') AND promised_at < ? AND status<>'引渡済み'""",
                (TODAY,))

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
    # 修理伝票の状態別件数
    rep_counts = cur.execute("SELECT status, COUNT(*) FROM repairs GROUP BY status").fetchall()
    print("  修理伝票: " + ", ".join(f"{s}{n}件" for s, n in rep_counts))
    print(f"\nDB作成: {DB} ({os.path.getsize(DB)/1024:.0f}KB)")
    con.close()


if __name__ == "__main__":
    main()
