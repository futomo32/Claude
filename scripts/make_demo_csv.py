#!/usr/bin/env python3
"""import_csv.py の予行演習用に、宝飾ナビCSVと同じ列名の合成データを data/demo_csv/ に生成する。

個人情報は含まない架空データ。列名(ローマ字)と主キー構造(店コード+ID)を実データに合わせ、
複合キー衝突(別店舗に同じID)や孤児参照も混ぜて、import_csv.py の挙動を検証する。

  python3 scripts/make_demo_csv.py
"""
import csv
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "demo_csv")
os.makedirs(OUT, exist_ok=True)


def write(name, header, data):
    with open(os.path.join(OUT, name + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in data:
            w.writerow([row.get(h, "") for h in header])


# ── マスタ ──
write("m_stor", ["strtencode", "strtenname"],
      [{"strtencode": "01", "strtenname": "本店"}, {"strtencode": "02", "strtenname": "支店"}])
write("m_tantou", ["strtancode", "strtanname", "strtencode"],
      [{"strtancode": "001", "strtanname": "築瀬 太郎", "strtencode": "01"},
       {"strtancode": "002", "strtanname": "山田 花子", "strtencode": "01"},
       {"strtancode": "050", "strtanname": "電話 受付", "strtencode": "02"}])
write("m_brand", ["strbrcode", "strbrname"], [{"strbrcode": "B1", "strbrname": "カルティエ"}])
write("m_ishi", ["striscode", "strisname"],
      [{"striscode": "I1", "strisname": "ダイヤモンド"}, {"striscode": "I2", "strisname": "ルビー"}])
write("m_jigane", ["strjicode", "strjiname"], [{"strjicode": "J1", "strjiname": "K18"}])
write("m_douki", ["strdocode", "strdoname"], [{"strdocode": "D1", "strdoname": "自家需要"}])
write("m_basyo", ["strbacode", "strbaname"], [{"strbacode": "P1", "strbaname": "店頭"}])
write("m_tiku", ["strtikucode", "strtikuname"], [{"strtikucode": "T1", "strtikuname": "豊田市中心部"}])
write("m_dbunrui", ["strdbuncode", "strdbunname"],
      [{"strdbuncode": "10", "strdbunname": "リング"}, {"strdbuncode": "90", "strdbunname": "メガネ"}])
write("m_siiresaki", ["strsircode", "strsirname"], [{"strsircode": "S1", "strsirname": "○○貿易"}])

# ── 顧客(店01に100/101、店02に100=複合キー衝突テスト) ──
# 性別コードは実データ準拠: 1=女, 2=男
def user(tc, kk, name, kana, tel, tan, sex="2", rank="A"):
    return {"strkotencode": tc, "lngkokey": kk, "strkoname": name, "strkokana": kana,
            "strkotel": tel, "strtel2": "", "strkopos": "471-0001", "strkojyu1": "豊田市○○町1-2",
            "strkojyu2": "△△マンション101", "strsexkbn": sex, "datbirthday": "1975/6/12",
            "datwedddate": "2000/3/3", "strrank": rank, "strdmkbn": "1", "strpcmail": "a@example.com",
            "strkeitaimail": "", "lngfinsize1": "9", "strpiasukbn": "1", "strtancode": tan,
            "strkanritenpo": tc, "dattoudate": "2010/1/5"}


UCOLS = ["strkotencode", "lngkokey", "strkoname", "strkokana", "strkotel", "strtel2", "strkopos",
         "strkojyu1", "strkojyu2", "strsexkbn", "datbirthday", "datwedddate", "strrank", "strdmkbn",
         "strpcmail", "strkeitaimail", "lngfinsize1", "strpiasukbn", "strtancode", "strkanritenpo", "dattoudate"]
write("d_user", UCOLS, [
    user("01", "100", "田中 一郎", "ﾀﾅｶ ｲﾁﾛｳ", "0565-00-0001", "001", "2"),
    user("01", "101", "鈴木 幸子", "ｽｽﾞｷ ｻﾁｺ", "0565-00-0002", "002", "1"),
    user("02", "100", "佐藤 三郎", "ｻﾄｳ ｻﾌﾞﾛｳ", "0565-00-0003", "050", "2"),
])

write("d_user_memo", ["strkotencode", "lngkokey", "strmemo01", "strmemo02", "datinpdate"],
      [{"strkotencode": "01", "lngkokey": "100", "strmemo01": "誕生月に来店", "strmemo02": "", "datinpdate": "2020/5/1"}])

# 続柄コードは実データ準拠(m_kubun種別013): 4=妻
write("d_famiry", ["strkotencode", "lngkokey", "strfamiryname", "strzokukbn", "strsexkbn", "datbirthday"],
      [{"strkotencode": "01", "lngkokey": "100", "strfamiryname": "田中 花", "strzokukbn": "4",
        "strsexkbn": "1", "datbirthday": "1978/8/8"}])

# ── 商品(店01に5000/5001、店02に5000=衝突) ──
# 状態区分コードは実データ準拠: 0=受託, 1=在庫, 3=売上, 5=返品
def item(tc, sk, no, name, dbun, oro, kou, ishi="I1", state="1"):
    return {"strsytencode": tc, "lngsykey": sk, "strsyno": no, "strsyname": name, "strsyinfo": "自社",
            "strdbuncode": dbun, "strsirsakicode": "S1", "curorokin": oro, "curkoukin": kou,
            "strjotaikbn": state, "strhotencode": tc, "striscode": ishi, "curmainjuryo": "0.3",
            "strcolcode": "F", "strclacode": "VS1", "strcutcode": "3EX", "strkanbno": "GIA123",
            "dattoudate": "2015/4/1"}


ICOLS = ["strsytencode", "lngsykey", "strsyno", "strsyname", "strsyinfo", "strdbuncode", "strsirsakicode",
         "curorokin", "curkoukin", "strjotaikbn", "strhotencode", "striscode", "curmainjuryo",
         "strcolcode", "strclacode", "strcutcode", "strkanbno", "dattoudate"]
write("d_item", ICOLS, [
    item("01", "5000", "R-5000", "ダイヤリング", "10", "150000", "300000"),
    item("01", "5001", "G-5001", "メガネフレーム", "90", "8000", "20000"),
    item("02", "5000", "R-9000", "ルビーリング", "10", "90000", "180000", "I2"),
])

# ── 販売(伝票T1: 顧客01-100 が商品2点、伝票T2: 顧客02-100) ──
def hanbai(dp, tc, kk, stc, sk, teika, kaikin, tan, name):
    # 掛売区分コードは実データ準拠: 1=現金, 2=掛売, 3=クレジット…
    return {"strkotencode": tc, "lngkokey": kk, "curdenpyono": dp, "datkaidate": "2023/11/3",
            "datcredate": "2023/11/3", "strhantancode": tan, "strkakekbn": "1", "strcrekbn": "",
            "strdocode": "D1", "strbacode": "P1", "curusepoint": "0", "curkasanpoint": "300",
            "strsytencode": stc, "lngsykey": sk, "curwariritu": "0", "strkokname": name,
            "strsyinfo": "自社", "curteika": teika, "curkaikin": kaikin, "curkaizeikin": "0"}


HCOLS = ["strkotencode", "lngkokey", "curdenpyono", "datkaidate", "datcredate", "strhantancode",
         "strkakekbn", "strcrekbn", "strdocode", "strbacode", "curusepoint", "curkasanpoint",
         "strsytencode", "lngsykey", "curwariritu", "strkokname", "strsyinfo", "curteika", "curkaikin", "curkaizeikin"]
write("d_hanbai", HCOLS, [
    hanbai("T1", "01", "100", "01", "5000", "300000", "280000", "001", "田中 一郎"),
    hanbai("T1", "01", "100", "01", "5001", "20000", "18000", "001", "田中 一郎"),
    hanbai("T2", "02", "100", "02", "5000", "180000", "180000", "050", "佐藤 三郎"),
    # 孤児: 存在しない顧客 01-999
    hanbai("T3", "01", "999", "01", "5001", "20000", "20000", "001", "退会 済子"),
])

# ── 売掛 ──
write("d_kakeuri", ["strkotencode", "lngkokey", "strsytencode", "lngsykey", "datkaidate",
                    "curatamakin", "curzankin", "datnyukindate"],
      [{"strkotencode": "01", "lngkokey": "100", "strsytencode": "01", "lngsykey": "5000",
        "datkaidate": "2023/11/3", "curatamakin": "100000", "curzankin": "180000", "datnyukindate": "2023/12/3"}])
write("d_kakeurihistory", ["strkotencode", "lngkokey", "lngkakekbn", "datkakedate", "curkakekin", "curnyukin", "strbiko"],
      [{"strkotencode": "01", "lngkokey": "100", "lngkakekbn": "1", "datkakedate": "2023/11/3",
        "curkakekin": "280000", "curnyukin": "100000", "strbiko": "頭金"}])
write("d_nyukin", ["strkotencode", "lngkokey", "datnyudate", "curnyukin", "strbiko"],
      [{"strkotencode": "01", "lngkokey": "100", "datnyudate": "2023/12/3", "curnyukin": "50000", "strbiko": "分割入金"}])

# ── ポイント ──
write("d_point", ["strkotencode", "lngkokey", "curpointzan", "datkoshinbi"],
      [{"strkotencode": "01", "lngkokey": "100", "curpointzan": "300", "datkoshinbi": "2023/11/3"}])
write("d_pointhistory", ["strkotencode", "lngkokey", "lngpointkbn", "curkasanpoint", "curusepoint",
                         "curzanpoint", "strsyname", "dathakko"],
      [{"strkotencode": "01", "lngkokey": "100", "lngpointkbn": "1", "curkasanpoint": "300",
        "curusepoint": "0", "curzanpoint": "300", "strsyname": "ダイヤリング", "dathakko": "2023/11/3"}])

# ── 処方箋(顧客01-101、レンズ=商品01-5001) ──
write("d_shohosen",
      ["strkotencode", "lngkokey", "lngshohosenno", "stryotokbn", "strsytencode1", "lngsykey1",
       "strsytencode2", "lngsykey2", "strsph_r", "strsph_l", "strcyl_r", "strcyl_l", "strax_r", "strax_l",
       "stradd_r", "stradd_l", "strpr_r", "strpr_l", "strbase_r", "strbase_l",
       "strpden_r", "strpden_l", "strpden_b", "strpdkin_r", "strpdkin_l", "strpdkin_b",
       "strragan_r", "strragan_l", "strragan_b", "strkyosei_r", "strkyosei_l", "strkyosei_b",
       "curgokeiteika", "curgokeiurine", "strtaioshacode", "strbiko2", "datinpdate"],
      [{"strkotencode": "01", "lngkokey": "101", "lngshohosenno": "1", "stryotokbn": "常用",
        "strsytencode1": "01", "lngsykey1": "5001", "strsytencode2": "", "lngsykey2": "",
        "strsph_r": "-2.00", "strsph_l": "-2.25", "strcyl_r": "-0.50", "strcyl_l": "-0.75",
        "strax_r": "180", "strax_l": "170", "stradd_r": "", "stradd_l": "",
        "strpr_r": "", "strpr_l": "", "strbase_r": "", "strbase_l": "",
        "strpden_b": "64", "strpdkin_b": "61",
        "strragan_r": "0.1", "strragan_l": "0.1", "strkyosei_r": "1.2", "strkyosei_l": "1.2",
        "curgokeiteika": "40000", "curgokeiurine": "36000", "strtaioshacode": "002",
        "strbiko2": "", "datinpdate": "2022/5/1"}])

# ── システムユーザー ──
write("d_systemuser", ["struserid", "strsytencode", "strdispname", "lngmasterflg", "strpassword"],
      [{"struserid": "admin", "strsytencode": "01", "strdispname": "管理者", "lngmasterflg": "1", "strpassword": "secret"},
       {"struserid": "staff1", "strsytencode": "01", "strdispname": "築瀬 太郎", "lngmasterflg": "0", "strpassword": "x"}])

print(f"合成CSVを生成しました: {OUT}")
print("次: python3 scripts/import_csv.py --demo")
