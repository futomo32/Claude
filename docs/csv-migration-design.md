# フルCSV移行 設計メモ(宝飾ナビ 114テーブル → トキワ)

宝飾ナビの全DBダンプ(CSV 114テーブル)を正とし、トキワDBを構築する。
列名はローマ字(str=文字/lng=整数/cur=金額/dat=日付)。実データは data/real/csv/。

## 主キー(最重要)
宝飾ナビは店舗ごとにID採番 → **複合キー**。トキワは TEXT主キーなので "店-ID" 形式で表現。
- 顧客: `customer_id = f"{strkotencode}-{lngkokey}"` (例 "01-12345")
- 商品: `product_key  = f"{strsytencode}-{lngsykey}"`
- 伝票: `curdenpyono`(売上伝票番号)でヘッダ/明細を結合

全ての子テーブルは同じ (店コード+キー) 規則で親を参照する。これで別店舗の同番号衝突を防ぐ。

## マスタ(コード→名前 解決)
importで各 m_*.csv を辞書に読み、コードを名前に変換する:
| マスタ | コード列 | 名前列 | 用途 |
|---|---|---|---|
| m_stor | strtencode | strtenname | 店舗 → stores |
| m_tantou | strtancode | strtanname | 担当者(301) → staff |
| m_brand | strbrcode | strbrname | ブランド |
| m_ishi | striscode | strisname | 石種(中石) |
| m_jigane | strjicode | strjiname | 地金 |
| m_desine | strdecode | strdename | デザイン |
| m_seihin | strsecode | strsename | 製品 |
| m_taste | strtascode | strtasname | テイスト |
| m_douki | strdocode | strdoname | 購入動機 |
| m_basyo | strbacode | strbaname | 購入場所 |
| m_tiku | strtikucode | strtikuname | 地区 |
| m_dbunrui | strdbuncode | strdbunname | 大分類(→ products.category) |
| m_cbunrui | strcbuncode | strcbunname | 中分類 |
| m_siiresaki | strsircode | strsirname | 仕入先 |
| z_wareki | strcode | strname | 和暦(日付変換の補助) |
| zztaxrate | lngtaxcode | curtaxrate | 税率 |

性別: strsexkbn "1"→男 / "2"→女(宝飾ナビ標準)。ピアス・DM等の 0/1 区分も同様に既定変換。

## テーブル対応(CSV → トキワ)
- d_user(74) → customers + customer_memos(d_user_memo)。担当/地区/動機/備考名は d_user 内に名前列あり or マスタ解決。
- d_famiry → customer_families
- d_item(81) → products。category=大分類名、中石=石名、cost=curorokin、list=curkoukin(要検証)。
- d_item_memo → (必要なら products への注記)
- **売上**: d_hanbai(20万) を購入履歴の主とし、curdenpyono で sales_slips(ヘッダ)+sale_lines(明細) に分割。
  支払・釣銭の精密値が要る場合は d_uriage(ヘッダ)+d_uriage_meisai(明細)+d_uriage_kake(掛)で補完。
- d_kakeuri/d_kakeurihistory/d_nyukin → receivables / receivable_entries
- d_point/d_pointhistory → point_balances / point_transactions
- d_shohosen(45) → prescriptions。sph/cyl/ax/add/pr/base(r/l)、裸眼(ragan)、矯正(kyosei)、
  PD遠(pden)、PD近(pdkin)、framesize、合計(gokei)。商品1→レンズ, 商品2→フレーム(仮)。
- d_systemuser → app_users(表示名・店・権限のみ。**平文パスワードは取り込まない**=NULL、ログイン実装時に再設定)。
- d_approachhistory → approach_history(実データは0件)

## 後回し(トキワに表示画面が無い/内部集計)
d_siire(仕入16万)/d_jutaku(受託)/d_nyushukkin(入出金)/d_tana(棚卸)/d_uriage系の一部/
w_*(分析ワーク)/wk_*/zz*(システム)。必要になった時点で追加。CSVは保管してあるので移行可能。

### ★d_siire(仕入)の列を確定した(2026-09-05)
店から「商品の伝票番号＝納品書番号が漏れている」と指摘があり、実データで突き止めた
(`scripts/find_slip_no.py`。全168,136行を読んで確認)。宝飾ナビ『仕入商品登録・修正・削除』
画面の左半分がこの表で、商品とは **lngsykey(商品キー)** で繋ぐ。

| 列 | 画面の項目 | 入っている割合 | トキワの受け皿 |
|---|---|---|---|
| lngsykey | (内部) | 100% | products.product_key と対応 |
| **strsirsakidenno** | **納品書No** | **12.5% / 21,097件** | **products.purchase_slip_no**(v1.4.2で追加・未取込) |
| datdendate | 伝票日付 | 88.2% / 148,377件 | 未(列も無い) |
| dattoudate | 登録日 | 88.2% | products.registered_at は d_item 側を使用 |
| strsirtancode | 仕入担当 | 20.0% / 33,690件 | 未 |
| strsirsycode | 仕入品番 | 24.6% / 41,329件 | products.maker_no(列だけ作って未取込) |
| cursirtanka | 仕入単価 | 100% | products.cost_price は d_item 側を使用 |

- **★lngsykey(商品キー)と strsyno(商品番号)は別物。** 同じ数字が別商品に入っていることが
  あり、取り違えると**まったく別の品の行**を見てしまう(実例: 商品番号21454 の商品の
  商品キーは 164226。一方で商品キー21454 の1988年の別商品も存在する)。
- 同じ `strsirsakidenno` は **d_jutaku(受託)にもある**(5.7% / 1,172件)。
- ★入力率は**全行**で数えた値。書き出しは**商品キー順=古い順**なので、
  先頭2万行だけを見ると「すべて空」に見えて誤判断する。

### ★あわせて分かった d_item の取りこぼし・未使用(2026-09-05)
| 列 | 意味 | 割合 | 判断 |
|---|---|---|---|
| strbiknaiyo | 商品の備考 | 23.9% / 50,961件 | **未取込**。入れる価値あり |
| strtaghinname | タグ品名 | 48.0% / 102,391件 | 取込済み(v0.34.23) |
| strfucho | 符丁 | **すべて空** | 取り込む必要なし(トキワが自動生成) |
| strshiharaihohokbn / datshiharaiyoteibi | 支払方法・支払予定日 | 46件のみ | 実質未使用 |
| strtagyousiki | タグ様式 | すべて空 | 不要 |
| strcolcode / strclacode / strcutcode | カラー/クラリティ/カット | 各0.1%(100件台) | ほぼ未使用 |
| strkanbno | 鑑別書No | 0.3% / 619件 | 取込済み(cert_no) |

## 未確定・実データで要検証(実行後にアプリで目視)
- 金額列の意味(curorokin=卸/仕入, curkoukin=甲=上代 の想定)。
- 状態区分 strjotaikbn / 各フラグ(strjuflg 受託 等)→ products.state の対応。
- 日付の和暦混在(datbirthday に "H29.12" や "1月18日" 等の欠損表記あり)。dt()が拾えない値はNULL。
- DM区分 strdmkbn / ピアス strpiasukbn の 0/1 の向き。

## 手順
1. 合成CSV(data/demo_csv/)で予行演習 → import_csv.py の動作確認。
2. 実データ: `python3 scripts/import_csv.py`(data/real/csv を移行)。
3. `python3 server/app.py` で顧客・商品・履歴・処方箋・売掛・担当者を目視検証。
4. コード→名前や金額の取り違えがあれば import_csv.py を微修正して再実行(冪等)。
