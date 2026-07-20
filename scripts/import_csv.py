#!/usr/bin/env python3
"""宝飾ナビの全CSVダンプ(114テーブル)を読み、db/tokiwa.db を構築する(フルCSV移行)。

  python3 scripts/import_csv.py            # data/real/csv を移行(本番)
  python3 scripts/import_csv.py --demo     # data/demo_csv で予行演習
  python3 scripts/import_csv.py <フォルダ> # 任意フォルダのcsvを移行

主キーは複合(店コード+ID)を "店-ID" 形式に。m_* マスタでコードを名前解決する。
再実行で tokiwa.db を作り直す(冪等)。data/real/ は .gitignore 済み(PC内のみ)。
設計は docs/csv-migration-design.md を参照。
"""
import csv
import datetime
import glob
import os
import re
import sqlite3
import sys

csv.field_size_limit(10 * 1024 * 1024)

BASE = os.path.join(os.path.dirname(__file__), "..")
SCHEMA = os.path.join(BASE, "db", "schema.sql")
DB = os.path.join(BASE, "db", "tokiwa.db")
SRC = os.path.join(BASE, "data", "real", "csv")
BATCH = 5000


# ── CSV読み込み(utf-8-sig優先。宝飾ナビのダンプはBOM付きUTF-8) ──
def _open(name):
    path = os.path.join(SRC, name if name.endswith(".csv") else name + ".csv")
    if not os.path.exists(path):
        return None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            f = open(path, "r", encoding=enc, newline="")
            f.readline()
            f.seek(0)
            return f
        except UnicodeDecodeError:
            f.close()
    return open(path, "r", encoding="cp932", errors="replace", newline="")


def rows(name):
    """CSVを1行ずつ dict で返すジェネレータ(メモリ節約。大きい表対応)。"""
    f = _open(name)
    if f is None:
        return
    try:
        for row in csv.DictReader(f):
            yield row
    finally:
        f.close()


def lookup(name, code_col, name_col):
    """m_* を {コード: 名前} の辞書に。"""
    d = {}
    for r in rows(name):
        c = s(r.get(code_col))
        if c is not None:
            d[c] = s(r.get(name_col))
    return d


# ── 値の正規化 ──
def s(v):
    if v is None:
        return None
    t = str(v).replace("　", " ").strip()
    return t or None


def pick(r, *keys):
    """複数の候補列名から最初に値のある列を返す(宝飾ナビの列名ゆらぎ吸収用)。
    例: 商品のブランドコード列名がstrbrcode/strbrandcodeのどちらか不明な場合に両方試す。"""
    for k in keys:
        v = s(r.get(k))
        if v:
            return v
    return None


def n(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return None


ERA_BASE = {"M": 1867, "T": 1911, "S": 1925, "H": 1988, "R": 2018,
            "明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def dt(v):
    """日付文字列 → YYYY-MM-DD。西暦/和暦(H29.12.1 等)に対応。拾えなければNULL。"""
    t = s(v)
    if not t:
        return None
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"([MTSHR明大昭平令][治正和成]?)\.?\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
    if m:
        base = ERA_BASE.get(m.group(1)) or ERA_BASE.get(m.group(1)[:1])
        if base:
            return f"{base + int(m.group(2))}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"
    return None


def cid_of(r, tc="strkotencode", kc="lngkokey"):
    t, k = s(r.get(tc)), s(r.get(kc))
    return f"{t}-{k}" if t and k else None


def pk_of(r, tc="strsytencode", kc="lngsykey"):
    t, k = s(r.get(tc)), s(r.get(kc))
    return f"{t}-{k}" if t and k else None


# 区分コード→名前(実データのxlsxから diag_kubun.py で抽出した正解対応表 2026-07-15)
SEX = {"1": "女", "2": "男"}
PIERCE = {"1": "有", "2": "無"}
DM = {"1": "送る", "2": "送らない"}
STATE = {"0": "受託", "1": "在庫", "3": "売上", "5": "返品"}
KAKE = {"1": "現金", "2": "掛売", "3": "クレジット", "4": "分割",
        "5": "クレジットローン", "6": "トレジャリーカード"}  # 0=未指定(None)
CREDIT = {"1": "JCB", "2": "VISA", "3": "UFJミリオン", "7": "TS3",
          "8": "セディナ", "9": "オリエント", "A": "山陰信販", "B": "オリコ"}
YOTO = {"1": "常用", "2": "遠用", "3": "近用"}  # 処方箋の用途区分
ZOKUGARA = {"0": "本人", "1": "父", "2": "母", "3": "夫", "4": "妻",
            "5": "長男", "6": "次男", "7": "長女", "8": "次女", "9": "他"}  # m_kubun種別013


def main():
    global SRC
    args = sys.argv[1:]
    if "--demo" in args:
        SRC = os.path.join(BASE, "data", "demo_csv")
        args.remove("--demo")
    if args:
        SRC = args[0]
    if not os.path.isdir(SRC) or not glob.glob(os.path.join(SRC, "*.csv")):
        print(f"[エラー] csv が見つかりません: {SRC}")
        print("  実データを data/real/csv/ に置いてから実行(予行演習は --demo)。")
        sys.exit(1)
    print(f"読み込み元: {SRC}\n")

    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(open(SCHEMA, encoding="utf-8").read())
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("PRAGMA synchronous = OFF")
    con.execute("PRAGMA journal_mode = MEMORY")
    cur = con.cursor()
    log = {}

    # ── マスタ辞書 ──
    m_tan = lookup("m_tantou", "strtancode", "strtanname")
    m_tan_store = {s(r.get("strtancode")): s(r.get("strtencode")) for r in rows("m_tantou")}
    m_brand = lookup("m_brand", "strbrcode", "strbrname")
    m_ishi = lookup("m_ishi", "striscode", "strisname")
    m_jigane = lookup("m_jigane", "strjicode", "strjiname")
    m_douki = lookup("m_douki", "strdocode", "strdoname")
    m_basyo = lookup("m_basyo", "strbacode", "strbaname")
    m_tiku = lookup("m_tiku", "strtikucode", "strtikuname")
    m_dbun = lookup("m_dbunrui", "strdbuncode", "strdbunname")
    m_sir = lookup("m_siiresaki", "strsircode", "strsirname")

    # ── 店舗 stores(m_stor) ──
    stores = []
    for r in rows("m_stor"):
        tc = s(r.get("strtencode"))
        if tc:
            stores.append((tc, s(r.get("strtenname")) or tc))
    cur.executemany("INSERT OR IGNORE INTO stores VALUES (?,?)", stores)
    log["stores"] = len(stores)

    # ── 担当者 staff(m_tantou) ──
    staff = [(c, nm or c, m_tan_store.get(c)) for c, nm in m_tan.items() if c]
    cur.executemany("INSERT OR IGNORE INTO staff(staff_code,name,store_code) VALUES (?,?,?)", staff)
    log["staff"] = len(staff)

    # ── 顧客 customers(d_user) ──
    cust, seen = [], set()
    for r in rows("d_user"):
        cid = cid_of(r)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        tan = s(r.get("strtancode"))
        cust.append((
            cid, s(r.get("strkoname")), s(r.get("strkokana")),
            s(r.get("strkotel")), s(r.get("strtel2")), s(r.get("strkopos")),
            s(r.get("strkojyu1")), s(r.get("strkojyu2")),
            SEX.get(s(r.get("strsexkbn")), s(r.get("strsexkbn"))),
            dt(r.get("datbirthday")), dt(r.get("datwedddate")),
            s(r.get("strrank")), m_tiku.get(pick(r, "strtikucode", "strtiku", "strchikucode")),  # 地区(m_tiku)
            DM.get(s(r.get("strdmkbn")), s(r.get("strdmkbn"))),
            s(r.get("strpcmail")) or s(r.get("strkeitaimail")),
            s(r.get("lngfinsize1")), PIERCE.get(s(r.get("strpiasukbn")), s(r.get("strpiasukbn"))),
            tan, m_tan.get(tan), s(r.get("strkanritenpo")) or s(r.get("strkotencode")),
            dt(r.get("dattoudate")),
        ))
    cur.executemany("""INSERT INTO customers
      (customer_id,name,kana,tel,tel2,postal,address,address2,gender,birthday,wedding_day,
       rank,district,dm_ok,email,ring_size,pierce,staff_code,staff_name,store_code,registered_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", cust)
    log["customers"] = len(cust)

    # 顧客メモ(d_user_memo: memo01〜10) ──
    memos = []
    for r in rows("d_user_memo"):
        cid = cid_of(r)
        if cid not in seen:
            continue
        for i in range(1, 11):
            b = s(r.get(f"strmemo{i:02d}"))
            if b:
                memos.append((cid, i, b, dt(r.get("datinpdate"))))
    cur.executemany("INSERT INTO customer_memos(customer_id,seq,body,updated_at) VALUES (?,?,?,?)", memos)
    log["memos"] = len(memos)

    # ── 家族(d_famiry) ──
    fam = []
    for r in rows("d_famiry"):
        cid = cid_of(r)
        if cid in seen:
            zoku = s(r.get("strzokukbn"))
            fam.append((cid, s(r.get("strfamiryname")), ZOKUGARA.get(zoku, zoku),
                        SEX.get(s(r.get("strsexkbn")), s(r.get("strsexkbn"))), dt(r.get("datbirthday"))))
    cur.executemany("INSERT INTO customer_families(customer_id,name,relation,gender,birthday) VALUES (?,?,?,?,?)", fam)
    log["families"] = len(fam)

    # ── 商品(d_item) ── 大きいのでバッチ投入
    pseen = set()
    prod_names = {}     # 商品キー→商品名(処方箋のレンズ/フレーム名解決に使う)
    prod_is_glass = {}  # 商品キー→メガネ商品か(処方箋の宝飾誤登録判定に使う)
    buf, cnt = [], 0
    # 不明在庫などの削除リスト(商品番号を1行ずつ書いたテキスト)。あれば該当商品を取り込まない。
    # 置き場所: data/real/削除商品番号.txt (SRC=data/real/csv の一つ上)。#で始まる行はコメント。
    del_nos = set()
    del_path = os.path.join(SRC, "..", "削除商品番号.txt")
    if os.path.exists(del_path):
        with open(del_path, encoding="utf-8") as f:
            for line in f:
                v = line.strip()
                if v and not v.startswith("#"):
                    del_nos.add(v)
    skipped_del = 0
    ins_prod = """INSERT INTO products
      (product_key,product_no,name,info,category,brand,metal,supplier,cost_price,list_price,state,
       location,center_stone,center_carat,color,clarity,cut,cert_no,is_glasses,registered_at,image_file)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    for r in rows("d_item"):
        pk = pk_of(r)
        if not pk or pk in pseen:
            continue
        if del_nos and s(r.get("strsyno")) in del_nos:
            skipped_del += 1  # 削除リストの商品番号 → 取り込まない
            continue
        pseen.add(pk)
        cat = m_dbun.get(s(r.get("strdbuncode")))
        name = s(r.get("strsyname")) or ""
        prod_names[pk] = name
        is_glass = 1 if (cat and re.search(r"メガネ|眼鏡|レンズ|フレーム", cat)) or \
                        re.search(r"メガネ|眼鏡|ﾒｶﾞﾈ|ﾚﾝｽﾞ|ﾌﾚｰﾑ", name) else 0
        prod_is_glass[pk] = is_glass
        buf.append((
            pk, s(r.get("strsyno")), name, s(r.get("strsyinfo")), cat,
            m_brand.get(pick(r, "strbrcode", "strbrandcode", "strbrand")),   # ブランド(m_brand)
            m_jigane.get(pick(r, "strjicode", "strjiganecode", "strjigane")),  # 地金(m_jigane)
            m_sir.get(s(r.get("strsirsakicode"))), n(r.get("curorokin")), n(r.get("curkoukin")),
            STATE.get(s(r.get("strjotaikbn")), s(r.get("strjotaikbn"))), s(r.get("strhotencode")),
            m_ishi.get(s(r.get("striscode"))), s(r.get("curmainjuryo")),
            s(r.get("strcolcode")), s(r.get("strclacode")), s(r.get("strcutcode")),
            s(r.get("strkanbno")), is_glass, dt(r.get("dattoudate")),
            os.path.basename((s(r.get("strpicfilename")) or "").replace("\\", "/")) or None,
        ))
        if len(buf) >= BATCH:
            cur.executemany(ins_prod, buf)
            cnt += len(buf)
            buf = []
    if buf:
        cur.executemany(ins_prod, buf)
        cnt += len(buf)
    log["products"] = cnt
    if del_nos:
        log["products_skipped(削除リスト)"] = skipped_del

    # ── 売上: d_hanbai を伝票(curdenpyono)でヘッダ+明細に分割 ──
    # 伝票番号→slip_id を確保しつつ、明細をバッチ投入
    slip_id_of = {}
    synth = 0
    line_buf = []
    ins_line = """INSERT INTO sale_lines
      (slip_id,product_key,free_name,info,list_price,amount,tax,discount_rate) VALUES (?,?,?,?,?,?,?,?)"""
    n_lines = 0
    for r in rows("d_hanbai"):
        cid = cid_of(r)
        dp = s(r.get("curdenpyono"))
        sold = dt(r.get("datkaidate")) or dt(r.get("datcredate"))
        if dp:
            gkey = "N:" + dp
        else:
            synth += 1
            gkey = f"S:{cid}:{sold}:{synth}"
        if gkey not in slip_id_of:
            cur.execute("""INSERT INTO sales_slips
              (slip_no,customer_id,staff_code,staff_name,store_code,sold_at,pay_method,credit_kind,motive,place,used_points,earned_points)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
              (dp, cid if cid in seen else None, s(r.get("strhantancode")),
               m_tan.get(s(r.get("strhantancode"))), s(r.get("strkotencode")), sold,
               KAKE.get(s(r.get("strkakekbn"))), CREDIT.get(s(r.get("strcrekbn")), s(r.get("strcrekbn"))),
               m_douki.get(s(r.get("strdocode"))), m_basyo.get(s(r.get("strbacode"))),
               n(r.get("curusepoint")) or 0, n(r.get("curkasanpoint")) or 0))
            slip_id_of[gkey] = cur.lastrowid
        pk = pk_of(r)
        rate = None
        try:
            rate = float(str(r.get("curwariritu")).replace("%", "")) if s(r.get("curwariritu")) else None
        except ValueError:
            rate = None
        line_buf.append((
            slip_id_of[gkey], pk if pk in pseen else None,
            None if pk in pseen else s(r.get("strkokname")), s(r.get("strsyinfo")),
            n(r.get("curteika")), n(r.get("curkaikin")), n(r.get("curkaizeikin")), rate))
        if len(line_buf) >= BATCH:
            cur.executemany(ins_line, line_buf)
            n_lines += len(line_buf)
            line_buf = []
    if line_buf:
        cur.executemany(ins_line, line_buf)
        n_lines += len(line_buf)
    log["slips"], log["lines"], log["synth_slips"] = len(slip_id_of), n_lines, synth

    # ── 売掛(d_kakeuri / d_kakeurihistory / d_nyukin) ──
    recv, recve = [], []
    for r in rows("d_kakeuri"):
        cid = cid_of(r)
        if cid in seen:
            recv.append((cid, pk_of(r), None, dt(r.get("datkaidate")),
                         n(r.get("curatamakin")), n(r.get("curzankin")), dt(r.get("datnyukindate"))))
    for r in rows("d_kakeurihistory"):
        cid = cid_of(r)
        if cid in seen:
            recve.append((cid, s(r.get("lngkakekbn")), dt(r.get("datkakedate")), None,
                          n(r.get("curkakekin")), n(r.get("curnyukin")), s(r.get("strbiko"))))
    for r in rows("d_nyukin"):
        cid = cid_of(r)
        if cid in seen:
            recve.append((cid, "入金", dt(r.get("datnyudate")), None,
                          None, n(r.get("curnyukin")), s(r.get("strbiko"))))
    cur.executemany("""INSERT INTO receivables(customer_id,product_key,product_name,bought_at,down_payment,balance,last_paid_at)
                       VALUES (?,?,?,?,?,?,?)""", recv)
    cur.executemany("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid,note)
                       VALUES (?,?,?,?,?,?,?)""", recve)
    log["receivables"], log["receivable_entries"] = len(recv), len(recve)

    # ── ポイント(d_point 残高 / d_pointhistory 取引) ──
    pbal, ptx = [], []
    have_bal = set()
    for r in rows("d_point"):
        cid = cid_of(r)
        if cid in seen:
            pbal.append((cid, n(r.get("curpointzan")) or 0, dt(r.get("datkoshinbi"))))
            have_bal.add(cid)
    # 台帳(d_point)に残高が無い顧客は、履歴の最終行(連番最大)の残高で補完する
    last_seq, last_bal, last_date = {}, {}, {}
    for r in rows("d_pointhistory"):
        cid = cid_of(r)
        if cid in seen:
            add, use = n(r.get("curkasanpoint")) or 0, n(r.get("curusepoint")) or 0
            when = dt(r.get("dathakko")) or dt(r.get("datinpdate"))  # 発行日が空なら処理日で補完
            ptx.append((cid, s(r.get("lngpointkbn")), add - use, add, use,
                        n(r.get("curzanpoint")), s(r.get("strsyname")), when))
            seq = n(r.get("lngpointseq")) or 0
            if cid not in have_bal and seq >= last_seq.get(cid, -1):
                last_seq[cid] = seq
                last_bal[cid] = n(r.get("curzanpoint")) or 0
                last_date[cid] = when
    for cid2, b in last_bal.items():
        pbal.append((cid2, b, last_date.get(cid2)))
    cur.executemany("INSERT OR REPLACE INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)", pbal)
    cur.executemany("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,use_points,balance,product_name,occurred_at)
                       VALUES (?,?,?,?,?,?,?,?)""", ptx)
    log["point_balances"], log["point_tx"] = len(pbal), len(ptx)

    # ── 処方箋(d_shohosen) ──
    rx = []
    for r in rows("d_shohosen"):
        cid = cid_of(r)
        if cid not in seen:
            continue
        lens_key = pk_of(r, "strsytencode1", "lngsykey1")
        frame_key = pk_of(r, "strsytencode2", "lngsykey2")
        lens_name = prod_names.get(lens_key)
        frame_name = prod_names.get(frame_key)
        # 宝飾誤登録の判定は「紐づく商品が実際にメガネ分類か」で行う(商品名の文字列に
        # PT/SV等の短い断片が偶然含まれるだけで誤検知するテキスト正規表現は使わない)
        misassign = 1 if (prod_is_glass.get(lens_key) == 0 or prod_is_glass.get(frame_key) == 0) else 0
        rx.append((
            cid, s(r.get("lngshohosenno")), YOTO.get(s(r.get("stryotokbn")), s(r.get("stryotokbn"))),
            lens_name, frame_name, lens_key, frame_key,
            s(r.get("strsph_r")), s(r.get("strsph_l")), s(r.get("strcyl_r")), s(r.get("strcyl_l")),
            s(r.get("strax_r")), s(r.get("strax_l")), s(r.get("stradd_r")), s(r.get("stradd_l")),
            s(r.get("strpr_r")), s(r.get("strpr_l")), s(r.get("strbase_r")), s(r.get("strbase_l")),
            s(r.get("strpden_r")), s(r.get("strpden_l")), s(r.get("strpden_b")),
            s(r.get("strpdkin_r")), s(r.get("strpdkin_l")), s(r.get("strpdkin_b")),
            s(r.get("strragan_r")), s(r.get("strragan_l")), s(r.get("strragan_b")),
            s(r.get("strkyosei_r")), s(r.get("strkyosei_l")), s(r.get("strkyosei_b")),
            n(r.get("curgokeiteika")), n(r.get("curgokeiurine")),
            m_tan.get(s(r.get("strtaioshacode"))), dt(r.get("datinpdate")), misassign,
        ))
    rx_cols = ("customer_id,rx_no,purpose,lens_name,frame_name,lens_key,frame_key,"
               "sph_r,sph_l,cyl_r,cyl_l,ax_r,ax_l,add_r,add_l,"
               "pri_r,pri_l,base_r,base_l,"
               "pd_far_r,pd_far_l,pd_far_both,pd_near_r,pd_near_l,pd_near_both,"
               "naked_r,naked_l,naked_both,corrected_r,corrected_l,corrected_both,"
               "total_list,total_sell,handler,rx_date,jewelry_misassign")
    ph = ",".join("?" * len(rx_cols.split(",")))
    cur.executemany(f"INSERT INTO prescriptions ({rx_cols}) VALUES ({ph})", rx)
    log["prescriptions"] = len(rx)

    # ── システムユーザー(d_systemuser)→ app_users(平文PWは取り込まない) ──
    au = []
    for r in rows("d_systemuser"):
        uid = s(r.get("struserid"))
        if not uid:
            continue
        role = "admin" if s(r.get("lngmasterflg")) in ("1", "-1") else "staff"
        au.append((uid, s(r.get("strsytencode")), s(r.get("strdispname")), role))
    cur.executemany("INSERT OR IGNORE INTO app_users(user_id,store_code,display_name,role) VALUES (?,?,?,?)", au)
    log["app_users"] = len(au)

    # ── 店舗マスタに無いが顧客・担当者が使う店舗コードに名前を付ける ──
    # 99=宝飾ナビ導入前の旧既存客 / 00=店頭現金(匿名) / 1=01の表記ゆれ / 98=ビジュ旧台帳
    STORE_NAMES = {"99": "本店(旧台帳)", "00": "店頭現金", "1": "本店", "98": "ビジュ(旧台帳)"}
    missing = cur.execute("""
      SELECT DISTINCT store_code FROM (
        SELECT store_code FROM customers UNION SELECT store_code FROM staff
      ) WHERE store_code IS NOT NULL
        AND store_code NOT IN (SELECT store_code FROM stores)""").fetchall()
    extra = [(c[0], STORE_NAMES.get(c[0], f"(不明店舗{c[0]})")) for c in missing]
    cur.executemany("INSERT INTO stores VALUES (?,?)", extra)
    log["stores"] += len(extra)

    cur.execute("INSERT INTO schema_migrations(version,note) VALUES (1,'フルCSV移行(宝飾ナビ114テーブル)')")
    con.commit()

    # ── 検証 ──
    print("== 取り込み件数 ==")
    for k, v in log.items():
        print(f"  {k:20s}: {v:,}")
    print("\n== 参照整合性 ==")
    viol = cur.execute("PRAGMA foreign_key_check").fetchall()
    if viol:
        from collections import Counter
        vc = Counter((v[0], v[2]) for v in viol)
        print(f"  孤立参照 {len(viol):,}件:")
        for (tbl, parent), c in vc.most_common():
            print(f"    {tbl} → {parent}: {c:,}件")
    else:
        print("  問題なし")
    print("\n== 検証クエリ ==")
    for label, sql in [
        ("店舗", "SELECT store_code,name FROM stores"),
        ("担当者数", "SELECT COUNT(*) FROM staff"),
        ("購入額 上位3顧客",
         """SELECT c.customer_id,c.name,SUM(l.amount) t FROM sale_lines l
            JOIN sales_slips s ON l.slip_id=s.slip_id JOIN customers c ON s.customer_id=c.customer_id
            WHERE l.amount IS NOT NULL GROUP BY c.customer_id ORDER BY t DESC LIMIT 3"""),
    ]:
        print(f"[{label}]")
        for row in cur.execute(sql):
            print("   ", row)
    con.close()
    print(f"\nDB作成: {DB} ({os.path.getsize(DB)/1024/1024:.1f}MB)")


if __name__ == "__main__":
    main()
