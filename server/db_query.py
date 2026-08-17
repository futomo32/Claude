"""tokiwa.db から画面用データ(TOKIWA_DATA と同一形状)を組み立て、会計を書き込む。

UIの描画コードを変えずに済むよう、埋め込み版と同じ配列の並びで返す。
"""
import contextlib, hashlib, json, re, secrets, sqlite3, datetime, unicodedata


@contextlib.contextmanager
def write_lock(con):
    """お金・在庫を動かす処理を排他する(BEGIN IMMEDIATE)。

    SQLiteの既定(遅延トランザクション)では、書き込みロックは最初のINSERT/UPDATEまで
    取られない。そのため「在庫を確認 → 伝票を作る」のような読んでから書く処理は、
    店内共有で2台が同時に会計すると**両方が確認を通過して二重販売が成立し得る**。
    BEGIN IMMEDIATE で最初から書き込みロックを取り、他方は busy_timeout の間待つ。

    ・入れ子で呼ばれた場合(既にトランザクション中)は何もしない=外側のロックに任せる
    ・例外時は ROLLBACK。途中まで書いた伝票が残らない
    ・内側で con.commit() を呼ばないこと(ロックが切れて排他の意味がなくなる)
    """
    if con.in_transaction:
        yield
        return
    prev = con.isolation_level
    con.isolation_level = None          # トランザクションを自前で管理する
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
    finally:
        con.isolation_level = prev

GLASS_PAT = re.compile(r"メガネ|眼鏡|レンズ|フレーム|ﾒｶﾞﾈ|ﾚﾝｽﾞ|ﾌﾚｰﾑ")


def normjp(s):
    """検索照合用の正規化(1か所に集約)。全角/半角・半角カナ/全角カナ・大文字/小文字の
    違いを吸収する。NFKC(全角英数→半角・半角カナ→全角カナ等)＋casefold(大小文字)。
    ここを直せば、これを使う全項目の照合ルールが一斉に変わる。SQLiteにも関数登録して使う。"""
    if s is None:
        return None
    return unicodedata.normalize("NFKC", str(s)).casefold()


def norm_code(s):
    """バーコード/商品番号の照合用に幅を正規化する。スキャナやレジの入力欄が全角(かな)
    モードだと数字が全角(２０５…)で入るため、NFKC で全角英数・全角ハイフン等を半角へ揃える。
    商品番号は英字(R-5000 等)の大小を区別する必要があるので casefold はしない(幅だけ揃える)。"""
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s)).strip()
FRAME_PAT = re.compile(r"フレーム|ﾌﾚｰﾑ|frame", re.I)
LENS_PAT = re.compile(r"レンズ|ﾚﾝｽﾞ|lens|非球面|累進", re.I)


def _rx_misassign(stored_flag, lens_name, frame_name):
    """処方箋の宝飾誤登録フラグを表示用に補正する(②即効の補正)。
    レンズ名/フレーム名に「メガネ・眼鏡・レンズ・フレーム」を含むものは正当なメガネ品なので
    誤登録扱いにしない(取込時の判定漏れ=全角レンズ等による誤検知を、再取込前でも消す)。"""
    if not stored_flag:
        return False
    for nm in (lens_name, frame_name):
        if nm and GLASS_PAT.search(str(nm)):
            return False
    return True

# 旧・宝飾ナビ由来のゴミ担当名(担当者フィールドにランク/DM/ライオンズ等を無理やり
# 詰め込んだ複合タグ)を判定する。例:「Aランク：三輪」「Ｌ○○」「ライオンズ」。
# レジ会計担当のワンタップ表示から外す/一括整理の対象にする。
_JUNK_STAFF_PAT = re.compile(r"ランク|ライオンズ|Ｌｉｏｎｓ|Lions|ＤＭ|[：:]")


def _is_junk_staff_name(name):
    """担当者名が旧タグ(本物の店員でない)っぽいかを判定する。"""
    if not name:
        return False
    return bool(_JUNK_STAFF_PAT.search(str(name)))


def glass_kind(*texts):
    """フレーム/レンズの別を判定(分類名や品名から)"""
    s = " ".join(t for t in texts if t)
    if FRAME_PAT.search(s):
        return "frame"
    if LENS_PAT.search(s):
        return "lens"
    return ""



def ensure_schema(con):
    """後付けした列がDBに無ければ自動で足す(冪等)。pull直後にmigrate_dbを忘れても
    サーバーが動くための保険。列不足でクエリが落ちて『在庫0件』等になるのを防ぐ。"""
    # 仕入先マスタ(分類フラグ付き)。無ければ作る
    con.execute("""CREATE TABLE IF NOT EXISTS supplier_master (
        name  TEXT PRIMARY KEY,   -- 仕入先名(products.supplier と一致)
        genre TEXT,                -- 商品ジャンル: 宝石/メガネ/時計/その他(未設定はNULL)
        fucho_head TEXT            -- 符丁の頭(メーカー符丁カナ)。漢字名でも正しく出すため名前と別管理
    )""")
    # 汎用マスタ(商品分類・保管場所・支払方法など「名前の一覧」型を1テーブルで管理)
    con.execute("""CREATE TABLE IF NOT EXISTS master_items (
        master_type TEXT NOT NULL,   -- category / location / pay_method ...
        name        TEXT NOT NULL,
        PRIMARY KEY (master_type, name)
    )""")
    # 写真プール: まとめて撮影した未割当の商品写真(商品登録前に一括アップロードしておき、
    # 商品登録・修正の時にここから選んで紐づける)。割り当てたら行を消す(ファイルは残す)。
    con.execute("""CREATE TABLE IF NOT EXISTS photo_pool (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        filename    TEXT NOT NULL,
        uploaded_at TEXT
    )""")
    # レジ入出金: 顧客の買い物と無関係な現金の出入り(代引手数料・収入印紙・両替・経費等)。
    # amountは +入金 / -出金。日報のレジ締め金額・入出金合計に反映する。顧客IDは持たない。
    con.execute("""CREATE TABLE IF NOT EXISTS cash_movements (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT,                -- 区分(経費/両替/代引手数料/収入印紙/その他)
        amount      INTEGER NOT NULL,    -- +入金 / -出金
        note        TEXT,
        staff_name  TEXT,
        occurred_at TEXT                 -- 発生日 YYYY-MM-DD
    )""")
    # アプリ設定(キー・バリュー)。顧客ランク基準などをJSONで保存する。
    con.execute("""CREATE TABLE IF NOT EXISTS app_settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )""")
    # 棚卸し(実地在庫の照合)。現物を確認した商品を記録し、在庫台帳との差異を出す。
    con.execute("""CREATE TABLE IF NOT EXISTS stocktake_checks (
        product_key TEXT PRIMARY KEY,
        checked_at  TEXT
    )""")
    # ログインユーザー(ロール別アクセス制御④)。schema.sql と同形。無いDBでも動くように。
    con.execute("""CREATE TABLE IF NOT EXISTS app_users (
        user_id      TEXT PRIMARY KEY,
        store_code   TEXT,
        display_name TEXT,
        role         TEXT NOT NULL DEFAULT 'staff',  -- admin=管理者/staff=社員/part=パート
        pass_hash    TEXT,                            -- NULL=未設定(初回ログイン時に本人が設定)
        active       INTEGER NOT NULL DEFAULT 1
    )""")
    # ログインセッション(トークン→ユーザー)。サーバー再起動してもログイン状態が残るようDBに置く。
    con.execute("""CREATE TABLE IF NOT EXISTS app_sessions (
        token      TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        created_at TEXT
    )""")
    # ユーザーが1人もいなければ初期管理者を作る(パスワードは初回ログイン時に設定)
    if not con.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
        con.execute("INSERT INTO app_users(user_id, display_name, role) VALUES ('admin', '管理者', 'admin')")
        con.commit()

    def cols(t):
        try:
            return {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        except sqlite3.Error:
            return set()
    adds = [
        ("products", "image_file", "TEXT"),
        ("products", "brand", "TEXT"),
        ("products", "metal", "TEXT"),
        ("sale_lines", "voided", "INTEGER DEFAULT 0"),
        ("sale_lines", "voided_at", "TEXT"),
        ("sales_slips", "voided", "INTEGER DEFAULT 0"),
        ("customers", "district", "TEXT"),
        ("customers", "exclude_stats", "INTEGER DEFAULT 0"),
        ("customers", "tel2", "TEXT"), ("customers", "note", "TEXT"),
        ("customers", "postal", "TEXT"), ("customers", "address2", "TEXT"),
        ("customers", "email", "TEXT"),
        ("customer_families", "linked_customer_id", "TEXT"),
        ("receivable_entries", "method", "TEXT"),  # 売掛入金の支払方法(現金/銀行振込/カード/その他。空=現金扱い)
        ("repairs", "photo_files", "TEXT"),  # 修理お預かり品の写真ファイル名(カンマ区切り。B-6)
        ("products", "fucho", "TEXT"),  # 符丁(下代を隠す店内符牒。仕入先頭文字＋数字部)。パートには送らない
        # 値札(タグ)に刷る2項目。宝飾ナビから引き継ぐ(2026-08-03 実データで所在を特定)
        ("products", "maker_no", "TEXT"),  # 品番(仕入先の商品コード)。宝飾ナビ d_siire.strsirsycode
        ("products", "tag_name", "TEXT"),  # タグ用の短い品名。宝飾ナビ d_item.strtaghinname
        ("supplier_master", "fucho_head", "TEXT"),  # 仕入先ごとの符丁頭カナ(漢字名対策)
        ("products", "is_consignment", "INTEGER DEFAULT 0"),  # 受託品フラグ(売上になっても残す。後日精算の識別用)
        ("products", "consign_settled", "INTEGER DEFAULT 0"),  # 受託の後日精算(原価入力)が済んだか
        ("prescriptions", "frame_type", "TEXT"),  # フレームの種類(セル/メタル/ツーポ/ナイロール)
        ("receivables", "slip_id", "INTEGER"),    # 起票元の売上伝票(併用払いの内訳を辿るため)
        ("products", "ring_fingers", "TEXT"),  # はめる指(複数可。カンマ区切り)
        ("products", "ring_size", "TEXT"),     # リングサイズ(フリー入力。#10.5 や 12号 等)
        ("sales_slips", "receipt_note", "TEXT"),  # その会計だけのレシート一言(再印字でも同じ内容が出る)
        # 取消(訂正・返品)の記録。電子帳簿保存法の「訂正・削除の事実と内容を確認できること」
        # に対応し、店舗運営上も「誰が・なぜ取り消したか」を追えるようにする(2026-07-31)。
        #   voided_by    … ログインユーザー(認証済み・詐称できない=監査の証拠)
        #   voided_staff … 取消操作をした担当者(レジと同じワンタップ選択・実務の記録)
        #   voided_reason… 取消理由(必須。「誰が」より「なぜ」が後から効く)
        ("sale_lines", "voided_by", "TEXT"),
        ("sale_lines", "voided_staff", "TEXT"),
        ("sale_lines", "voided_reason", "TEXT"),
        ("sales_slips", "voided_at", "TEXT"),
        ("sales_slips", "voided_by", "TEXT"),
        ("sales_slips", "voided_staff", "TEXT"),
        ("sales_slips", "voided_reason", "TEXT"),
        # ホームの「お声がけ」で、同じ用件を二度出さないための鍵。
        # 例「誕生日:1234:2026」「修理納期:57」。✓を押すとこの鍵つきで履歴に記録し、
        # 次からその用件は一覧に出さない(2026-08-06 追加)。
        ("approach_history", "ref_key", "TEXT"),
        # 返金方法(現金/クレジット/ポイント等)。取消時に選ぶ。返品日の現金締めに
        # 現金返金だけを反映するために必要(2026-08-06 税理士確認に基づく)。
        ("sale_lines", "refund_method", "TEXT"),
        ("sales_slips", "refund_method", "TEXT"),
    ]
    changed = False
    for table, col, decl in adds:
        c = cols(table)
        if c and col not in c:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                changed = True
            except sqlite3.Error:
                pass
    # staff.is_register(レジ会計担当としてワンタップバーに出すか)。デフォルトは
    # 0(非表示)。宝飾ナビ由来の担当者は数百件規模になりがちで、全員表示→不要な
    # ものだけ手動でOFFにする方式だとクリック数が膨大になるため、逆に全員非表示から
    # 必要な人だけマスタ画面でONにする運用にする(実店舗は数人〜十数人のため負担が少ない)。
    scols = cols("staff")
    if scols and "is_register" not in scols:
        try:
            con.execute("ALTER TABLE staff ADD COLUMN is_register INTEGER DEFAULT 0")
            changed = True
        except sqlite3.Error:
            pass
    # 後付けの索引(既存DBにも自動で張る)。schema.sql と対で管理すること。
    # idx_rx_line: 明細→処方箋の逆引き。この抜けが原因で、明細の多い顧客の詳細表示に
    # 10秒超かかっていた(2026-08-06)。「検索に使う外部キーには必ず索引」の原則。
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_rx_line ON prescriptions(sale_line_id)")
        changed = True
    except sqlite3.Error:
        pass
    if changed:
        con.commit()


def stock_stats(con):
    """在庫サマリ(状態=在庫の商品のみ)。上代=list_price(税込)、下代=cost_price(税別)。
    粗利率 = (1 - 下代×(1+消費税率) / 上代) × 100 … 下代を税込換算して上代(税込)と比較。
    ※消費税率は当面10%固定。会計確定・返品でリアルタイムに変わるので、UIからも取り直せる。"""
    con.row_factory = sqlite3.Row
    TAX_RATE = 0.10
    srow = con.execute("""SELECT COUNT(*) c, COALESCE(SUM(list_price),0) lt, COALESCE(SUM(cost_price),0) ct
                          FROM products WHERE state='在庫'""").fetchone()
    s_count, s_list, s_cost = srow["c"], srow["lt"] or 0, srow["ct"] or 0
    s_margin = round((1 - (s_cost * (1 + TAX_RATE)) / s_list) * 100, 1) if s_list else 0
    return {"count": s_count, "listTotal": s_list, "costTotal": s_cost,
            "marginRate": s_margin, "taxRate": TAX_RATE}


def stocktake_scan(con, product_no):
    """棚卸しのスキャン: 商品番号で在庫品を1点、現物確認済みにする(棚卸台帳に記録)。
    ・在庫状態の同番号のうち、まだ未確認の1点を確認済みにする(同番号が複数あれば繰り返しスキャンで順に)。
    ・在庫状態でない番号(売却済み等)は警告を返す。存在しない番号はエラー。
    ・同じ品番の在庫が複数ある場合(移行データに少数あり)は same_no / remaining を返し、
      「同番号がもう何点あるか」を画面に出せるようにする(現物を1点ずつスキャンすれば全部消える)。"""
    con.row_factory = sqlite3.Row
    no = str(product_no or "").strip()
    if not no:
        raise ValueError("商品番号を入力してください")
    where, wargs = _resolve_code_conditions(no)  # バーコードは品番(先頭5桁)等で照合
    rows = con.execute(
        f"SELECT product_key, product_no, name, state, location, list_price "
        f"FROM products WHERE {where}", wargs).fetchall()
    if not rows:
        # ★桁数不足・チェックデジット不一致など「バーコードの読み取り失敗」らしい入力は、
        #   「商品が台帳にない」とは別のメッセージにする(2026-08-03)。
        #   実機テストで、値札のバーコードが規格(80%)未満の縮小率のため読み取りエラーが
        #   一定数出ることを確認した。読み取り失敗を「商品が登録されていない」と誤解されると
        #   現場が混乱するため、数字だけで8桁以上(=手入力の5桁品番より明らかに長い、
        #   スキャンらしい入力)なのに一致しない場合は、専用のメッセージで案内する。
        #   ※13桁ちょうどでチェックデジットも正しい「正常なEAN-13」は _resolve_code_conditions
        #     の時点で候補条件に入るため、ここに来る13桁はほぼ誤読(桁抜け・桁化け)。
        digits_only = norm_code(no)
        if digits_only.isdigit() and len(digits_only) >= 8:
            return {"result": "scan_failed", "product_no": no,
                    "message": "バーコードの読み取りに失敗しました(桁数不足や誤読の可能性)"}
        return {"result": "not_found", "product_no": no, "message": "その商品番号は台帳にありません"}
    instock = [r for r in rows if r["state"] == "在庫"]
    if not instock:
        return {"result": "not_instock", "product_no": no, "name": rows[0]["name"],
                "message": "この番号は在庫状態ではありません(売却済み等)"}
    checked_keys = {r[0] for r in con.execute(
        "SELECT product_key FROM stocktake_checks WHERE product_key IN (%s)" %
        ",".join("?" * len(instock)), [r["product_key"] for r in instock])}
    target = next((r for r in instock if r["product_key"] not in checked_keys), None)
    if not target:
        return {"result": "already", "product_no": no, "name": instock[0]["name"],
                "message": "この番号の在庫は全て確認済みです"}
    con.execute("INSERT OR REPLACE INTO stocktake_checks(product_key, checked_at) VALUES (?, datetime('now','localtime'))",
                (target["product_key"],))
    # 開始日時が未設定なら、最初のスキャンで記録(リセットせず使い始めた場合の保険)
    if not _stocktake_started(con):
        _set_setting(con, "stocktake_started_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    con.commit()
    # 同じ品番の在庫が他にもある場合、残りの未確認点数を返す(現物を1点ずつスキャンすれば消える)
    remaining = sum(1 for r in instock
                    if r["product_key"] != target["product_key"] and r["product_key"] not in checked_keys)
    return {"result": "ok", "product_no": target["product_no"] or no, "name": target["name"],
            "location": target["location"], "product_key": target["product_key"],
            "list_price": target["list_price"], "same_no": len(instock), "remaining": remaining}


def _set_setting(con, key, value):
    con.execute("INSERT INTO app_settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _stocktake_started(con):
    row = con.execute("SELECT value FROM app_settings WHERE key='stocktake_started_at'").fetchone()
    return row[0] if row and row[0] else None


def stocktake_summary(con):
    """棚卸しの進捗と差異。確認済み点数 / 在庫総点数 / 未確認(在庫台帳にあるが現物未確認=紛失疑い)一覧 / 開始日時。"""
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) FROM products WHERE state='在庫'").fetchone()[0]
    checked = con.execute("""SELECT COUNT(*) FROM stocktake_checks s
                             JOIN products p ON p.product_key=s.product_key AND p.state='在庫'""").fetchone()[0]
    unchecked = []
    for r in con.execute("""SELECT product_no, name, location, list_price
                            FROM products p WHERE p.state='在庫'
                              AND p.product_key NOT IN (SELECT product_key FROM stocktake_checks)
                            ORDER BY product_no"""):
        unchecked.append({"product_no": r["product_no"], "name": r["name"],
                          "location": r["location"], "list_price": r["list_price"]})
    # 確認が1件も無ければ「未開始」扱い(開始日時は表示しない)
    started_at = _stocktake_started(con) if checked > 0 else None
    return {"total": total, "checked": checked, "unchecked": unchecked,
            "unchecked_count": len(unchecked), "started_at": started_at}


def stocktake_reset(con):
    """棚卸しの確認記録を全消去(新しい棚卸しを始める)。開始日時も引き直す。"""
    con.execute("DELETE FROM stocktake_checks")
    _set_setting(con, "stocktake_started_at", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    con.commit()
    return {"ok": True}


# ── ホームの「今週のお声がけ」 ────────────────────────────────────────────
# 期間の決め方は店の運用に合わせて決めた(2026-08-06)。ここを直せば全部追随する。
CARE_POINT_DAYS = 30    # ポイント失効の何日前から出すか
CARE_REPAIR_DAYS = 7    # 修理の引渡予定日の何日前から出すか
CARE_MAX = 12           # ホームに一度に出す最大件数(超えた分は「他○件」)


def _add_years(d, years):
    """日付にN年足す。2月29日は28日に寄せる(閏年でない年に存在しないため)。"""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _parse_date(s):
    """'YYYY-MM-DD'(時刻が付いていても可)を date にする。読めなければ None。"""
    t = str(s or "")[:10]
    try:
        return datetime.date.fromisoformat(t)
    except ValueError:
        return None


def _care_skip_outreach(r):
    """こちらから連絡する用件(誕生日・記念日・ポイント)の対象外か。

    DMを出さない相手は外す。**とくに死去された方の誕生日をお声がけ候補に出すのは
    事故なので必ず外す。**集計対象外(ななし等)も連絡先として扱わない。
    ※修理納期はこの判定を通さない。お預かり品を返す義務があり、連絡の可否とは別のため。
    """
    if r["exclude_stats"]:
        return True
    return bool(dm_block_reason(r["address"])) or dm_is_blocked(r["dm_ok"])


def care_list(con):
    """ホームの「今週のお声がけ」に出す項目を集める。

    4種類。期間は店の運用に合わせて決めた(2026-08-06):
      誕生日      … 今月ぶん全部。ただし**過ぎた日は出さない**
      結婚記念日  … 同じ
      ポイント失効 … 失効日(最終購入日 + card_expiry_years年)の30日前から
      修理納期    … 引渡予定日の7日前から。**過ぎた分は出し続け overdue=1 で強調**

    ✓を押した用件は approach_history に ref_key つきで記録され、二度と出てこない。
    """
    con.row_factory = sqlite3.Row
    today = datetime.date.today()
    mm = f"{today.month:02d}"

    done = {r["ref_key"] for r in con.execute(
        "SELECT ref_key FROM approach_history WHERE COALESCE(ref_key,'')<>''")}
    items = []

    def add(kind, r, when, ref_key, detail="", overdue=False):
        if ref_key in done:
            return
        items.append({
            "kind": kind, "customer_id": r["customer_id"], "name": r["name"],
            "staff_name": r["staff_name"], "date": when.isoformat(),
            "when_text": f"{when.month}/{when.day}", "detail": detail,
            "overdue": 1 if overdue else 0, "ref_key": ref_key,
        })

    # ── 誕生日・結婚記念日(今月ぶん・過ぎた日は出さない) ──
    for kind, col in (("誕生日", "birthday"), ("結婚記念日", "wedding_day")):
        for r in con.execute(f"""SELECT customer_id,name,staff_name,address,dm_ok,exclude_stats,
                                        {col} d
                                 FROM customers
                                 WHERE COALESCE({col},'')<>'' AND substr({col},6,2)=?""", (mm,)):
            d = _parse_date(r["d"])
            if not d or d.day < today.day or _care_skip_outreach(r):
                continue
            add(kind, r, datetime.date(today.year, today.month, d.day),
                f"{kind}:{r['customer_id']}:{today.year}")

    # ── ポイント失効間近(失効日の30日前から) ──
    years = max(1, int(point_settings(con).get("card_expiry_years") or 5))
    for r in con.execute("""SELECT c.customer_id,c.name,c.staff_name,c.address,c.dm_ok,
                                   c.exclude_stats, b.balance,
                                   MAX(s.sold_at) last_buy
                            FROM customers c
                            JOIN point_balances b ON b.customer_id=c.customer_id AND b.balance>0
                            LEFT JOIN sales_slips s ON s.customer_id=c.customer_id
                                 AND COALESCE(s.voided,0)=0
                            GROUP BY c.customer_id"""):
        last = _parse_date(r["last_buy"])
        if not last or _care_skip_outreach(r):
            continue
        expiry = _add_years(last, years)
        left = (expiry - today).days
        if 0 <= left <= CARE_POINT_DAYS:
            add("ポイント失効", r, expiry,
                f"ポイント失効:{r['customer_id']}:{expiry.year}",
                detail=f"{r['balance']:,}pt({expiry.month}/{expiry.day}まで)")

    # ── 修理納期(7日前から。過ぎた分も出し続ける) ──
    for r in con.execute("""SELECT rp.id, rp.item_name, rp.promised_at,
                                   c.customer_id, c.name, c.staff_name
                            FROM repairs rp JOIN customers c ON c.customer_id=rp.customer_id
                            WHERE COALESCE(rp.promised_at,'')<>''
                                  AND COALESCE(rp.status,'') <> '引渡済み'"""):
        d = _parse_date(r["promised_at"])
        if not d:
            continue
        left = (d - today).days
        if left <= CARE_REPAIR_DAYS:
            add("修理納期", r, d, f"修理納期:{r['id']}",
                detail=r["item_name"] or "", overdue=left < 0)

    # 期限が近い順。過ぎているものを先頭に出す(放置が一番まずいため)
    items.sort(key=lambda x: (not x["overdue"], x["date"]))
    return {"items": items[:CARE_MAX], "total": len(items)}


def record_care_done(con, p):
    """ホームの「お声がけ」の✓。アプローチ履歴に記録し、同じ用件を二度出さないようにする。

    undo=1 で取り消す(押し間違いを戻せるようにする。記録を消すだけ)。
    """
    cid = str(p.get("customer_id") or "").strip()
    ref_key = str(p.get("ref_key") or "").strip()
    if not cid or not ref_key:
        raise ValueError("お声がけの対象が指定されていません")
    with write_lock(con):
        if p.get("undo"):
            con.execute("DELETE FROM approach_history WHERE ref_key=?", (ref_key,))
        else:
            # 二重に押されても履歴が増えないようにする
            row = con.execute("SELECT 1 FROM approach_history WHERE ref_key=?", (ref_key,)).fetchone()
            if not row:
                con.execute("""INSERT INTO approach_history
                                 (customer_id,approach_date,kind,title,staff_name,done,ref_key)
                               VALUES (?,?,?,?,?,1,?)""",
                            (cid, datetime.date.today().isoformat(),
                             str(p.get("kind") or ""), str(p.get("title") or ""),
                             p.get("staff_name"), ref_key))
    con.commit()
    return {"ok": True, "care": care_list(con)}


def build_blob(con):
    """全画面ぶんのデータを1つのdictにまとめて返す(埋め込み版と同一形状)。"""
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 売上合算(累計・2026年度・最終購入日)を明細から算出
    totals, y2026, last_buy = {}, {}, {}
    for r in cur.execute("""
        SELECT s.customer_id cid, SUM(l.amount) tot,
               SUM(CASE WHEN s.sold_at LIKE '2026%' THEN l.amount ELSE 0 END) y26,
               MAX(s.sold_at) last
        FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
        WHERE s.customer_id IS NOT NULL AND l.amount IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
        GROUP BY s.customer_id"""):
        totals[r["cid"]] = r["tot"] or 0
        y2026[r["cid"]] = r["y26"] or 0
        last_buy[r["cid"]] = r["last"]

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day,
                                   is_test,note,postal,address2,tel2,email,rank,dm_ok,district,exclude_stats
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y2026.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),   # 11=テスト印 12=用途 13=最終購入日
            r["postal"], r["address2"],                    # 14=郵便番号 15=建物名等
            r["tel2"], r["email"],                         # 16=携帯電話(TEL2) 17=eメール
            r["rank"], r["dm_ok"], r["district"], r["exclude_stats"],  # 18=ランク 19=DM 20=地区 21=集計対象外
        ])

    def group(sql, key_idx=0):
        d = {}
        for row in cur.execute(sql):
            vals = list(row)
            d.setdefault(str(vals[key_idx]), []).append(vals[1:])
        return d

    sales = group("""SELECT s.customer_id, s.sold_at, COALESCE(l.free_name, p.name), l.info,
                            l.amount, s.pay_method, s.staff_name, p.product_no
                     FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
                     LEFT JOIN products p ON l.product_key = p.product_key
                     WHERE s.customer_id IS NOT NULL
                           AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
                     ORDER BY s.sold_at DESC""")

    families = group("""SELECT customer_id, name, relation, gender, birthday, linked_customer_id, id
                        FROM customer_families ORDER BY id""")

    urikake = group("""SELECT customer_id, id, product_name, bought_at, down_payment, balance, last_paid_at,
                              slip_id
                       FROM receivables ORDER BY bought_at DESC, id DESC""")
    # 売掛行の末尾に「同じ会計での支払内訳」を入れる(現金＋クレジット＋掛売の併用払いで、
    # 現金/クレジットをいくら受け取ったかを売掛明細から確認できるようにする)
    _pt = slip_pay_texts(con)
    for _rows in urikake.values():
        for _r in _rows:
            _r[6] = _pt.get(_r[6]) or None
    urikake_hist = group("""SELECT customer_id, entry_date, entry_type, product_name, amount, paid, method
                            FROM receivable_entries ORDER BY entry_date DESC""")

    point_tx = group("""SELECT customer_id, occurred_at, tx_type, add_points, use_points, balance
                        FROM point_transactions ORDER BY occurred_at DESC""")
    points = {str(r["customer_id"]): r["balance"]
              for r in cur.execute("SELECT customer_id, balance FROM point_balances")}

    approach = group("""SELECT customer_id, approach_date, kind, title, staff_name
                        FROM approach_history ORDER BY approach_date DESC""")

    rx = {}
    for r in cur.execute("SELECT * FROM prescriptions ORDER BY id DESC"):
        name_l, name_f = r["lens_name"], r["frame_name"]
        # 誤登録判定は取込時に商品分類で確定済み(jewelry_misassign)の値のみを使う。
        # 商品名の文字列に対する正規表現の再判定はPT/SV等の短い断片で誤検知するため行わない。
        misassign = bool(r["jewelry_misassign"])
        rx.setdefault(str(r["customer_id"]), []).append({
            "id": r["id"], "rx_no": r["rx_no"], "purpose": r["purpose"],
            "lens_name": name_l, "frame_name": name_f,
            "lens_price": r["lens_price"], "frame_price": r["frame_price"], "total": r["total_sell"],
            "misassign": misassign, "sale_line_id": r["sale_line_id"],
            "sph_r": r["sph_r"], "sph_l": r["sph_l"], "cyl_r": r["cyl_r"], "cyl_l": r["cyl_l"],
            "ax_r": r["ax_r"], "ax_l": r["ax_l"], "pri_r": r["pri_r"], "pri_l": r["pri_l"],
            "base_r": r["base_r"], "base_l": r["base_l"],
            "pri2_r": r["pri2_r"], "pri2_l": r["pri2_l"], "base2_r": r["base2_r"], "base2_l": r["base2_l"],
            "add_r": r["add_r"], "add_l": r["add_l"],
            "pd_far_both": r["pd_far_both"], "pd_far_r": r["pd_far_r"], "pd_far_l": r["pd_far_l"],
            "pd_near_both": r["pd_near_both"], "pd_near_r": r["pd_near_r"], "pd_near_l": r["pd_near_l"],
            "naked_both": r["naked_both"], "naked_r": r["naked_r"], "naked_l": r["naked_l"],
            "corrected_both": r["corrected_both"], "corrected_r": r["corrected_r"], "corrected_l": r["corrected_l"],
            "handler": r["handler"], "rx_date": r["rx_date"],
        })

    # 処方箋に未紐付けの「メガネ関連の購入明細」(処方箋追加時に選べる候補)
    linked = set(r[0] for r in cur.execute(
        "SELECT sale_line_id FROM prescriptions WHERE sale_line_id IS NOT NULL"))
    rx_candidates = {}
    for r in cur.execute("""
        SELECT s.customer_id cid, l.line_id, s.sold_at, l.amount,
               COALESCE(l.free_name, p.name) nm, p.is_glasses g, p.category cat
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0"""):
        nm = r["nm"] or ""
        is_glass = r["g"] == 1 or bool(GLASS_PAT.search(nm))
        if is_glass and r["line_id"] not in linked:
            rx_candidates.setdefault(str(r["cid"]), []).append(
                [r["line_id"], r["sold_at"], nm, r["amount"], glass_kind(r["cat"], nm)])

    products = []
    for r in cur.execute("""SELECT product_no,name,category,list_price,state,location,
                                   center_stone,center_carat,product_key,image_file,cost_price,supplier
                            FROM products ORDER BY product_no"""):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        products.append([r["product_no"], r["name"], r["category"], r["list_price"],
                         r["state"], r["location"], stone or None, r["product_key"], r["image_file"],
                         r["cost_price"], r["supplier"]])

    repairs = []
    for r in cur.execute("""SELECT id,repair_no,customer_id,item_name,issue,estimate,
                                   received_at,promised_at,status,completed_at,staff_name,note,photo_files
                            FROM repairs ORDER BY id DESC"""):
        repairs.append({
            "id": r["id"], "repair_no": r["repair_no"], "customer_id": r["customer_id"],
            "item_name": r["item_name"], "issue": r["issue"], "estimate": r["estimate"],
            "received_at": r["received_at"], "promised_at": r["promised_at"],
            "status": r["status"], "completed_at": r["completed_at"],
            "staff_name": r["staff_name"], "note": r["note"],
            "photos": [x for x in (r["photo_files"] or "").split(",") if x],
        })

    # 在庫サマリ(状態=在庫の商品のみ)。会計確定・返品でリアルタイムに変わるため /api/stock_stats でも取り直せる。
    stock_summary = stock_stats(con)

    # 支払方法の内訳(フラット配列)。日報等で「支払方法別の実額」を正確に集計するために使う
    # (1会計が複数方法に分かれる場合、明細1行ごとの支払方法は代表ラベルに過ぎないため)
    tenders = []
    for r in cur.execute("""SELECT s.sold_at, sp.method, sp.amount, s.customer_id
                            FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
                            WHERE (COALESCE(s.voided,0)=0
                                   OR substr(COALESCE(s.voided_at,''),1,10) <> s.sold_at)
                            ORDER BY s.sold_at DESC"""):
        tenders.append([r["sold_at"], r["method"], r["amount"], str(r["customer_id"])])

    return dict(customers=customers, sales=sales, families=families, points=points,
                pointTx=point_tx, urikake=urikake, urikakeHist=urikake_hist,
                approach=approach, rx=rx, rxCandidates=rx_candidates, products=products,
                repairs=repairs, tenders=tenders, stockStats=stock_summary,
                care=care_list(con),
                pointSettings=point_settings(con),
                tagSettings=tag_settings(con))


def build_blob_light(con):
    """起動時にブラウザへ渡す軽量データ。重い明細(売上/処方箋/処方箋候補/ポイント履歴/
    アプローチ/商品)は含めず、顧客一覧と小さな集計だけを返す(全データ一括送信=60MB超を回避)。
    重い明細は必要時に取得する:
      顧客詳細 → /api/customer_detail  / 商品 → /api/products
      日報・期間集計 → /api/daily_sales, /api/slip_lines
    """
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 一覧表示に要る集計値(累計・当年度・最終購入日)は明細から先に算出しておく
    totals, y_cur, last_buy = {}, {}, {}
    cur_year = str(datetime.date.today().year)
    for r in cur.execute("""
        SELECT s.customer_id cid, SUM(l.amount) tot,
               SUM(CASE WHEN s.sold_at LIKE ? THEN l.amount ELSE 0 END) yc,
               MAX(s.sold_at) last
        FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
        WHERE s.customer_id IS NOT NULL AND l.amount IS NOT NULL
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
        GROUP BY s.customer_id""", (cur_year + "%",)):
        totals[r["cid"]] = r["tot"] or 0
        y_cur[r["cid"]] = r["yc"] or 0
        last_buy[r["cid"]] = r["last"]

    customers = []
    for r in cur.execute("""SELECT customer_id,name,kana,tel,staff_name,address,birthday,gender,wedding_day,
                                   is_test,note,postal,address2,tel2,email,rank,dm_ok,district,exclude_stats
                            FROM customers ORDER BY is_test DESC, CAST(customer_id AS INTEGER)"""):
        cid = r["customer_id"]
        customers.append([
            cid, r["name"], r["kana"], r["tel"], r["staff_name"], r["address"],
            r["birthday"], r["gender"], totals.get(cid, 0), y_cur.get(cid, 0), r["wedding_day"],
            r["is_test"], r["note"], last_buy.get(cid),
            r["postal"], r["address2"], r["tel2"], r["email"],
            r["rank"], r["dm_ok"], r["district"], r["exclude_stats"],  # 18=ランク 19=DM 20=地区 21=集計対象外
        ])

    def group(sql, key_idx=0):
        d = {}
        for row in cur.execute(sql):
            vals = list(row)
            d.setdefault(str(vals[key_idx]), []).append(vals[1:])
        return d

    # 顧客詳細で使うが小さい(合計0.5MB程度)ものと、日報/売掛集計で全件走査するものは
    # 起動時に持っておく(遅延化しても効果が薄く、集計側の作り直しが増えるため)
    families = group("""SELECT customer_id, name, relation, gender, birthday, linked_customer_id, id
                        FROM customer_families ORDER BY id""")
    urikake = group("""SELECT customer_id, id, product_name, bought_at, down_payment, balance, last_paid_at,
                              slip_id
                       FROM receivables ORDER BY bought_at DESC, id DESC""")
    # 売掛行の末尾に「同じ会計での支払内訳」を入れる(現金＋クレジット＋掛売の併用払いで、
    # 現金/クレジットをいくら受け取ったかを売掛明細から確認できるようにする)
    _pt = slip_pay_texts(con)
    for _rows in urikake.values():
        for _r in _rows:
            _r[6] = _pt.get(_r[6]) or None
    urikake_hist = group("""SELECT customer_id, entry_date, entry_type, product_name, amount, paid, method
                            FROM receivable_entries ORDER BY entry_date DESC""")
    points = {str(r["customer_id"]): r["balance"]
              for r in cur.execute("SELECT customer_id, balance FROM point_balances")}

    repairs = []
    for r in cur.execute("""SELECT id,repair_no,customer_id,item_name,issue,estimate,
                                   received_at,promised_at,status,completed_at,staff_name,note,photo_files
                            FROM repairs ORDER BY id DESC"""):
        repairs.append({
            "id": r["id"], "repair_no": r["repair_no"], "customer_id": r["customer_id"],
            "item_name": r["item_name"], "issue": r["issue"], "estimate": r["estimate"],
            "received_at": r["received_at"], "promised_at": r["promised_at"],
            "status": r["status"], "completed_at": r["completed_at"],
            "staff_name": r["staff_name"], "note": r["note"],
            "photos": [x for x in (r["photo_files"] or "").split(",") if x],
        })

    stock_summary = stock_stats(con)

    tenders = []
    for r in cur.execute("""SELECT s.sold_at, sp.method, sp.amount, s.customer_id
                            FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
                            WHERE (COALESCE(s.voided,0)=0
                                   OR substr(COALESCE(s.voided_at,''),1,10) <> s.sold_at)
                            ORDER BY s.sold_at DESC"""):
        tenders.append([r["sold_at"], r["method"], r["amount"], str(r["customer_id"])])

    # 担当者(有効なもの)。各画面の担当者プルダウンをマスタ連動にするため。
    # staffテーブルが空なら顧客の担当者名から拾ってフォールバック(サンプルDB等)
    staff = [r["name"] for r in cur.execute("SELECT name FROM staff WHERE active=1 ORDER BY name")]
    if not staff:
        staff = [r["staff_name"] for r in cur.execute(
            "SELECT DISTINCT staff_name FROM customers WHERE staff_name IS NOT NULL AND staff_name<>'' ORDER BY staff_name")]
    # レジ会計担当のワンタップバーに出す担当者(is_register=1 の有効な人だけ。デフォルトOFF)。
    # 並び順は担当者番号(staff_code)順。番号の無い人は末尾に名前順で。
    # 誰も設定していない(全部OFF)場合に限り staff 全体にフォールバック(会計不能を防ぐ安全策)。
    register_staff = [r["name"] for r in cur.execute(
        "SELECT name FROM staff WHERE active=1 AND COALESCE(is_register,0)=1 "
        "ORDER BY (staff_code IS NULL OR staff_code=''), CAST(staff_code AS INTEGER), name")]
    if not register_staff:
        register_staff = staff
    # 担当者の「番号」入力(コード検索)用。有効な担当者のcode/nameペア
    staff_codes = [[r["staff_code"], r["name"]] for r in cur.execute(
        "SELECT staff_code, name FROM staff WHERE active=1")]

    return dict(customers=customers, families=families, points=points,
                urikake=urikake, urikakeHist=urikake_hist,
                repairs=repairs, tenders=tenders, stockStats=stock_summary, staff=staff,
                registerStaff=register_staff, staffCodes=staff_codes,
                cashMovements=list_cash_movements(con),
                pointSettings=point_settings(con),
                tagSettings=tag_settings(con),
                lite=True)  # lite=True で「明細は遅延取得」とUIに知らせる


def _col(r, key, default=None):
    """sqlite3.Row から列を安全に取り出す(古いDBに新しい列が無い場合は default)。
    ensure_schema で列を足す前のDBや、SELECT に含めていない場合でも落ちないようにする。"""
    try:
        return r[key]
    except (IndexError, KeyError):
        return default


def _rx_row(r):
    """prescriptions の1行を画面用dictに変換(build_blob と customer_detail で共用)。"""
    return {
        "id": r["id"], "rx_no": r["rx_no"], "purpose": r["purpose"],
        "lens_name": r["lens_name"], "frame_name": r["frame_name"],
        "frame_type": _col(r, "frame_type"),  # セル/メタル/ツーポ/ナイロール
        "lens_price": r["lens_price"], "frame_price": r["frame_price"], "total": r["total_sell"],
        "misassign": _rx_misassign(r["jewelry_misassign"], r["lens_name"], r["frame_name"]),
        "sale_line_id": r["sale_line_id"],
        "sph_r": r["sph_r"], "sph_l": r["sph_l"], "cyl_r": r["cyl_r"], "cyl_l": r["cyl_l"],
        "ax_r": r["ax_r"], "ax_l": r["ax_l"], "pri_r": r["pri_r"], "pri_l": r["pri_l"],
        "base_r": r["base_r"], "base_l": r["base_l"],
        "pri2_r": r["pri2_r"], "pri2_l": r["pri2_l"], "base2_r": r["base2_r"], "base2_l": r["base2_l"],
        "add_r": r["add_r"], "add_l": r["add_l"],
        "pd_far_both": r["pd_far_both"], "pd_far_r": r["pd_far_r"], "pd_far_l": r["pd_far_l"],
        "pd_near_both": r["pd_near_both"], "pd_near_r": r["pd_near_r"], "pd_near_l": r["pd_near_l"],
        "naked_both": r["naked_both"], "naked_r": r["naked_r"], "naked_l": r["naked_l"],
        "corrected_both": r["corrected_both"], "corrected_r": r["corrected_r"], "corrected_l": r["corrected_l"],
        "handler": r["handler"], "rx_date": r["rx_date"],
    }


def pay_fallback(pay_method, credit_kind=None):
    """支払方法の表示文字列を作る。移行データは「掛売区分」が空のことが多く、そのまま出すと
    購入履歴の支払が「—」になってしまう。宝飾ナビの運用では
      掛売区分あり→その区分 / クレジット種別あり→クレジット / どちらも空→現金
    なので、この順で埋める(日報の `pay_method or "現金"` と表示を揃える)。"""
    pm = str(pay_method or "").strip()
    ck = str(credit_kind or "").strip()
    if pm and ck and ck not in pm:
        return f"{pm}({ck})"
    if pm:
        return pm
    if ck:
        return f"クレジット({ck})" if ck != "クレジット" else ck
    return "現金"


def slip_pay_texts(con, where_sql="", args=()):
    """伝票ごとの支払表示 {slip_id: "現金 ¥50,000 / クレジット ¥50,000"} を返す。
    現金＋クレジットの併用払いは sale_payments に内訳が入っているので、
    2種類以上あるときだけ金額つきで並べる(1種類なら金額は伝票合計と同じなので方法だけ)。"""
    rows = con.execute(
        "SELECT sp.slip_id, sp.method, sp.amount FROM sale_payments sp "
        "JOIN sales_slips s ON s.slip_id = sp.slip_id " + where_sql +
        " ORDER BY sp.slip_id, sp.id", args).fetchall()
    by_slip = {}
    for r in rows:
        by_slip.setdefault(r["slip_id"], []).append((r["method"] or "現金", int(r["amount"] or 0)))
    out = {}
    for sid, parts in by_slip.items():
        parts = [(m, a) for m, a in parts if a]
        if len(parts) > 1:
            out[sid] = " / ".join(f"{m} ¥{a:,}" for m, a in parts)
        elif parts:
            out[sid] = parts[0][0]
    return out


def customer_detail(con, cid):
    """1顧客ぶんの重い明細(売上/処方箋/処方箋候補/ポイント履歴/アプローチ)を返す。
    顧客詳細を開いた時にだけ呼ぶ(遅延取得)。UIの D.sales[id] 等と同じ形状。"""
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cid = str(cid)

    # 品名の差し替え表: 明細ID → 処方箋の正式名(レンズ名優先、無ければフレーム名)。
    # レジでは「メガネレンズ」等の仮名で会計し、後から処方箋で正式名を入れるため、
    # 購入一覧の品名は処方箋側を優先して表示する(v0.25.0からの仕様)。
    # ★明細1行ごとにサブクエリで処方箋を引く書き方はしない。顧客の処方箋を1回だけ
    #   取って辞書で突き合わせる(下の処方箋候補と同じパターン。意図が読める形を優先)。
    rx_names = {}
    for r in cur.execute("""SELECT sale_line_id, lens_name, frame_name FROM prescriptions
                            WHERE customer_id = ? AND sale_line_id IS NOT NULL
                            ORDER BY id""", (cid,)):
        nm = r["lens_name"] or r["frame_name"]
        if nm:
            rx_names.setdefault(r["sale_line_id"], nm)  # 同じ明細に複数あれば最初の1件

    sales = [list(r) for r in cur.execute("""
        SELECT s.sold_at, COALESCE(l.free_name, p.name) AS disp_name,
               l.info, l.amount, s.pay_method, s.staff_name, p.product_no, l.line_id, s.slip_id,
               s.credit_kind, p.image_file, l.product_key
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ?
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
        ORDER BY s.sold_at DESC""", (cid,))]

    # 支払表示を埋める(移行データの空欄対策＋現金/クレジット併用の内訳)。
    # 行の並びは [0]買上日 [1]品名 [2]商品情報 [3]金額 [4]支払 [5]担当 [6]商品番号
    #            [7]line_id [8]slip_id [9]credit_kind [10]画像 [11]商品キー → [4]を表示用に
    # 置き換え、[9]は画像ファイル名に詰め替えてUIへ渡す(popで[11]の商品キーは[10]へ繰り上がる)。
    # ★商品キー([10])は購入履歴→商品詳細のジャンプに使う。宝飾ナビは同じ商品番号を
    #   複数の商品に使い回すことがあり(実データ診断で17組確認)、番号では特定できない。
    pay_texts = slip_pay_texts(con, "WHERE s.customer_id = ?", (cid,))
    for row in sales:
        row[1] = rx_names.get(row[7]) or row[1]  # [7]=line_id。処方箋の正式名を優先
        row[4] = pay_texts.get(row[8]) or pay_fallback(row[4], row[9])
        row[9] = row.pop(10)  # [9]=商品画像(サムネイル用)。元[11]の商品キーが[10]になる

    # 取消(返品)済みの明細。監査ログとして「取消済みも表示」トグルON時のみ画面に出す。
    # 形状は sales と同じ並び＋[9]取消日時・[10]取消した担当者・[11]取消理由・[12]ログインユーザー。
    # 「誰が・なぜ取り消したか」を残すのは電子帳簿保存法の訂正削除履歴への対応(2026-07-31)。
    sales_voided = [list(r) for r in cur.execute("""
        SELECT s.sold_at, COALESCE(l.free_name, p.name) AS disp_name,
               l.info, l.amount, s.pay_method, s.staff_name, p.product_no, l.line_id, s.slip_id,
               l.voided_at,
               COALESCE(l.voided_staff, s.voided_staff, ''),
               COALESCE(l.voided_reason, s.voided_reason, ''),
               COALESCE(l.voided_by, s.voided_by, ''),
               s.credit_kind
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ? AND (COALESCE(l.voided,0)=1 OR COALESCE(s.voided,0)=1)
        ORDER BY s.sold_at DESC""", (cid,))]
    for row in sales_voided:  # 取消済み一覧も支払の表示を揃える([9]〜[12]の取消情報は維持)
        row[4] = pay_texts.get(row[8]) or pay_fallback(row[4], row.pop())

    point_tx = [list(r) for r in cur.execute("""
        SELECT occurred_at, tx_type, add_points, use_points, balance
        FROM point_transactions WHERE customer_id = ? ORDER BY occurred_at DESC""", (cid,))]

    approach = [list(r) for r in cur.execute("""
        SELECT approach_date, kind, title, staff_name
        FROM approach_history WHERE customer_id = ? ORDER BY approach_date DESC""", (cid,))]

    rx = [_rx_row(r) for r in cur.execute(
        "SELECT * FROM prescriptions WHERE customer_id = ? ORDER BY id DESC", (cid,))]

    linked = set(r[0] for r in cur.execute(
        "SELECT sale_line_id FROM prescriptions WHERE customer_id = ? AND sale_line_id IS NOT NULL", (cid,)))
    rx_candidates = []
    for r in cur.execute("""
        SELECT l.line_id, s.sold_at, l.amount,
               COALESCE(l.free_name, p.name) nm, p.is_glasses g, p.category cat
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        WHERE s.customer_id = ?
              AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0""", (cid,)):
        nm = r["nm"] or ""
        is_glass = r["g"] == 1 or bool(GLASS_PAT.search(nm))
        if is_glass and r["line_id"] not in linked:
            rx_candidates.append([r["line_id"], r["sold_at"], nm, r["amount"], glass_kind(r["cat"], nm)])

    return {"sales": sales, "salesVoided": sales_voided, "rx": rx, "rxCandidates": rx_candidates,
            "pointTx": point_tx, "approach": approach}


# 在庫一覧の並び替えで指定できる列(キー→実カラム。ホワイトリストでSQLインジェクション防止)
PRODUCT_SORT_COLS = {"no": "product_no", "name": "name", "cat": "category",
                     "list": "list_price", "cost": "cost_price", "state": "state",
                     "loc": "location", "supplier": "supplier"}


def _ean13_base(code):
    """スキャン値が EAN-13(13桁の数字・チェックデジット一致)なら、商品識別に使う
    先頭10桁を返す。宝飾ナビのタグは 管理番号の先頭4区画(XXXXX-Y-ZZ-WW=10桁)＋'00'＋
    チェックデジット の EAN-13。末尾区画(VVV)はバーコードに入らないため先頭10桁で照合する。
    手入力の商品番号(R-5000 / 17543-1-01-20-130 等)は EAN-13 でないので None を返す。
    スキャナが全角数字(２０５…)で入力しても照合できるよう先に幅を半角へ正規化する。"""
    s = norm_code(code)
    if len(s) != 13 or not s.isdigit():
        return None
    digs = [int(c) for c in s]
    chk = (10 - sum(d * (3 if i % 2 else 1) for i, d in enumerate(digs[:12])) % 10) % 10
    if chk != digs[12]:
        return None
    return s[:10]


def _resolve_code_conditions(code):
    """スキャン/入力値から products.product_no 照合用の (whereSQL, args) を返す。
    EAN-13 バーコードなら次の3通りに当てる(全角モードで入力されても半角化して照合)。
      ① 先頭5桁 = 品番。実データの商品番号は5桁の品番(例 20556)なので、これが本線。
      ② 先頭10桁で前方一致。商品番号にフル管理番号(20556-1-02-23-130)が入っている場合の保険。
      ③ 13桁そのまま。バーコードの数字を商品番号にしている場合の保険。
    ※バーコードには管理番号の末尾区画(VVV)が入らないため、同じ品番の在庫が複数あると
      バーコードだけでは個体を特定できない(呼び出し側で候補から選ぶ)。"""
    raw = norm_code(code)
    base = _ean13_base(raw)
    if base:
        return ("(product_no = ? OR product_no = ? OR REPLACE(product_no,'-','') LIKE ?)",
                [raw, base[:5], base + "%"])
    return ("product_no = ?", [raw])


def search_products(con, q="", cat="", state="", supplier="", genre="", sort="no", order="desc", limit=50, offset=0):
    """商品検索(在庫一覧・レジの商品ピッカー用)。全商品(21万件)を送らずサーバーで絞り込む。
    戻り値 {rows:[...], total:N}。rows は
      [商品番号,品名,分類,上代,状態,置場,石,商品キー,画像,下代,仕入先]。
    末尾寄りの商品キー(product_key)はレジで在庫引落・購入履歴の紐付けに使う内部キー。
    sort/order で並び替え(サーバー側。ページングと整合させるため)。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    where, args = [], []
    if q:
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        qn = norm_code(q)                       # 全角(かな)入力を半角化した品番/バーコード照合用
        liken = "%" + qn.replace("%", "").replace("_", "") + "%"
        base = _ean13_base(q)  # バーコード(EAN-13)なら品番(先頭5桁)と管理番号(先頭10桁)で照合
        if base:
            where.append("(product_no LIKE ? OR name LIKE ? OR product_no = ? "
                         "OR REPLACE(product_no,'-','') LIKE ?)")
            args += [liken, like, base[:5], base + "%"]
        else:
            where.append("(product_no LIKE ? OR product_no LIKE ? OR name LIKE ?)")
            args += [like, liken, like]
    if cat:
        where.append("category = ?"); args.append(cat)
    if state:
        where.append("state = ?"); args.append(state)
    if supplier:
        where.append("supplier = ?"); args.append(supplier)
    if genre:
        # 仕入先ジャンルで絞り込み(仕入先マスタで該当ジャンルに設定された仕入先の商品のみ)
        where.append("supplier IN (SELECT name FROM supplier_master WHERE genre = ?)")
        args.append(genre)
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    col = PRODUCT_SORT_COLS.get(sort, "product_no")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    order_sql = f" ORDER BY {col} {direction}, product_no"  # col/directionは固定候補のみで安全
    total = con.execute("SELECT COUNT(*) FROM products" + wsql, args).fetchone()[0]
    rows = []
    for r in con.execute(
            "SELECT product_no,name,category,list_price,cost_price,state,location,"
            "center_stone,center_carat,supplier,product_key,image_file,brand,metal "
            "FROM products" + wsql + order_sql + " LIMIT ? OFFSET ?", args + [limit, offset]):
        stone = r["center_stone"] or ""
        if stone and r["center_carat"]:
            stone += f' {r["center_carat"]}ct'
        rows.append([r["product_no"], r["name"], r["category"], r["list_price"],
                     r["state"], r["location"], stone or None, r["product_key"], r["image_file"],
                     r["cost_price"], r["supplier"], r["brand"], r["metal"]])  # [11]=ブランド [12]=地金
    return {"rows": rows, "total": total}


def product_categories(con):
    """商品分類の一覧(在庫一覧の絞り込みプルダウン用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category<>'' ORDER BY category")]


def product_suppliers(con):
    """仕入先の一覧(在庫一覧・レジの商品ピッカーの絞り込みプルダウン用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT supplier FROM products WHERE supplier IS NOT NULL AND supplier<>'' ORDER BY supplier")]


SUPPLIER_GENRES = ("宝石", "メガネ", "時計", "その他")


def sync_supplier_master(con):
    """商品に登場する仕入先名を仕入先マスタに取り込む(未登録のみ・分類はNULL)。"""
    con.execute("""INSERT OR IGNORE INTO supplier_master(name, genre)
                   SELECT DISTINCT supplier, NULL FROM products
                   WHERE supplier IS NOT NULL AND supplier<>''""")
    con.commit()


def list_supplier_master(con):
    """仕入先マスタ一覧(分類割り当て画面用)。名前・ジャンル・商品件数・在庫数を返す。
    在庫数は state='在庫' の商品のみを数える(現在店頭にある枠)。並び替えはUI側で行う。"""
    sync_supplier_master(con)
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("""SELECT m.name, m.genre, m.fucho_head,
                                   (SELECT COUNT(*) FROM products p WHERE p.supplier = m.name) cnt,
                                   (SELECT COUNT(*) FROM products p WHERE p.supplier = m.name AND p.state='在庫') stock
                            FROM supplier_master m ORDER BY m.name"""):
        rows.append({"name": r["name"], "genre": r["genre"], "fucho_head": r["fucho_head"],
                     "count": r["cnt"], "stock": r["stock"]})
    return rows


def product_brands(con):
    """商品に登場するブランド名の一覧(登録・修正フォームの入力候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand<>'' ORDER BY brand")]


def product_metals(con):
    """商品に登場する地金の一覧(重複除去。詳細検索の候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT metal FROM products WHERE metal IS NOT NULL AND metal<>'' ORDER BY metal")]


def product_stones(con):
    """商品に登場する中石(石種)の一覧(重複除去。詳細検索の候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT center_stone FROM products WHERE center_stone IS NOT NULL AND center_stone<>'' ORDER BY center_stone")]


def prescription_purposes(con):
    """処方箋に登場する用途の一覧(重複除去。詳細検索の候補用)。"""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT purpose FROM prescriptions WHERE purpose IS NOT NULL AND purpose<>'' ORDER BY purpose")]


def search_options(con):
    """詳細検索フォームのプルダウン候補をまとめて返す(重複除去済み)。"""
    return {"categories": product_categories(con), "brands": product_brands(con),
            "metals": product_metals(con), "stones": product_stones(con),
            "suppliers": product_suppliers(con), "purposes": prescription_purposes(con)}


def set_supplier_genre(con, name, genre):
    """仕入先のジャンルを設定/変更する。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("仕入先が指定されていません")
    genre = (genre or "").strip() or None
    if genre is not None and genre not in SUPPLIER_GENRES:
        raise ValueError("不正なジャンルです")
    con.execute("""INSERT INTO supplier_master(name, genre) VALUES(?,?)
                   ON CONFLICT(name) DO UPDATE SET genre=excluded.genre""", (name, genre))
    con.commit()
    return {"name": name, "genre": genre}


def supplier_fucho_head(con, name):
    """仕入先の符丁文字(メーカー頭カナ)を返す。未登録は ''。符丁の1文字目に使う。"""
    name = str(name or "").strip()
    if not name:
        return ""
    r = con.execute("SELECT fucho_head FROM supplier_master WHERE name=?", (name,)).fetchone()
    return (r[0] or "") if r else ""


def set_supplier_fucho(con, name, head):
    """仕入先の符丁文字(メーカー頭カナ)を設定/変更する。空で解除。
    濁点付きカナ(半角だと2文字)も許容するため2文字まで受ける。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("仕入先が指定されていません")
    head = str(head or "").strip()[:2] or None
    con.execute("""INSERT INTO supplier_master(name, fucho_head) VALUES(?,?)
                   ON CONFLICT(name) DO UPDATE SET fucho_head=excluded.fucho_head""", (name, head))
    con.commit()
    return {"name": name, "fucho_head": head}


def sale_kind4(is_glasses, category, place):
    """売上を4分類(催事/メガネ/時計/店頭)に振り分ける(B-9)。
    優先順: (1)催事=購入場所が店頭以外 → (2)メガネ=is_glasses → (3)時計=分類に「時計」
    → (4)店頭=残り。店の目視集計に合わせ、催事(店外イベント)を最優先で切り出す。
    ※分類ルールは実データの購入場所コードの実態を見て今後調整可。"""
    pl = str(place or "").strip()
    if pl and pl not in ("店頭", "本店", "01", "0", "店内"):
        return "催事"
    if is_glasses:
        return "メガネ"
    if "時計" in str(category or ""):
        return "時計"
    return "店頭"


# ── 日報・帳票の集計ルール(2026-08-06 顧問税理士の確認に基づき確定) ──────────
# 締めた日の日報は後から変えない。判断基準は「売った日と同じ日に取り消したか」。
#   ・当日中の取消(締め前) … 訂正扱い。売上にも返品にも出さない(5回打ち直したら最終だけ残る)
#   ・日をまたいだ取消     … 売った日の日報はそのまま。**取消した日**の日報にマイナスの
#     返品行を出す(元の売上日を注記)。現金締めには返金方法が現金の分だけ反映する。
# SQL片: 「この明細は売った日のうちに取り消された(=訂正)」
_SAME_DAY_VOID = "(COALESCE(l.voided,0)=1 AND substr(COALESCE(l.voided_at,''),1,10) = s.sold_at)"


def daily_sales(con, date):
    """指定日のレジ売上明細(日報・ホームタイル用)。全売上をブラウザに持たずサーバーで集計。
    売上行は「売った日」基準(後日取消でも残す)。返品行は「取消した日」に ret=1 で出す。"""
    con.row_factory = sqlite3.Row
    out = []
    # 現金＋クレジット併用の内訳(sale_payments)を先に引いておき、支払欄に金額つきで出す
    pay_texts = slip_pay_texts(con, "WHERE s.sold_at = ?", (str(date),))
    for r in con.execute(f"""
        SELECT s.slip_id, s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.info, l.amount, s.pay_method, s.credit_kind,
               s.staff_name, p.is_glasses ig, p.category cat, s.place place
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sold_at = ? AND NOT {_SAME_DAY_VOID}""", (str(date),)):
        out.append({"cid": r["cid"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "info": r["info"], "amount": r["amount"] or 0,
                    "pay": pay_texts.get(r["slip_id"]) or pay_fallback(r["pay_method"], r["credit_kind"]),
                    "staff": r["staff_name"],
                    "kind4": sale_kind4(r["ig"], r["cat"], r["place"])})
    # 返品行: この日に取り消された明細(当日訂正は除く)をマイナスで出す
    for r in con.execute(f"""
        SELECT s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.info, l.amount,
               l.refund_method rm, s.pay_method, s.credit_kind,
               s.sold_at orig, l.voided_staff vstaff,
               p.is_glasses ig, p.category cat, s.place place
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE COALESCE(l.voided,0)=1 AND substr(COALESCE(l.voided_at,''),1,10) = ?
              AND NOT {_SAME_DAY_VOID}""", (str(date),)):
        method = r["rm"] or pay_fallback(r["pay_method"], r["credit_kind"])
        out.append({"cid": r["cid"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "info": r["info"], "amount": -(r["amount"] or 0),
                    "pay": f"返金({method})", "refund_method": method,
                    "staff": r["vstaff"], "ret": 1,
                    "note": f"{r['orig']}購入分の返品",
                    "kind4": sale_kind4(r["ig"], r["cat"], r["place"])})
    return out


def payment_totals(con, frm, to=None):
    """期間の支払方法別の合計(日報の「内訳」用)。現金＋クレジット併用でも、
    sale_payments の内訳ごとに集計するので「現金がいくら/クレジットがいくら」が分かる。
    sale_payments に内訳が無い伝票(移行データ)は、伝票の支払方法で明細金額を寄せる。

    集計ルール(_SAME_DAY_VOID のコメント参照):
      受け取ったお金は「売った日」に計上(後日取消でも売った日の締めは変えない)。
      返金は「取消した日」に返金方法でマイナス計上。
      伝票まるごと当日中の取消だけは訂正扱いで最初から無かったことにする。"""
    con.row_factory = sqlite3.Row
    to = to or frm
    # 「伝票まるごと売った日のうちに取消」(訂正)。お金は動かなかった扱いにする
    same_day_slip = ("(COALESCE(s.voided,0)=1 AND "
                     "substr(COALESCE(s.voided_at,''),1,10) = s.sold_at)")
    totals, seen = {}, set()
    for r in con.execute(f"""
        SELECT sp.method m, COALESCE(SUM(sp.amount),0) t, GROUP_CONCAT(DISTINCT s.slip_id) ids
        FROM sale_payments sp JOIN sales_slips s ON s.slip_id = sp.slip_id
        WHERE s.sold_at >= ? AND s.sold_at <= ? AND NOT {same_day_slip}
        GROUP BY sp.method""", (str(frm), str(to))):
        totals[r["m"] or "現金"] = totals.get(r["m"] or "現金", 0) + int(r["t"] or 0)
        for i in str(r["ids"] or "").split(","):
            if i:
                seen.add(int(i))
    for r in con.execute(f"""
        SELECT s.slip_id, s.pay_method pm, s.credit_kind ck, COALESCE(SUM(l.amount),0) t
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        WHERE s.sold_at >= ? AND s.sold_at <= ? AND NOT {same_day_slip}
        GROUP BY s.slip_id""", (str(frm), str(to))):
        if r["slip_id"] in seen:
            continue  # 内訳がある伝票は二重計上しない
        k = pay_fallback(r["pm"], r["ck"])
        totals[k] = totals.get(k, 0) + int(r["t"] or 0)
    # 返金: 取消した日が期間内の明細をマイナス計上(当日訂正の伝票は上で除外済みなので触らない)
    for r in con.execute(f"""
        SELECT l.refund_method rm, s.pay_method pm, s.credit_kind ck, COALESCE(SUM(l.amount),0) t
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        WHERE COALESCE(l.voided,0)=1
              AND substr(COALESCE(l.voided_at,''),1,10) >= ? AND substr(COALESCE(l.voided_at,''),1,10) <= ?
              AND NOT {same_day_slip} AND NOT {_SAME_DAY_VOID}
        GROUP BY rm, pm, ck""", (str(frm), str(to))):
        k = r["rm"] or pay_fallback(r["pm"], r["ck"])
        totals[k] = totals.get(k, 0) - int(r["t"] or 0)
    return [{"method": k, "amount": v} for k, v in
            sorted(totals.items(), key=lambda kv: -kv[1]) if v]


def slip_lines(con, frm, to, staff=""):
    """期間の売上伝票明細(売上集計・CSV用)。サーバー側で期間・担当者で絞り込む。"""
    con.row_factory = sqlite3.Row
    args = [str(frm), str(to)]
    staffsql = ""
    if staff:
        staffsql = " AND s.staff_name = ?"
        args.append(staff)
    out = []
    pay_texts = slip_pay_texts(con, "WHERE s.sold_at >= ? AND s.sold_at <= ?", (str(frm), str(to)))
    for r in con.execute(f"""
        SELECT s.slip_id, s.sold_at, s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.amount, s.pay_method, s.credit_kind, s.staff_name,
               p.is_glasses ig, p.category cat, s.place place
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE s.sold_at >= ? AND s.sold_at <= ? AND NOT {_SAME_DAY_VOID}""" + staffsql + """
        ORDER BY s.sold_at""", args):
        out.append({"date": r["sold_at"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "amount": r["amount"] or 0,
                    "pay": pay_texts.get(r["slip_id"]) or pay_fallback(r["pay_method"], r["credit_kind"]),
                    "staff": r["staff_name"],
                    "kind4": sale_kind4(r["ig"], r["cat"], r["place"])})
    # 返品行: 取消した日が期間内の明細をマイナスで出す(当日訂正は出さない)。
    # 売上行と同じ形＋ret/noteを持ち、日付順に混ぜて返す
    for r in con.execute(f"""
        SELECT substr(l.voided_at,1,10) vdate, s.customer_id cid, c.name cname,
               COALESCE(l.free_name, p.name) item, l.amount,
               l.refund_method rm, s.pay_method, s.credit_kind, s.sold_at orig,
               l.voided_staff vstaff, p.is_glasses ig, p.category cat, s.place place
        FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
        LEFT JOIN products p ON l.product_key = p.product_key
        LEFT JOIN customers c ON c.customer_id = s.customer_id
        WHERE COALESCE(l.voided,0)=1
              AND substr(COALESCE(l.voided_at,''),1,10) >= ? AND substr(COALESCE(l.voided_at,''),1,10) <= ?
              AND NOT {_SAME_DAY_VOID}""" + staffsql.replace("s.staff_name", "l.voided_staff") + """
        ORDER BY vdate""", args):
        method = r["rm"] or pay_fallback(r["pay_method"], r["credit_kind"])
        out.append({"date": r["vdate"], "name": r["cname"] or r["cid"], "item": r["item"],
                    "amount": -(r["amount"] or 0),
                    "pay": f"返金({method})", "staff": r["vstaff"], "ret": 1,
                    "note": f"{r['orig']}購入分の返品",
                    "kind4": sale_kind4(r["ig"], r["cat"], r["place"])})
    out.sort(key=lambda x: x["date"])
    return out


def customer_ranking(con, frm="", to="", kind="", limit=100, exclude=True):
    """購入額の顧客ランキング(B-4)。期間・対象カテゴリで絞り込み、合計購入額の多い順に返す。
      frm/to  … 販売日の期間(空なら全期間=累計)
      kind    … "" 全て / "メガネ"=メガネ商品のみ / "宝飾"=メガネ以外
      exclude … True で「集計対象外(ななし等)」と検証ペルソナを除外(既定)
    戻り値: [{customer_id,name,rank,total,count}] を total 降順で。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 100
    where = ["s.customer_id IS NOT NULL", "l.amount IS NOT NULL",
             "COALESCE(l.voided,0)=0", "COALESCE(s.voided,0)=0"]
    args = []
    if frm:
        where.append("s.sold_at >= ?"); args.append(str(frm))
    if to:
        where.append("s.sold_at <= ?"); args.append(str(to))
    if kind == "メガネ":
        where.append("p.is_glasses = 1")
    elif kind == "宝飾":
        where.append("COALESCE(p.is_glasses,0) = 0")
    if exclude:
        where.append("COALESCE(c.exclude_stats,0) = 0 AND COALESCE(c.is_test,0) = 0")
    sql = ("""SELECT s.customer_id cid, c.name cname, c.rank rank,
                     SUM(l.amount) total, COUNT(*) cnt
              FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
              LEFT JOIN products p ON l.product_key = p.product_key
              LEFT JOIN customers c ON c.customer_id = s.customer_id
              WHERE """ + " AND ".join(where) +
           " GROUP BY s.customer_id ORDER BY total DESC LIMIT ?")
    out = []
    for r in con.execute(sql, args + [limit]):
        out.append({"customer_id": r["cid"], "name": r["cname"] or r["cid"],
                    "rank": r["rank"], "total": r["total"] or 0, "count": r["cnt"]})
    return out


def prescription_search(con, frm="", to="", purpose="", misassign_only=False):
    """メガネ処方箋の横断検索(B-4)。顧客をまたいで処方箋を期間・用途で絞り込む。
    行から元の顧客詳細へ遷移できるよう customer_id と顧客名も返す。"""
    con.row_factory = sqlite3.Row
    where, args = ["1=1"], []
    if frm:
        where.append("rx.rx_date >= ?"); args.append(str(frm))
    if to:
        where.append("rx.rx_date <= ?"); args.append(str(to))
    if purpose:
        where.append("rx.purpose = ?"); args.append(purpose)
    if misassign_only:
        where.append("rx.jewelry_misassign = 1")
    out = []
    for r in con.execute("""
        SELECT rx.id, rx.customer_id cid, c.name cname, rx.rx_no, rx.rx_date, rx.purpose,
               rx.lens_name, rx.frame_name, rx.total_sell, rx.handler, rx.jewelry_misassign mis
        FROM prescriptions rx LEFT JOIN customers c ON c.customer_id = rx.customer_id
        WHERE """ + " AND ".join(where) + " ORDER BY rx.rx_date DESC, rx.id DESC LIMIT 500", args):
        mis = _rx_misassign(r["mis"], r["lens_name"], r["frame_name"])
        if misassign_only and not mis:
            continue  # 名称がメガネ品(誤検知)の行は「誤登録のみ」から除外
        out.append({"id": r["id"], "customer_id": r["cid"], "customer": r["cname"] or r["cid"],
                    "rx_no": r["rx_no"], "rx_date": r["rx_date"], "purpose": r["purpose"],
                    "lens_name": r["lens_name"], "frame_name": r["frame_name"],
                    "total": r["total_sell"], "handler": r["handler"], "misassign": mis})
    return out


def detailed_customer_search(con, p):
    """顧客の横断詳細検索(B-4拡張)。顧客属性＋購入商品属性＋処方箋属性をANDで絞り込み、
    条件に合う顧客の一覧を返す(DM・お声がけ抽出用)。
      p(すべて任意):
        顧客属性: name(氏名/カナ/ID部分一致), staff(担当名), rank, birth_month(1-12),
                  district(部分一致), gender('男'/'女'), dm_ok('1'=DM可のみ),
                  last_buy('none'|'1'|'3'|'5'), exclude('1'=集計対象外/検証を除外・既定)
        購入商品: p_category, p_brand, p_metal, p_stone(部分一致), p_supplier, p_name(品名部分一致),
                  buy_from, buy_to(買上日の期間), prod_match('same'=同一商品で全条件 / 'any'=別々の購入でも可)
        処方箋:   rx_purpose, rx_lens(レンズ名/フレーム名の部分一致), rx_from, rx_to(処方日の期間)
    戻り値: {rows:[[id,name,kana,tel,rank,district,total,staff]], count, truncated}"""
    con.row_factory = sqlite3.Row
    g = lambda k: str((p or {}).get(k) or "").strip()
    where, args = ["COALESCE(c.is_test,0)=0"], []

    # ── 顧客属性 ──
    if g("exclude") != "0":  # 既定で集計対象外(ななし等)を除外
        where.append("COALESCE(c.exclude_stats,0)=0")
    if g("name"):
        nn = "%" + normjp(g("name")) + "%"
        where.append("(normjp(c.name) LIKE ? OR normjp(c.kana) LIKE ? OR c.customer_id = ?)")
        args += [nn, nn, g("name")]
    if g("staff"):
        where.append("c.staff_name = ?"); args.append(g("staff"))
    if g("rank"):
        where.append("c.rank = ?"); args.append(g("rank"))
    if g("birth_month"):
        try:
            where.append("substr(c.birthday,6,2) = ?"); args.append("%02d" % int(g("birth_month")))
        except ValueError:
            pass
    if g("district"):
        where.append("normjp(c.district) LIKE ?"); args.append("%" + normjp(g("district")) + "%")
    if g("gender"):
        where.append("c.gender = ?"); args.append(g("gender"))
    if g("dm_ok") == "1":
        # 「DM可のみ」= DM区分が「送らない」でなく、住所の先頭にDM不可の記号も無い顧客。
        # 空欄は「可」として残す(店の運用で、出したくない時だけ値を入れているため)。
        # 従来は `COALESCE(c.dm_ok,0)=1` と数値の1を比べていたが、実際に入っている値は
        # 「送る/送らない」「可/不可」等の文字列で、一件も一致せず絞れていなかった。
        where.append("normjp(COALESCE(c.dm_ok,'')) NOT IN (%s)"
                     % ",".join("?" for _ in _DM_NO_NORM))
        args.extend(_DM_NO_NORM)
        where.append("(%s)" % " AND ".join(
            "normjp(COALESCE(c.address,'')) NOT LIKE ?" for _ in DM_BLOCK_REASONS))
        args.extend(normjp(k * 3) + "%" for k in DM_BLOCK_REASONS)

    # 最終購入(購入の最新日)。none=購入履歴なし / N=N年以上購入なし(購入はあるが古い)
    lb = g("last_buy")
    live_sales = ("SELECT 1 FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                  "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0")
    if lb == "none":
        where.append("NOT EXISTS(" + live_sales + ")")
    elif lb in ("1", "3", "5"):
        import datetime as _dt
        cutoff = (_dt.date.today() - _dt.timedelta(days=365 * int(lb))).isoformat()
        where.append("(SELECT MAX(ss.sold_at) FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                     "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0) < ?")
        args.append(cutoff)

    # ── 購入商品属性(EXISTS) ──
    def prod_conds():
        conds, a = [], []
        if g("p_category"):
            conds.append("pr.category = ?"); a.append(g("p_category"))
        if g("p_brand"):
            conds.append("pr.brand = ?"); a.append(g("p_brand"))
        if g("p_metal"):
            conds.append("pr.metal = ?"); a.append(g("p_metal"))
        if g("p_stone"):
            conds.append("normjp(pr.center_stone) LIKE ?"); a.append("%" + normjp(g("p_stone")) + "%")
        if g("p_supplier"):
            conds.append("pr.supplier = ?"); a.append(g("p_supplier"))
        if g("p_name"):
            conds.append("normjp(COALESCE(sl.free_name, pr.name)) LIKE ?"); a.append("%" + normjp(g("p_name")) + "%")
        return conds, a

    def exists_sale(extra_conds, extra_args):
        base = ("EXISTS(SELECT 1 FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                "LEFT JOIN products pr ON sl.product_key=pr.product_key "
                "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0")
        a = []
        for cnd in extra_conds:
            base += " AND " + cnd
        a += extra_args
        if g("buy_from"):
            base += " AND ss.sold_at >= ?"; a.append(g("buy_from"))
        if g("buy_to"):
            base += " AND ss.sold_at <= ?"; a.append(g("buy_to"))
        return base + ")", a

    pconds, pargs = prod_conds()
    has_period = bool(g("buy_from") or g("buy_to"))
    if pconds or has_period:
        if g("prod_match") == "any" and pconds:
            # 別々の購入でもよい: 各条件を個別のEXISTSにする(期間は各EXISTSに適用)
            for cnd, av in zip(pconds, pargs):
                sql, a = exists_sale([cnd], [av])
                where.append(sql); args += a
            if not pconds and has_period:
                sql, a = exists_sale([], [])
                where.append(sql); args += a
        else:
            # 既定(same): 同一商品(=同じ売上明細)が全条件を満たす
            sql, a = exists_sale(pconds, pargs)
            where.append(sql); args += a

    # ── 処方箋属性(EXISTS) ──
    rxc, rxa = [], []
    if g("rx_purpose"):
        rxc.append("rx.purpose = ?"); rxa.append(g("rx_purpose"))
    if g("rx_lens"):
        rl = "%" + normjp(g("rx_lens")) + "%"
        rxc.append("(normjp(rx.lens_name) LIKE ? OR normjp(rx.frame_name) LIKE ?)")
        rxa += [rl, rl]
    if g("rx_from"):
        rxc.append("rx.rx_date >= ?"); rxa.append(g("rx_from"))
    if g("rx_to"):
        rxc.append("rx.rx_date <= ?"); rxa.append(g("rx_to"))
    if rxc:
        where.append("EXISTS(SELECT 1 FROM prescriptions rx WHERE rx.customer_id=c.customer_id AND "
                     + " AND ".join(rxc) + ")")
        args += rxa

    total_sub = ("(SELECT COALESCE(SUM(sl.amount),0) FROM sale_lines sl JOIN sales_slips ss ON sl.slip_id=ss.slip_id "
                 "WHERE ss.customer_id=c.customer_id AND COALESCE(sl.voided,0)=0 AND COALESCE(ss.voided,0)=0)")
    LIMIT = 2000
    sql = ("SELECT c.customer_id id, c.name, c.kana, c.tel, c.rank, c.district, c.staff_name staff, "
           + total_sub + " total FROM customers c WHERE " + " AND ".join(where)
           + " ORDER BY total DESC LIMIT ?")
    rows = []
    for r in con.execute(sql, args + [LIMIT + 1]):
        rows.append([r["id"], r["name"], r["kana"], r["tel"], r["rank"], r["district"],
                     r["total"] or 0, r["staff"]])
    truncated = len(rows) > LIMIT
    if truncated:
        rows = rows[:LIMIT]
    return {"rows": rows, "count": len(rows), "truncated": truncated}


# ── ポイント設定(ルールマスタ) ──
# 店の運用に合わせて設定画面から変更できる。app_settings に保存し、無ければ既定値。
#   point_rate_yen    … 何円の買上で1pt(既定100=100円で1pt。旧デモの200円は撤廃)
#   point_use_no_grant… 1=ポイントを使った会計はポイントを付与しない(宝飾ナビと同じ運用)
#   card_expiry_years … カード有効期限 = 最終購入日 + N年(既定5年。券面リライト印字で使用)
# ※機器モード(レシート・カード機器を使うか)は設定ではなく「起動方法」で決まる
#   (server/app.py の HW_ENABLED。トキワ起動.bat=OFF / 機器ありで起動.bat=ON)。
POINT_SETTING_DEFAULTS = {
    "point_rate_yen": 100,
    "point_use_no_grant": 1,
    "card_expiry_years": 5,
    "card_message": "",   # 券面のフリーメッセージ(最大2行・全角22文字。空=印字なし)
    "receipt_message": "",  # レシート下部メッセージ(最大4行。空=印字なし)
    "receipt_thanks": "お買上げありがとうございます",  # レシートの感謝の一文(1行。空=印字なし)
}


def point_settings(con):
    """ポイント運用ルールを返す(未設定の項目は既定値)。
    文字列の設定は「保存された空文字」も尊重する(例: 感謝の一文を空=印字なしにする)。
    数値の設定だけは空・不正値を既定値扱いにする。"""
    out = dict(POINT_SETTING_DEFAULTS)
    for k in out:
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (k,)).fetchone()
        if row is None:
            continue
        if isinstance(POINT_SETTING_DEFAULTS[k], int):
            try:
                out[k] = int(row[0])
            except (ValueError, TypeError):
                pass
        else:
            out[k] = str(row[0])
    return out


def save_point_settings(con, p):
    """ポイント運用ルールを保存する。不正値は現行値のまま(黙って壊さない)。"""
    cur = point_settings(con)

    def norm(key, lo, hi):
        try:
            v = int(str(p.get(key)).replace(",", ""))
        except (ValueError, TypeError):
            return cur[key]
        return min(hi, max(lo, v))

    # 券面メッセージ: 改行は2行まで・制御文字除去・全体100文字まで
    msg = str(p.get("card_message", cur["card_message"]) or "")
    msg = "\n".join(ln.strip() for ln in msg.splitlines()[:2] if ln.strip())[:100]
    # レシート下部メッセージ: 改行は4行まで・全体200文字まで
    rmsg = str(p.get("receipt_message", cur["receipt_message"]) or "")
    rmsg = "\n".join(ln.strip() for ln in rmsg.splitlines()[:4] if ln.strip())[:200]
    # 感謝の一文: 1行のみ・36桁(全角18文字)に収まるよう50文字で切る。空=印字なし
    thanks = str(p.get("receipt_thanks", cur["receipt_thanks"]) or "")
    thanks = thanks.splitlines()[0].strip()[:50] if thanks.strip() else ""
    vals = {
        "point_rate_yen": norm("point_rate_yen", 1, 100000),
        "point_use_no_grant": 1 if str(p.get("point_use_no_grant", cur["point_use_no_grant"])) in ("1", "True", "true") else 0,
        "card_expiry_years": norm("card_expiry_years", 1, 99),
        "card_message": msg,
        "receipt_message": rmsg,
        "receipt_thanks": thanks,
    }
    for k, v in vals.items():
        _set_setting(con, k, str(v))
    con.commit()
    return vals


# ── 値札(タグ)の印字位置(app_settings に保存) ──
#   tag_offset_x / tag_offset_y … 印字位置をmm単位でずらす補正(右・下が＋)。
# プリンタの給紙のクセを吸収するための値。端末(ブラウザ)ではなくDBに置くのは、
#   ・レジPCから開いても他のPCから店内共有で開いてもURLが変わるため、ブラウザ保存だと
#     保存領域が分かれて「昨日合わせたのにズレる」が起きる
#   ・バックアップに含まれるので、PCの入れ替えや故障で設定が消えない
# ため。値札プリンタは1台なので、店で1つ持てば足りる(2台になったら要見直し)。
#   tag_scale_x / tag_scale_y  … 印字倍率の補正(%)。プリンタが全体を縮小/拡大して刷る分を戻す。
#     実機(Apeos C3530)で、4行ぶん128mmが3mm以上詰まる=約2%縮む事象が出たため用意した
#     (2026-08-03)。印刷ダイアログの倍率100%で直るのが本筋だが、機種によっては
#     ドライバが余白ぶん自動縮小するため、その分をこちらで戻せるようにしておく。
# ※表裏の180°回転(旧 tag_reverse)は設定から外した(2026-08-03)。台紙の帯の向きと
#   給紙の向きが固定の店では選ぶ余地がなく、「使う人に意識させたくない」との指示で
#   UI側の固定値 TAG_REVERSE(tokiwa-ui.html)に移した。DBに残った旧 tag_reverse の
#   行は読まれないだけで無害。
TAG_SETTING_DEFAULTS = {
    "tag_offset_x": 0.0,
    "tag_offset_y": 0.0,
    "tag_scale_x": 100.0,
    "tag_scale_y": 100.0,
}
TAG_OFFSET_MAX = 20.0            # ±20mm。実機で約10mm下へずれる事象があったため10→20に拡げた
                                 # (2026-08-03)。これを超えるなら用紙設定側の問題
TAG_SCALE_MIN, TAG_SCALE_MAX = 90.0, 110.0   # ±10%。これ以上ズレるなら設定側の問題


def _clamp_num(v, lo, hi):
    """数値にして lo〜hi に収める。数値でない・NaN・Inf は例外にする。"""
    f = float(str(v).strip())
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError("数値ではありません")
    return max(lo, min(hi, round(f, 2)))


def _clamp_tag_setting(key, v):
    """項目に応じた範囲で丸める(位置はmm・倍率は%)。"""
    if key.startswith("tag_scale"):
        return _clamp_num(v, TAG_SCALE_MIN, TAG_SCALE_MAX)
    return _clamp_num(v, -TAG_OFFSET_MAX, TAG_OFFSET_MAX)


def tag_settings(con):
    """値札の印字位置・倍率の補正を返す(未設定は既定値)。"""
    out = dict(TAG_SETTING_DEFAULTS)
    for k in out:
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (k,)).fetchone()
        if row is not None and str(row[0]).strip() != "":
            try:
                out[k] = _clamp_tag_setting(k, row[0])
            except (ValueError, TypeError):
                pass
    return out


def save_tag_settings(con, p):
    """値札の補正を保存する。不正値は現行値のまま(黙って壊さない)。"""
    cur = tag_settings(con)
    for k in TAG_SETTING_DEFAULTS:
        if k not in p:
            continue
        try:
            cur[k] = _clamp_tag_setting(k, p.get(k))
        except (ValueError, TypeError):
            pass    # 数値でなければ現行値を維持
    for k, v in cur.items():
        _set_setting(con, k, str(v))
    con.commit()
    return tag_settings(con)


# ── バックアップ設定(app_settings に保存。実処理は server/backup.py) ──
#   backup_enabled … 1=自動バックアップON(サーバー起動時＋1日1回)
#   backup_dirs    … 追加の保存先(改行区切り)。店外=外付けHDD・クラウド同期フォルダ。
#                    空でも店内 db/backups には必ず取る
#   backup_keep    … 保存先ごとに残す世代数(1世代だけだと壊れた状態で上書きした時に復旧不能)
#   backup_last_*  … 最終実行の記録(設定ではなくシステムが書く。画面表示用)
BACKUP_SETTING_DEFAULTS = {
    "backup_enabled": 1,
    "backup_dirs": "",
    "backup_keep": 14,
    "backup_last_at": "",
    "backup_last_result": "",
}


def backup_settings(con):
    """バックアップ設定＋最終実行の記録を返す(未設定は既定値)。"""
    out = dict(BACKUP_SETTING_DEFAULTS)
    for k in out:
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (k,)).fetchone()
        if row is not None and str(row[0]).strip() != "":
            if isinstance(BACKUP_SETTING_DEFAULTS[k], int):
                try:
                    out[k] = int(row[0])
                except (ValueError, TypeError):
                    pass
            else:
                out[k] = str(row[0])
    return out


def save_backup_settings(con, p):
    """バックアップ設定を保存する(最終実行の記録は書き換えない)。"""
    cur = backup_settings(con)
    try:
        keep = int(str(p.get("backup_keep", cur["backup_keep"])).replace(",", ""))
    except (ValueError, TypeError):
        keep = cur["backup_keep"]
    keep = min(365, max(1, keep))   # 1世代だけの運用は危険なため下限1・上限365
    # 保存先: 1行1パス・空行と重複を除く(最大5か所)
    dirs, seen = [], set()
    for ln in str(p.get("backup_dirs", cur["backup_dirs"]) or "").splitlines():
        d = ln.strip().strip('"')
        if d and d not in seen:
            seen.add(d)
            dirs.append(d)
    vals = {
        "backup_enabled": 1 if str(p.get("backup_enabled", cur["backup_enabled"])) in ("1", "True", "true") else 0,
        "backup_dirs": "\n".join(dirs[:5]),
        "backup_keep": keep,
    }
    for k, v in vals.items():
        _set_setting(con, k, str(v))
    con.commit()
    return backup_settings(con)


def record_backup_result(con, at, message):
    """バックアップの実行結果を記録する(画面に最終実行として表示する)。"""
    _set_setting(con, "backup_last_at", str(at or ""))
    _set_setting(con, "backup_last_result", str(message or "")[:500])
    con.commit()


def backup_counts(con):
    """前回バックアップ時の主要テーブル件数({テーブル名: 件数})。無ければ空。
    次回との比較で件数の急減(誤削除の兆候)を検知するために使う。"""
    row = con.execute("SELECT value FROM app_settings WHERE key='backup_counts'").fetchone()
    if not row or not str(row[0]).strip():
        return {}
    try:
        d = json.loads(row[0])
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def save_backup_counts(con, counts):
    """主要テーブル件数を記録する(次回の比較の基準になる)。"""
    _set_setting(con, "backup_counts", json.dumps(counts, ensure_ascii=False))
    con.commit()


def record_integrity_result(con, at, summary, checks):
    """データ点検の結果を記録する(画面の「最終点検」に表示する)。"""
    _set_setting(con, "integrity_last_at", str(at or ""))
    _set_setting(con, "integrity_last_summary", str(summary or "")[:500])
    _set_setting(con, "integrity_last_checks", json.dumps(checks or [], ensure_ascii=False))
    con.commit()


def integrity_status(con):
    """最後に実行したデータ点検の結果を返す(未実行なら空)。"""
    out = {"integrity_last_at": "", "integrity_last_summary": "", "checks": []}
    for k in ("integrity_last_at", "integrity_last_summary"):
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (k,)).fetchone()
        if row:
            out[k] = str(row[0] or "")
    row = con.execute("SELECT value FROM app_settings WHERE key='integrity_last_checks'").fetchone()
    if row and str(row[0]).strip():
        try:
            c = json.loads(row[0])
            out["checks"] = c if isinstance(c, list) else []
        except (ValueError, TypeError):
            pass
    return out


def adjust_points(con, p):
    """ポイントの手動修正(±)。宝飾ナビの「カードを入れてポイント修正」に相当する画面操作。
    理由を必須にして履歴(point_transactions)に「手動修正」として残す(監査できるように)。"""
    cid = str(p.get("customer_id") or "").strip()
    if not cid:
        raise ValueError("顧客が指定されていません")
    try:
        delta = int(str(p.get("delta")).replace(",", "").replace("+", ""))
    except (ValueError, TypeError):
        raise ValueError("修正ポイントを整数で入力してください(例: 500 / -300)")
    if delta == 0:
        raise ValueError("0ポイントの修正はできません")
    reason = str(p.get("reason") or "").strip()
    if not reason:
        raise ValueError("修正理由を入力してください(履歴に残ります)")
    # 残高の読み書きを排他する(別端末の会計・返品と同時に走ると残高が上書きし合うため)
    with write_lock(con):
        row = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
        bal = int(row[0] or 0) if row else 0
        newbal = bal + delta
        if newbal < 0:
            raise ValueError(f"残高が0未満になります(現在 {bal:,} pt)")
        today = datetime.date.today().isoformat()
        con.execute("""INSERT INTO point_transactions
            (customer_id,tx_type,points,add_points,use_points,balance,product_name,occurred_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (cid, "手動修正", abs(delta), delta if delta > 0 else None,
             -delta if delta < 0 else None, newbal, f"手動修正: {reason}", today))
        con.execute("""INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)
                       ON CONFLICT(customer_id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
                    (cid, newbal, today))
    return {"customer_id": cid, "balance": newbal, "delta": delta,
            "occurred_at": today, "reason": reason}


# 顧客ランクの既定基準(B-5)。宝飾ナビの合計金額ランク(1が最上位)に準拠。
# (下限金額, ランク名) を上から判定。設定画面で変更した場合は app_settings に保存される。
RANK_RULES = [
    (1000000, "1"), (500000, "2"), (300000, "3"), (200000, "4"),
    (100000, "5"), (50000, "6"), (9800, "7"), (1, "8"), (0, "9"),
]


def get_rank_rules(con):
    """顧客ランク基準を返す([[下限金額,ランク名],...]・下限の降順)。未設定なら既定値。"""
    row = con.execute("SELECT value FROM app_settings WHERE key='rank_rules'").fetchone()
    if row and row[0]:
        try:
            rules = [[int(r[0]), str(r[1])] for r in json.loads(row[0]) if str(r[1]).strip() != ""]
            if rules:
                rules.sort(key=lambda x: x[0], reverse=True)
                return rules
        except (ValueError, TypeError, IndexError):
            pass
    return [[lo, lab] for lo, lab in RANK_RULES]


def set_rank_rules(con, rules):
    """顧客ランク基準を保存する。rules=[[下限金額,ランク名],...]。"""
    clean = []
    for r in (rules or []):
        try:
            lo = int(str(r[0]).replace(",", ""))
        except (ValueError, TypeError, IndexError):
            continue
        lab = str(r[1]).strip() if len(r) > 1 else ""
        if lab != "":
            clean.append([lo, lab])
    if not clean:
        raise ValueError("有効な基準がありません(金額とランク名を入力してください)")
    clean.sort(key=lambda x: x[0], reverse=True)
    con.execute("INSERT INTO app_settings(key,value) VALUES('rank_rules',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(clean, ensure_ascii=False),))
    con.commit()
    return {"rules": clean}


def rank_for_amount(total, rules=None):
    """合計購入額から基準に沿ったランク名を返す。"""
    t = total or 0
    rules = rules if rules is not None else [list(x) for x in RANK_RULES]
    for lo, label in rules:
        if t >= lo:
            return label
    return rules[-1][1] if rules else ""


def compute_rank_updates(con, kind="", date_from="", date_to="", include_bottom=False):
    """全顧客の合計購入額から新ランクを算出し、現ランクと異なる顧客の一覧を返す(プレビュー)。
      kind: ""=全て / "宝飾" / "メガネ"。集計対象外・検証ペルソナ・取消明細は対象外。
      date_from/date_to: 集計する買上日の期間(YYYY-MM-DD、空なら全期間)。
      include_bottom: True なら最下位ランク(既定"9")の顧客も更新対象に含める(復活可)。
                      False(既定)なら最下位ランクの顧客は据え置き。
    ・distribution: ランクごとの「現在の人数 / 再計算後の人数」内訳(提案B)。
    戻り値: {rules, updates, total_customers, bottom_rank, skipped_bottom,
             include_bottom, distribution, date_from, date_to}"""
    con.row_factory = sqlite3.Row
    rules = get_rank_rules(con)
    bottom_rank = rules[-1][1] if rules else "9"
    where = ["s.customer_id IS NOT NULL", "l.amount IS NOT NULL",
             "COALESCE(l.voided,0)=0", "COALESCE(s.voided,0)=0"]
    args = []
    if kind == "メガネ":
        where.append("p.is_glasses=1")
    elif kind == "宝飾":
        where.append("COALESCE(p.is_glasses,0)=0")
    if date_from:
        where.append("s.sold_at >= ?"); args.append(str(date_from))
    if date_to:
        where.append("s.sold_at <= ?"); args.append(str(date_to))
    totals = {}
    for r in con.execute("""SELECT s.customer_id cid, SUM(l.amount) t
                            FROM sale_lines l JOIN sales_slips s ON l.slip_id = s.slip_id
                            LEFT JOIN products p ON l.product_key = p.product_key
                            WHERE """ + " AND ".join(where) + " GROUP BY s.customer_id", args):
        totals[r["cid"]] = r["t"] or 0
    labels = [r[1] for r in rules]
    dist_cur = {lab: 0 for lab in labels}   # 現在ランク別の人数
    dist_calc = {lab: 0 for lab in labels}  # 基準どおり再計算した場合の人数
    other_cur = 0  # ランク未設定・基準外の現ランク
    updates = []
    n = 0
    skipped_bottom = 0
    for r in con.execute("""SELECT customer_id, name, rank FROM customers
                            WHERE COALESCE(is_test,0)=0 AND COALESCE(exclude_stats,0)=0"""):
        n += 1
        cur_rank = r["rank"] or ""
        if cur_rank in dist_cur:
            dist_cur[cur_rank] += 1
        else:
            other_cur += 1
        cid = r["customer_id"]
        total = totals.get(cid, 0) or 0
        newr = rank_for_amount(total, rules)
        if newr in dist_calc:
            dist_calc[newr] += 1
        # 最下位ランクの顧客は既定で据え置き(include_bottom=True なら含める)
        if not include_bottom and cur_rank == bottom_rank:
            skipped_bottom += 1
            continue
        if cur_rank != newr:
            updates.append({"customer_id": cid, "name": r["name"] or cid,
                            "old": r["rank"], "new": newr, "total": total})
    updates.sort(key=lambda u: u["total"], reverse=True)
    distribution = [{"rank": lab, "min": rules[i][0],
                     "cur": dist_cur[lab], "calc": dist_calc[lab]}
                    for i, lab in enumerate(labels)]
    return {"rules": rules, "updates": updates, "total_customers": n,
            "bottom_rank": bottom_rank, "skipped_bottom": skipped_bottom,
            "include_bottom": bool(include_bottom), "distribution": distribution,
            "other_cur": other_cur, "date_from": date_from or "", "date_to": date_to or ""}


def apply_rank_updates(con, kind="", date_from="", date_to="", include_bottom=False):
    """compute_rank_updates の変更をまとめて customers.rank に反映する。"""
    res = compute_rank_updates(con, kind, date_from, date_to, include_bottom)
    cur = con.cursor()
    for u in res["updates"]:
        cur.execute("UPDATE customers SET rank=? WHERE customer_id=?", (u["new"], u["customer_id"]))
    con.commit()
    return {"updated": len(res["updates"])}


def _ensure_documents_table(con):
    """発行履歴テーブルを(無ければ)作る。既存DBでもマイグレーション不要で動くように。"""
    con.execute("""CREATE TABLE IF NOT EXISTS issued_documents (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_type   TEXT NOT NULL,          -- 'quote'=見積書 / 'invoice'=請求書
        issued_at  TEXT NOT NULL,          -- 発行日 YYYY-MM-DD
        to_name    TEXT,                   -- 宛名
        keisho     TEXT,                   -- 敬称(様/御中)
        total      INTEGER,                -- 合計(税込)
        tax        INTEGER,                -- 内消費税
        lines_json TEXT,                   -- 明細 [{name,amount},...] のJSON
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")


def save_document(con, p):
    """発行した見積書/請求書を履歴に保存する。"""
    _ensure_documents_table(con)
    lines = p.get("lines") or []
    cur = con.cursor()
    cur.execute("""INSERT INTO issued_documents(doc_type,issued_at,to_name,keisho,total,tax,lines_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (p.get("doc_type"), p.get("issued_at") or datetime.date.today().isoformat(),
                 p.get("to_name"), p.get("keisho"),
                 int(p.get("total") or 0), int(p.get("tax") or 0),
                 json.dumps(lines, ensure_ascii=False)))
    con.commit()
    return {"id": cur.lastrowid}


def list_documents(con, limit=100):
    """発行履歴の一覧(新しい順)。明細も含めて返し、UIで呼び出し→編集できるようにする。"""
    _ensure_documents_table(con)
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    out = []
    for r in con.execute("""SELECT id,doc_type,issued_at,to_name,keisho,total,tax,lines_json
                            FROM issued_documents ORDER BY id DESC LIMIT ?""", (limit,)):
        try:
            lines = json.loads(r["lines_json"] or "[]")
        except (ValueError, TypeError):
            lines = []
        out.append({"id": r["id"], "doc_type": r["doc_type"], "issued_at": r["issued_at"],
                    "to_name": r["to_name"], "keisho": r["keisho"], "total": r["total"],
                    "tax": r["tax"], "lines": lines})
    return out


def set_product_image(con, product_key, image_file):
    """商品の写真ファイル名を更新する(B-7 撮影・登録)。実ファイルの保存はサーバー側で行う。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    cur = con.execute("UPDATE products SET image_file=? WHERE product_key=?", (image_file, pk))
    con.commit()
    if cur.rowcount == 0:
        raise ValueError("対象の商品が見つかりません")
    return {"product_key": pk, "image_file": image_file}


def clear_product_image(con, product_key):
    """商品の写真を外す(間違って登録した写真を取り消す用)。商品自体は削除しない。
    直前まで紐づいていたファイル名を返すので、実ファイルの削除はapp.py側で行う。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    row = con.execute("SELECT image_file FROM products WHERE product_key=?", (pk,)).fetchone()
    if not row:
        raise ValueError("対象の商品が見つかりません")
    old_file = row[0]
    con.execute("UPDATE products SET image_file=NULL WHERE product_key=?", (pk,))
    con.commit()
    return {"product_key": pk, "removed_file": old_file}


# ── 写真プール(まとめて撮影→後で商品に割り当て) ──
def add_photo_pool_entry(con, filename):
    """アップロード済みの1枚をプールに登録する(実ファイル保存はapp.py側)。"""
    con.execute("INSERT INTO photo_pool(filename, uploaded_at) VALUES (?,?)",
                (filename, datetime.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_photo_pool(con):
    """未割当の写真プール一覧(古い=先に撮った順)。件数が多くなりやすいので撮影順消化を想定。"""
    return [{"id": r[0], "filename": r[1], "uploaded_at": r[2]}
            for r in con.execute("SELECT id, filename, uploaded_at FROM photo_pool ORDER BY id")]


def assign_photo_pool(con, pool_id, product_key):
    """プールの1枚を商品に割り当てる(商品のimage_fileに設定し、プールから外す)。"""
    row = con.execute("SELECT filename FROM photo_pool WHERE id=?", (pool_id,)).fetchone()
    if not row:
        raise ValueError("対象の写真が見つかりません(他の人が使用済みかもしれません)")
    fname = row[0]
    set_product_image(con, product_key, fname)
    con.execute("DELETE FROM photo_pool WHERE id=?", (pool_id,))
    con.commit()
    return {"product_key": str(product_key), "image_file": fname}


def delete_photo_pool_row(con, pool_id):
    """プールから1枚を除外する(使わない写真の整理用)。実ファイル削除はapp.py側で行う。"""
    row = con.execute("SELECT filename FROM photo_pool WHERE id=?", (pool_id,)).fetchone()
    if not row:
        raise ValueError("対象の写真が見つかりません")
    con.execute("DELETE FROM photo_pool WHERE id=?", (pool_id,))
    con.commit()
    return row[0]


# 汎用マスタの定義(「名前の一覧」型)。table/col は使用件数と改名時のデータ追随に使う。
# ※table/col はここの固定値のみ(ユーザー入力ではない)なのでSQL的に安全。
MASTERS = {
    "category":   {"label": "商品分類",   "table": "products",      "col": "category"},
    "brand":      {"label": "ブランド",   "table": "products",      "col": "brand"},
    "stone":      {"label": "石種",       "table": "products",      "col": "center_stone"},
    "metal":      {"label": "地金",       "table": "products",      "col": "metal",
                   "seed": ["Pt900", "Pt950", "K18", "K18YG", "K18WG",
                            "K18PG", "K24", "K14", "SV925"]},
    "district":   {"label": "地区",       "table": "customers",     "col": "district"},
    "location":   {"label": "保管場所",   "table": "products",      "col": "location"},
    "motive":     {"label": "購入動機",   "table": "sales_slips",   "col": "motive"},
    "pay_method": {"label": "支払方法",   "table": "sale_payments", "col": "method",
                   "seed": ["現金", "クレジット", "PayPay", "掛売", "分割"]},
    "rank":       {"label": "顧客ランク", "table": "customers",     "col": "rank",
                   "seed": ["SA", "A", "B", "C", "VIP"]},
}


def master_types():
    """管理できるマスタの一覧(マスタ管理TOPのプルダウン用)。"""
    return [{"type": k, "label": v["label"]} for k, v in MASTERS.items()]


def _master_cfg(mtype):
    cfg = MASTERS.get(mtype)
    if not cfg:
        raise ValueError("不明なマスタです")
    return cfg


def sync_master(con, mtype):
    """既存データ(＋seed)に登場する値をマスタに取り込む(未登録のみ)。
    table/col が無いマスタ(地金など)は seed のみ取り込む。"""
    cfg = _master_cfg(mtype)
    for nm in cfg.get("seed", []):
        con.execute("INSERT OR IGNORE INTO master_items(master_type,name) VALUES (?,?)", (mtype, nm))
    t, c = cfg.get("table"), cfg.get("col")
    if t and c:
        con.execute(f"""INSERT OR IGNORE INTO master_items(master_type,name)
                        SELECT ?, {c} FROM {t} WHERE {c} IS NOT NULL AND {c}<>'' GROUP BY {c}""", (mtype,))
    con.commit()


def list_master_items(con, mtype):
    """マスタの項目一覧＋各項目の使用件数(削除時の警告に使う)。
    table/col が無いマスタは使用件数を常に0で返す。"""
    cfg = _master_cfg(mtype)
    sync_master(con, mtype)
    t, c = cfg.get("table"), cfg.get("col")
    items = []
    for r in con.execute("SELECT name FROM master_items WHERE master_type=? ORDER BY name", (mtype,)):
        cnt = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {c}=?", (r[0],)).fetchone()[0] if (t and c) else 0
        items.append({"name": r[0], "count": cnt})
    return {"type": mtype, "label": cfg["label"], "items": items}


def save_master_item(con, p):
    """マスタ項目の 追加/改名/削除。改名時は実データの該当列も追随して置換する
    (table/col が無いマスタはマスタ一覧のみ更新)。"""
    mtype = p.get("type")
    cfg = _master_cfg(mtype)
    action = p.get("action")
    name = str(p.get("name") or "").strip()
    t, c = cfg.get("table"), cfg.get("col")
    cur = con.cursor()
    if action == "add":
        if not name:
            raise ValueError("名称を入力してください")
        cur.execute("INSERT OR IGNORE INTO master_items(master_type,name) VALUES (?,?)", (mtype, name))
    elif action == "rename":
        new = str(p.get("new_name") or "").strip()
        if not name or not new:
            raise ValueError("名称を入力してください")
        if new != name:
            cur.execute("INSERT OR IGNORE INTO master_items(master_type,name) VALUES (?,?)", (mtype, new))
            cur.execute("DELETE FROM master_items WHERE master_type=? AND name=?", (mtype, name))
            if t and c:
                cur.execute(f"UPDATE {t} SET {c}=? WHERE {c}=?", (new, name))  # 実データも追随
    elif action == "delete":
        cur.execute("DELETE FROM master_items WHERE master_type=? AND name=?", (mtype, name))
        # ※実データの値は残す(表示はできる)。マスタのプルダウン候補から消えるだけ。
    else:
        raise ValueError("不明な操作です")
    con.commit()
    return {"ok": True, "type": mtype, "action": action}


def sync_staff_from_names(con):
    """記録に登場する担当者名で staff テーブルに無いものを取り込む(コードは自動採番)。
    取込済みのstaffがある場合は既存を尊重し、名前が未登録のものだけ足す。"""
    existing = {r[0] for r in con.execute("SELECT name FROM staff")}
    row = con.execute("SELECT MAX(CAST(staff_code AS INTEGER)) FROM staff WHERE staff_code GLOB '[0-9]*'").fetchone()
    nxt = (row[0] or 0) + 1
    for r in con.execute("SELECT DISTINCT staff_name FROM customers WHERE staff_name IS NOT NULL AND staff_name<>''"):
        nm = r[0]
        if nm and nm not in existing:
            con.execute("INSERT OR IGNORE INTO staff(staff_code,name,active) VALUES (?,?,1)", (str(nxt), nm))
            existing.add(nm)
            nxt += 1
    con.commit()


# 担当者が実データで紐づく場所(名前で照合)。使用件数=削除時の警告に使う。
STAFF_USAGE = [("customers", "staff_name"), ("sales_slips", "staff_name"),
               ("approach_history", "staff_name"), ("prescriptions", "handler"),
               ("repairs", "staff_name")]


def _staff_usage_map(con):
    """担当者名→使用件数(5テーブル合算)。GROUP BYで一括集計して高速化。"""
    usage = {}
    for t, c in STAFF_USAGE:
        try:
            for r in con.execute(f"SELECT {c}, COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND {c}<>'' GROUP BY {c}"):
                usage[r[0]] = usage.get(r[0], 0) + r[1]
        except sqlite3.Error:
            pass
    return usage


def list_staff(con):
    """担当者マスタ一覧。code/name/active＋使用件数(顧客/売上/アプローチ/処方箋/修理の合算)。
    並び順はデフォルトで番号(staff_code)の昇順。"""
    sync_staff_from_names(con)
    umap = _staff_usage_map(con)
    con.row_factory = sqlite3.Row
    return [{"code": r["staff_code"], "name": r["name"], "active": bool(r["active"]),
             "register": bool(r["is_register"]), "count": umap.get(r["name"], 0)}
            for r in con.execute(
                "SELECT staff_code,name,active,COALESCE(is_register,0) is_register "
                "FROM staff ORDER BY CAST(staff_code AS INTEGER)")]


def save_staff(con, p):
    """担当者の 追加(code空)/更新(name・active)/削除(action=delete)。"""
    code = str(p.get("code") or "").strip()
    name = str(p.get("name") or "").strip()
    active = 1 if p.get("active", 1) else 0
    cur = con.cursor()
    if p.get("action") == "delete":
        if not code:
            raise ValueError("担当者が指定されていません")
        cur.execute("DELETE FROM staff WHERE staff_code=?", (code,))
        con.commit()
        return {"deleted": code}
    if p.get("action") == "cleanup":  # ゴミ担当(旧タグ)の一括整理
        return purge_junk_staff(con)
    # register(レジ会計担当としてワンタップバーに出すか)。payloadに含まれる時だけ更新
    has_reg = "register" in p
    register = 1 if p.get("register") else 0
    if not code:  # 新規
        if not name:
            raise ValueError("担当者名を入力してください")
        row = con.execute("SELECT MAX(CAST(staff_code AS INTEGER)) FROM staff WHERE staff_code GLOB '[0-9]*'").fetchone()
        code = str((row[0] or 0) + 1)
        reg_new = register if has_reg else 0  # 手動追加も既定はレジ表示OFF(必要な人だけON)
        cur.execute("INSERT INTO staff(staff_code,name,active,is_register) VALUES (?,?,?,?)",
                    (code, name, active, reg_new))
    else:  # 更新
        if name:
            cur.execute("UPDATE staff SET name=?, active=? WHERE staff_code=?", (name, active, code))
        else:
            cur.execute("UPDATE staff SET active=? WHERE staff_code=?", (active, code))
        if has_reg:
            cur.execute("UPDATE staff SET is_register=? WHERE staff_code=?", (register, code))
    con.commit()
    return {"code": code, "name": name, "active": bool(active)}


def list_junk_staff(con):
    """ゴミ担当(旧タグらしき担当者)を一覧。整理プレビュー用。使用件数と処理予定を付ける。"""
    umap = _staff_usage_map(con)
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT staff_code,name,active FROM staff ORDER BY name"):
        if _is_junk_staff_name(r["name"]):
            cnt = umap.get(r["name"], 0)
            out.append({"code": r["staff_code"], "name": r["name"], "count": cnt,
                        # 使用0件は削除、使用ありは停止(データ参照を壊さない)
                        "plan": "delete" if cnt == 0 else "deactivate"})
    return out


def purge_junk_staff(con):
    """ゴミ担当(旧タグ)を一括整理。使用0件は削除、使用ありは停止＋レジ非表示にする
    (実データの担当者名は残るので過去伝票の参照は壊れない)。件数を返す。"""
    junk = list_junk_staff(con)
    cur = con.cursor()
    deleted, deactivated = [], []
    for s in junk:
        if s["plan"] == "delete":
            cur.execute("DELETE FROM staff WHERE staff_code=?", (s["code"],))
            deleted.append(s["name"])
        else:
            cur.execute("UPDATE staff SET active=0, is_register=0 WHERE staff_code=?", (s["code"],))
            deactivated.append(s["name"])
    con.commit()
    return {"deleted": deleted, "deactivated": deactivated,
            "count": len(deleted) + len(deactivated)}


def sample_in_stock_key(con):
    """会計デモ用に、在庫状態の商品を1つ選んでその product_key を返す。"""
    row = con.execute("SELECT product_key FROM products WHERE state='在庫' AND name IS NOT NULL LIMIT 1").fetchone()
    return row[0] if row else None


CUSTOMER_FIELDS = ("name", "kana", "gender", "birthday", "wedding_day", "tel", "tel2",
                   "email", "postal", "address", "address2", "rank", "district", "dm_ok",
                   "staff_name", "ring_size", "pierce", "note", "exclude_stats")


def upsert_customer(con, payload):
    """顧客の新規登録/編集。customer_id が空なら採番して新規、あれば更新。"""
    cur = con.cursor()
    cid = str(payload.get("customer_id") or "").strip()
    vals = {k: (payload.get(k) or None) for k in CUSTOMER_FIELDS}
    vals["exclude_stats"] = 1 if payload.get("exclude_stats") else 0  # NULLでなく0/1で保持(集計除外の判定用)
    is_new = not cid
    if is_new:
        row = con.execute("SELECT MAX(CAST(customer_id AS INTEGER)) FROM customers").fetchone()
        cid = str((row[0] or 0) + 1)
        cols = ["customer_id"] + list(CUSTOMER_FIELDS) + ["store_code", "registered_at"]
        ph = ",".join("?" * len(cols))
        cur.execute(f"INSERT INTO customers({','.join(cols)}) VALUES ({ph})",
                    [cid] + [vals[k] for k in CUSTOMER_FIELDS] + ["01", None])
    else:
        setclause = ",".join(f"{k}=?" for k in CUSTOMER_FIELDS)
        cur.execute(f"UPDATE customers SET {setclause} WHERE customer_id=?",
                    [vals[k] for k in CUSTOMER_FIELDS] + [cid])
    con.commit()
    return {"customer_id": cid, "new": is_new}


# 顧客に紐づくテーブル(重複マージで付け替える対象)。列を増やしたらここも直すこと。
# ★漏らすと「マージしたのに履歴が消えた」事故になるため、schema.sql の customer_id 参照を
#   全て洗い出して列挙している(2026-08-01 時点で全12参照)。
CUSTOMER_LINKED_TABLES = ("sales_slips", "receivables", "receivable_entries",
                          "point_transactions", "approach_history", "prescriptions",
                          "repairs", "customer_memos", "customer_families")


def _digits(s):
    return re.sub(r"[^0-9]", "", str(s or ""))


def _last_purchase(con, cid):
    """最終購入日(customers に列が無いため売上から求める)。"""
    r = con.execute("""SELECT MAX(s.sold_at) FROM sales_slips s
                       WHERE s.customer_id=? AND COALESCE(s.voided,0)=0""", (cid,)).fetchone()
    return r[0] if r else None


def find_duplicate_customers(con, limit=200):
    """重複の疑いがある顧客を探す。判定は次の2通り(強い順)。

      tel  … 電話番号(数字だけにして比較)が一致。最も確実
      name … 氏名+カナ(記号・空白を除いて比較)が一致。同姓同名の別人もあるため要確認

    ★自動では統合しない。同じ電話番号のご家族など「重複でない」ケースがあるため、
      必ず画面で中身を見比べてから統合する運用にする。
    """
    con.row_factory = sqlite3.Row
    # 累計購入額・最終購入日は customers に列が無く売上から集計する設計のため、ここで算出する
    rows = con.execute("""SELECT c.customer_id, c.name, c.kana, c.tel, c.tel2, c.address, c.birthday,
                                 COALESCE(t.total,0) total_amount, t.last_at last_purchase_at
                          FROM customers c
                          LEFT JOIN (SELECT s.customer_id cid, SUM(l.amount) total, MAX(s.sold_at) last_at
                                     FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
                                     WHERE COALESCE(s.voided,0)=0 AND COALESCE(l.voided,0)=0
                                     GROUP BY s.customer_id) t ON t.cid = c.customer_id
                          WHERE COALESCE(c.is_test,0)=0""").fetchall()
    # 判定(2026-08-13 厳格化): 「電話だけ一致」は同居家族を、「氏名だけ一致」は同姓同名を
    # 大量に拾い、一覧が使い物にならなかった(実テストで数百組)。重複と呼べるのは
    #   nametel  … 氏名+電話番号の両方が一致(ダミー電話は _tel_key が除外)
    #   namebirth… 氏名+生年月日の両方が一致(電話が未登録の古い顧客向けの控え)
    by_tel, by_name = {}, {}   # 変数名は流用: by_tel=氏名+電話 / by_name=氏名+生年月日
    for r in rows:
        nk = normjp(str(r["name"] or ""))
        if not nk:
            continue
        for t in (r["tel"], r["tel2"]):
            tk = _tel_key(t)
            if tk:
                by_tel.setdefault(nk + "|" + tk, []).append(r)
        bd = str(r["birthday"] or "").strip()
        if bd:
            by_name.setdefault(nk + "|" + bd, []).append(r)

    def pack(r):
        return {"customer_id": r["customer_id"], "name": r["name"], "kana": r["kana"],
                "tel": r["tel"], "tel2": r["tel2"], "address": r["address"],
                "birthday": r["birthday"], "total": int(r["total_amount"] or 0),
                "last": r["last_purchase_at"]}

    groups, seen = [], set()
    for kind, table in (("nametel", by_tel), ("namebirth", by_name)):
        for key, members in table.items():
            if len(members) < 2:
                continue
            ids = tuple(sorted(m["customer_id"] for m in members))
            if ids in seen:
                continue
            seen.add(ids)
            groups.append({"kind": kind, "key": key,
                           "members": [pack(m) for m in members]})
    groups.sort(key=lambda g: (0 if g["kind"] == "nametel" else 1, -len(g["members"])))
    return {"groups": groups[:limit], "total": len(groups)}


def customer_merge_preview(con, keep_id, merge_id):
    """統合前の確認用データ。2件の顧客情報と「何がどれだけ移るか」を返す。
    ★実行はしない(画面で中身を見比べてもらうための材料)。"""
    keep_id, merge_id = str(keep_id or "").strip(), str(merge_id or "").strip()
    if not keep_id or not merge_id:
        raise ValueError("統合する顧客が指定されていません")
    if keep_id == merge_id:
        raise ValueError("同じ顧客は統合できません")
    con.row_factory = sqlite3.Row
    out = {"keep_id": keep_id, "merge_id": merge_id, "customers": {}, "moves": {}}
    for cid in (keep_id, merge_id):
        r = con.execute("SELECT * FROM customers WHERE customer_id=?", (cid,)).fetchone()
        if not r:
            raise ValueError(f"顧客({cid})が見つかりません")
        bal = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
        d = {k: r[k] for k in r.keys()}
        d["points"] = int(bal[0] or 0) if bal else 0
        # 累計購入額・最終購入日は売上から集計(customers には列が無い)
        t = con.execute("""SELECT COALESCE(SUM(l.amount),0), MAX(s.sold_at)
                           FROM sales_slips s JOIN sale_lines l ON l.slip_id = s.slip_id
                           WHERE s.customer_id=? AND COALESCE(s.voided,0)=0
                             AND COALESCE(l.voided,0)=0""", (cid,)).fetchone()
        d["total_amount"] = int(t[0] or 0)
        d["last_purchase_at"] = t[1]
        d["sales_count"] = con.execute(
            "SELECT COUNT(*) FROM sales_slips WHERE customer_id=? AND COALESCE(voided,0)=0", (cid,)).fetchone()[0]
        d["receivable_balance"] = con.execute(
            "SELECT COALESCE(SUM(balance),0) FROM receivables WHERE customer_id=?", (cid,)).fetchone()[0]
        d["repairs"] = con.execute("SELECT COUNT(*) FROM repairs WHERE customer_id=?", (cid,)).fetchone()[0]
        d["prescriptions"] = con.execute(
            "SELECT COUNT(*) FROM prescriptions WHERE customer_id=?", (cid,)).fetchone()[0]
        out["customers"][cid] = d
    # 移動する件数(統合される側)
    for t in CUSTOMER_LINKED_TABLES:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE customer_id=?", (merge_id,)).fetchone()[0]
        except sqlite3.Error:
            n = 0
        if n:
            out["moves"][t] = n
    out["moves_points"] = out["customers"][merge_id]["points"]
    return out


def merge_customers(con, keep_id, merge_id, operator=None):
    """重複顧客を統合する。merge_id の履歴を全て keep_id へ付け替え、merge_id を削除する。

    ★取り消せない操作なので、呼び出し側は必ず customer_merge_preview で
      中身を確認してから実行すること。
    ポイント残高は合算する(どちらのポイントも失わせない)。統合の記録は
    ポイント履歴と統合される側の顧客名を残した形で customer_memos に残す。
    """
    prev = customer_merge_preview(con, keep_id, merge_id)   # 存在チェックも兼ねる
    keep_id, merge_id = prev["keep_id"], prev["merge_id"]
    keep_name = prev["customers"][keep_id].get("name") or keep_id
    merge_name = prev["customers"][merge_id].get("name") or merge_id
    moved = {}
    with write_lock(con):
        for t in CUSTOMER_LINKED_TABLES:
            try:
                cur = con.execute(f"UPDATE {t} SET customer_id=? WHERE customer_id=?", (keep_id, merge_id))
                if cur.rowcount:
                    moved[t] = cur.rowcount
            except sqlite3.Error:
                pass
        # 家族リンクの相手側も付け替える(自分自身が家族になる行は消す)
        try:
            con.execute("UPDATE customer_families SET linked_customer_id=? WHERE linked_customer_id=?",
                        (keep_id, merge_id))
            con.execute("DELETE FROM customer_families WHERE customer_id=linked_customer_id")
        except sqlite3.Error:
            pass
        # ポイント残高は合算(統合される側の残高を足す)
        add = int(prev["customers"][merge_id]["points"] or 0)
        keep_bal = int(prev["customers"][keep_id]["points"] or 0)
        newbal = keep_bal + add
        today = datetime.date.today().isoformat()
        if add:
            con.execute("""INSERT INTO point_transactions
                             (customer_id,tx_type,points,add_points,balance,product_name,occurred_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (keep_id, "統合", add, add, newbal,
                         f"顧客統合: {merge_name}({merge_id})から移管", today))
        con.execute("""INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)
                       ON CONFLICT(customer_id) DO UPDATE SET balance=excluded.balance,
                         updated_at=excluded.updated_at""", (keep_id, newbal, today))
        con.execute("DELETE FROM point_balances WHERE customer_id=?", (merge_id,))
        # 統合の記録を残す(誰がいつ統合したか。元の顧客IDと氏名も残す)
        try:
            con.execute("""INSERT INTO customer_memos(customer_id, body, updated_at)
                           VALUES (?,?,?)""",
                        (keep_id,
                         f"[顧客統合 {today}] {merge_name}(ID {merge_id})を統合しました"
                         f"(操作: {operator or '不明'})。移動: "
                         + "・".join(f"{k} {v}件" for k, v in moved.items()) or "なし",
                         today))
        except sqlite3.Error:
            pass
        con.execute("DELETE FROM customers WHERE customer_id=?", (merge_id,))
    return {"ok": True, "keep_id": keep_id, "merge_id": merge_id,
            "keep_name": keep_name, "merge_name": merge_name,
            "moved": moved, "points_added": add, "point_balance": newbal}


def _tel_key(t):
    """電話番号を比較用に正規化する。9桁未満と「ダミー番号」は None(判定に使わない)。
    実データには 1111111111 / 1111-11-1111 のような穴埋めの番号が大量にあり、
    これを「同じ電話」と数えると無関係な顧客同士が重複扱いになる(2026-08-13 テストで発覚)。
    数字の種類が2種類以下の番号はダミーとみなす。"""
    d = _digits(t)
    if len(d) < 9 or len(set(d)) <= 2:
        return None
    return d


def check_customer_duplicate(con, tel=None, name=None, kana=None, exclude_id=None):
    """登録前の重複チェック(2026-08-13 判定を厳格化)。
    「電話だけ一致」は同居のご家族、「氏名だけ一致」は同姓同名の別人を大量に拾って
    警告が意味を失うため、**氏名と電話番号の両方が一致した時だけ**警告する。
    ★登録は止めない(それでも別人のケースはあり得るため)。"""
    con.row_factory = sqlite3.Row
    hits = []
    ex = str(exclude_id or "")
    nk = normjp(str(name or ""))
    tk = _tel_key(tel)
    if nk and tk:
        for r in con.execute("""SELECT customer_id, name, kana, tel, tel2, address
                                FROM customers WHERE COALESCE(is_test,0)=0"""):
            if r["customer_id"] == ex:
                continue
            if normjp(str(r["name"] or "")) == nk and tk in (_tel_key(r["tel"]), _tel_key(r["tel2"])):
                hits.append({"customer_id": r["customer_id"], "name": r["name"], "kana": r["kana"],
                             "tel": r["tel"], "address": r["address"],
                             "last": _last_purchase(con, r["customer_id"]),
                             "why": "氏名と電話番号が同じ"})
    return {"hits": hits[:10]}


def add_family(con, p):
    """家族を追加する。
    A(自由入力): {customer_id, name, relation, gender, birthday}
    B(登録済み顧客とリンク): {customer_id, linked_customer_id, relation} を渡すと、
      相手顧客の氏名等をコピーして双方向に登録(相手側にも本人を家族として追加)。
    """
    cid = str(p.get("customer_id") or "").strip()
    if not cid:
        raise ValueError("顧客が指定されていません")
    cur = con.cursor()
    new_id = None
    linked = str(p.get("linked_customer_id") or "").strip() or None
    if linked:
        # B: 相手顧客の情報を取得
        row = con.execute("SELECT name,gender,birthday FROM customers WHERE customer_id=?", (linked,)).fetchone()
        if not row:
            raise ValueError("リンク先の顧客が見つかりません")
        if linked == cid:
            raise ValueError("自分自身は家族に登録できません")
        # 既に同じリンクがあれば重複させない
        dup = con.execute("SELECT id FROM customer_families WHERE customer_id=? AND linked_customer_id=?",
                          (cid, linked)).fetchone()
        if dup:
            new_id = dup[0]
        else:
            cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                           VALUES (?,?,?,?,?,?)""",
                        (cid, row[0], p.get("relation"), row[1], row[2], linked))
            new_id = cur.lastrowid
        # 双方向: 相手側にも本人を家族として登録する。
        # ★続柄はNULLではなく「家族」を入れる(NULLだと相手側の表示が「ー」になり、
        #   未入力なのか壊れているのか分からない。正しい続柄は相手側で編集してもらう)。
        # dupの場合もここを通す: 片側だけ削除された後の登録し直しで、欠けた側を修復するため。
        me = con.execute("SELECT name,gender,birthday FROM customers WHERE customer_id=?", (cid,)).fetchone()
        rev = con.execute("SELECT id FROM customer_families WHERE customer_id=? AND linked_customer_id=?",
                          (linked, cid)).fetchone()
        if me and not rev:
            cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                           VALUES (?,?,?,?,?,?)""", (linked, me[0], "家族", me[1], me[2], cid))
            reverse_id = cur.lastrowid
        else:
            reverse_id = rev[0] if rev else None
    else:
        # A: 自由入力
        if not p.get("name"):
            raise ValueError("家族の氏名を入力してください")
        cur.execute("""INSERT INTO customer_families(customer_id,name,relation,gender,birthday,linked_customer_id)
                       VALUES (?,?,?,?,?,?)""",
                    (cid, p.get("name"), p.get("relation"), p.get("gender"), p.get("birthday"), None))
        new_id = cur.lastrowid
        reverse_id = None
    con.commit()
    # reverse_id: リンク登録で相手側にできた行のid(画面が相手側の表示を正しく更新するために返す)
    return {"customer_id": cid, "ok": True, "id": new_id, "reverse_id": reverse_id}


def update_family(con, p):
    """家族1件を修正する。リンク(B)行は続柄のみ変更(氏名等は相手顧客に追随)。自由入力(A)行は全項目。"""
    fid = p.get("id")
    if not fid:
        raise ValueError("対象の家族が指定されていません")
    row = con.execute("SELECT customer_id, linked_customer_id FROM customer_families WHERE id=?", (fid,)).fetchone()
    if not row:
        raise ValueError("対象の家族が見つかりません")
    relation = p.get("relation") or None
    if row[1]:  # リンク(B)
        con.execute("UPDATE customer_families SET relation=? WHERE id=?", (relation, fid))
    else:       # 自由入力(A)
        name = (p.get("name") or "").strip()
        if not name:
            raise ValueError("家族の氏名を入力してください")
        con.execute("UPDATE customer_families SET name=?, relation=?, gender=?, birthday=? WHERE id=?",
                    (name, relation, p.get("gender") or None, p.get("birthday") or None, fid))
    con.commit()
    return {"id": fid, "customer_id": row[0], "linked": row[1]}


def delete_family(con, family_id):
    """家族1件を削除する。リンク行(B方式)の場合は**相手側の対の行も一緒に削除**する。
    (2026-08-13 変更。片側だけ消すと「Aから消したのにB側にAが残る」という
     非対称な状態になり、テストで混乱を招いたため。家族関係は双方向で1つの事実)"""
    if not family_id:
        raise ValueError("対象の家族が指定されていません")
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT customer_id, linked_customer_id FROM customer_families WHERE id=?",
                      (family_id,)).fetchone()
    if not row:
        raise ValueError("対象の家族が見つかりません")
    con.execute("DELETE FROM customer_families WHERE id=?", (family_id,))
    reverse_deleted = None
    if row["linked_customer_id"]:
        rev = con.execute("""SELECT id FROM customer_families
                             WHERE customer_id=? AND linked_customer_id=?""",
                          (row["linked_customer_id"], row["customer_id"])).fetchone()
        if rev:
            con.execute("DELETE FROM customer_families WHERE id=?", (rev["id"],))
            reverse_deleted = rev["id"]
    con.commit()
    return {"deleted": family_id, "customer_id": row["customer_id"],
            "linked_customer_id": row["linked_customer_id"], "reverse_deleted": reverse_deleted}


PRODUCT_FIELDS = ("product_no", "name", "category", "brand", "metal", "supplier", "cost_price",
                  "list_price", "location", "center_stone", "center_carat",
                  "color", "clarity", "cut", "cert_no", "info", "fucho",
                  "maker_no", "tag_name", "ring_fingers", "ring_size")

# 符丁(下代を隠す店内符牒)。数字→カナ「エビスアキナイカミ」対応表。
_FUCHO_DIGITS = {"1": "ｴ", "2": "ﾋ", "3": "ｽ", "4": "ｱ", "5": "ｷ",
                 "6": "ﾅ", "7": "ｲ", "8": "ｶ", "9": "ﾐ", "0": "ｹ"}


def fucho_encode(cost_price, head=""):
    """下代(cost_price)の【上3桁】を『エビスアキナイカミ』で符牒化し、頭にメーカー符丁文字(head)を付ける。
    head は仕入先マスタに登録した符丁カナ(supplier_fucho_head で取得)。漢字名対策として
    仕入先名そのものではなく登録済みのカナを使う。
    同じ数字が連続したら 先頭1文字＋「ﾀ」1つ にまとめる(2連でも3連以上でも ﾀ は1つ)。
    例: head='ｳ'・下代30800(上3桁=308) → ｳｽｹｶ / 下代12200(上3桁=122) → ｳｴﾋﾀ。cost が無ければ ''。"""
    digits = "".join(ch for ch in str(cost_price or "") if ch.isdigit())[:3]  # 下代の上3桁のみ
    if not digits:
        return ""
    out = []
    i = 0
    while i < len(digits):
        d = digits[i]
        out.append(_FUCHO_DIGITS.get(d, ""))
        j = i + 1
        while j < len(digits) and digits[j] == d:
            j += 1
        if j - i >= 2:
            out.append("ﾀ")  # 連続はまとめて ﾀ 1つ
        i = j
    return str(head or "") + "".join(out)


def add_product(con, payload):
    """商品(仕入)の新規登録。product_no 空なら自動採番。state は '在庫'。"""
    cur = con.cursor()
    vals = {k: (payload.get(k) or None) for k in PRODUCT_FIELDS}
    name = (vals["name"] or "").strip()
    if not name:
        raise ValueError("商品名は必須です")
    row = con.execute("SELECT MAX(CAST(product_key AS INTEGER)) FROM products").fetchone()
    key = str((row[0] or 0) + 1)
    pno = str(vals["product_no"] or "").strip()
    if not pno:
        # 自動採番は店の5桁系列(22XXX)の続き。6桁以上(別系列)・9桁(過去メガネ)・
        # "*"等のプレースホルダ番号は基準から除外する(それらに引っ張られて桁が増えるのを防ぐ)。
        row = con.execute(
            "SELECT MAX(CAST(product_no AS INTEGER)) FROM products "
            "WHERE product_no GLOB '[0-9]*' AND LENGTH(product_no)<=5").fetchone()
        pno = str((row[0] or 0) + 1).zfill(5)
    vals["product_no"] = pno
    for k in ("cost_price", "list_price"):
        if vals[k] is not None:
            try:
                vals[k] = int(str(vals[k]).replace(",", ""))
            except ValueError:
                raise ValueError("価格は数字で入力してください")
    if not str(vals.get("fucho") or "").strip():  # 符丁が空なら下代＋仕入先から自動生成
        vals["fucho"] = fucho_encode(vals.get("cost_price"), supplier_fucho_head(con, vals.get("supplier"))) or None
    is_glasses = 1 if ("メガネ" in (vals["category"] or "") or "メガネ" in name) else 0
    cols = ["product_key"] + list(PRODUCT_FIELDS) + ["state", "is_glasses", "registered_at"]
    cur.execute(
        f"INSERT INTO products({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [key] + [vals[k] for k in PRODUCT_FIELDS]
        + ["在庫", is_glasses, payload.get("registered_at") or None])
    con.commit()
    stone = vals["center_stone"] or ""
    if stone and vals["center_carat"]:
        stone += f' {vals["center_carat"]}ct'
    return {"product_key": key, "product_no": pno,
            "row": [pno, name, vals["category"], vals["list_price"], "在庫",
                    vals["location"], stone or None]}


def add_consignment(con, payload):
    """受託品(催事等でメーカーの品をその場でレジに通すため)を1件作成する。
    Phase 1(A方式): メーカー(仕入先)と金額だけで即作成。原価は納品書が届くまで未確定(NULL)、
    state='受託'・is_consignment=1。会計するとほかの商品と同じく 売上 になる。品名は任意(既定 受託品)。
    後日、メーカーの納品書で原価・正式品番を入れて精算するのは Phase 2。"""
    cur = con.cursor()
    supplier = str(payload.get("supplier") or "").strip()
    if not supplier:
        raise ValueError("メーカー(仕入先)を選んでください")
    name = str(payload.get("name") or "").strip() or "受託品"
    try:
        amount = int(str(payload.get("amount") or 0).replace(",", ""))
    except ValueError:
        raise ValueError("金額は数字で入力してください")
    row = con.execute("SELECT MAX(CAST(product_key AS INTEGER)) FROM products").fetchone()
    key = str((row[0] or 0) + 1)
    pno = "受託" + key  # 内部キーは常にユニーク。見える番号も受託と分かる形にする
    is_glasses = 1 if GLASS_PAT.search(name) else 0
    cur.execute("""INSERT INTO products(product_key,product_no,name,supplier,list_price,state,
                                        is_consignment,is_glasses,registered_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (key, pno, name, supplier, amount, "受託", 1, is_glasses,
                 datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    return {"product_key": key, "product_no": pno, "name": name,
            "amount": amount, "supplier": supplier}


def consignment_list(con):
    """受託品(is_consignment=1)の一覧。後日精算(納品書で原価入力)用。
    未精算(原価未確定)を先頭に、メーカー別・新しい順。売れた日も付ける。"""
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("""
        SELECT p.product_key, p.name, p.supplier, p.list_price, p.cost_price,
               COALESCE(p.consign_settled,0) settled, p.state,
               (SELECT MAX(s.sold_at) FROM sale_lines l JOIN sales_slips s ON s.slip_id=l.slip_id
                WHERE l.product_key=p.product_key AND COALESCE(l.voided,0)=0) sold_at
        FROM products p
        WHERE COALESCE(p.is_consignment,0)=1
        ORDER BY settled ASC, p.supplier, CAST(p.product_key AS INTEGER) DESC"""):
        rows.append({"product_key": r["product_key"], "name": r["name"], "supplier": r["supplier"],
                     "list_price": r["list_price"], "cost_price": r["cost_price"],
                     "settled": r["settled"], "state": r["state"], "sold_at": r["sold_at"]})
    return {"rows": rows}


def settle_consignment(con, p):
    """受託品の後日精算: 原価(下代)を入れて確定。以降は粗利が正しく計算される。
    精算済みでも原価を入れ直せば更新できる(訂正用)。"""
    pk = str(p.get("product_key") or "").strip()
    if not pk:
        raise ValueError("対象が指定されていません")
    try:
        cost = int(str(p.get("cost") or 0).replace(",", ""))
    except ValueError:
        raise ValueError("原価は数字で入力してください")
    if cost < 0:
        raise ValueError("原価は0以上で入力してください")
    row = con.execute("SELECT COALESCE(is_consignment,0) FROM products WHERE product_key=?", (pk,)).fetchone()
    if not row or not row[0]:
        raise ValueError("対象の受託品が見つかりません")
    con.execute("UPDATE products SET cost_price=?, consign_settled=1 WHERE product_key=?", (cost, pk))
    con.commit()
    return consignment_list(con)


def get_product(con, product_key):
    """商品1件の全項目を返す(修正フォームの初期表示用)。search_products の一覧行より
    項目数が多い(カラー・クラリティ・カット・鑑定書No・備考も含む)。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    con.row_factory = sqlite3.Row
    r = con.execute(
        "SELECT product_key,product_no,name,category,brand,metal,supplier,cost_price,list_price,location,"
        "center_stone,center_carat,color,clarity,cut,cert_no,info,fucho,state,image_file,"
        "maker_no,tag_name,ring_fingers,ring_size "
        "FROM products WHERE product_key=?", (pk,)).fetchone()
    if not r:
        raise ValueError("商品が見つかりません")
    out = dict(r)
    out["buyers"] = product_buyers(con, pk)
    return out


# 保証書の用紙の分かれ目。10万円以上=A4、それ以外=A5(2026-08-06 店の運用で決定)
WARRANTY_A4_MIN = 100000


def warranty_data(con, line_id):
    """保証書に刷る値を1明細ぶん集める。

    台紙(A4/A5)に**値と写真だけを重ね刷り**するので、枠・題字・保証文言は返さない。
    用紙は買上金額で決まる: 10万円以上=A4 / それ以外=A5。
    """
    con.row_factory = sqlite3.Row
    r = con.execute("""SELECT s.sold_at, s.staff_name, l.amount, l.free_name,
                              c.customer_id, c.name cname,
                              p.product_no, p.name pname, p.cert_no,
                              p.center_stone, p.center_carat, p.image_file
                       FROM sale_lines l JOIN sales_slips s ON s.slip_id = l.slip_id
                       LEFT JOIN customers c ON c.customer_id = s.customer_id
                       LEFT JOIN products p ON p.product_key = l.product_key
                       WHERE l.line_id = ?
                             AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0""",
                    (line_id,)).fetchone()
    if not r:
        raise ValueError("保証書を作る明細が見つかりません(取消済みの可能性があります)")

    # 石の情報。★宝飾ナビの「脇石1・脇石2」はトキワに取り込んでいないため、
    #   中石だけになる(実物の保証書は「BO28.720ct D2.550ct」のように脇石も入る)。
    #   8月末の実データ再取込で脇石の列を足すまでは中石のみで刷る。
    stone = " ".join(x for x in [
        (r["center_stone"] or "").strip(),
        (f'{str(r["center_carat"]).strip()}ct' if str(r["center_carat"] or "").strip() else ""),
    ] if x)

    d = _parse_date(r["sold_at"])
    amount = r["amount"] or 0
    return {
        "date_text": f"{d.year} 年 {d.month} 月 {d.day} 日" if d else "",
        "product_no": r["product_no"] or "",
        "cert_no": r["cert_no"] or "",
        "customer_name": r["cname"] or "",
        "customer_id": str(r["customer_id"] or ""),
        "product_name": r["pname"] or r["free_name"] or "",
        "stone": stone,
        "staff_name": r["staff_name"] or "",
        "image_file": r["image_file"] or "",
        "amount": amount,
        "paper": "a4" if amount >= WARRANTY_A4_MIN else "a5",
    }


def product_buyers(con, product_key):
    """この商品を買った方を新しい順で返す(商品詳細から購入履歴へ飛ぶために使う)。

    同じ品が「売れて → 返品されて → また売れた」場合は複数件になるため一覧で返す。
    画面は先頭(最後の売上)を出し、2件以上あれば「他○件」と添える。
    取消済みの明細・伝票は数えない(売れていないことになるため)。
    """
    con.row_factory = sqlite3.Row
    rows = []
    for b in con.execute("""SELECT s.customer_id cid, c.name cname, s.sold_at, s.slip_id
                            FROM sale_lines l JOIN sales_slips s ON s.slip_id = l.slip_id
                            LEFT JOIN customers c ON c.customer_id = s.customer_id
                            WHERE l.product_key = ?
                                  AND COALESCE(l.voided,0)=0 AND COALESCE(s.voided,0)=0
                                  AND s.customer_id IS NOT NULL
                            ORDER BY s.sold_at DESC""", (str(product_key),)):
        rows.append({"customer_id": str(b["cid"]), "name": b["cname"],
                     "sold_at": b["sold_at"], "slip_id": b["slip_id"]})
    return rows


def update_product(con, payload):
    """商品情報の修正(B-7: 登録内容の確認・修正)。product_key必須。
    state(在庫/売上/受託/返品)と image_file はここでは変更しない
    (会計・返品・写真登録の各機能が管理しているため、競合を避けて触れない)。"""
    pk = str(payload.get("product_key") or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    vals = {k: (payload.get(k) or None) for k in PRODUCT_FIELDS}
    name = (vals["name"] or "").strip()
    if not name:
        raise ValueError("商品名は必須です")
    for k in ("cost_price", "list_price"):
        if vals[k] is not None:
            try:
                vals[k] = int(str(vals[k]).replace(",", ""))
            except ValueError:
                raise ValueError("価格は数字で入力してください")
    if not str(vals.get("fucho") or "").strip():  # 符丁が空なら下代＋仕入先から自動生成
        vals["fucho"] = fucho_encode(vals.get("cost_price"), supplier_fucho_head(con, vals.get("supplier"))) or None
    is_glasses = 1 if ("メガネ" in (vals["category"] or "") or "メガネ" in name) else 0
    sets = ",".join(f"{k}=?" for k in PRODUCT_FIELDS) + ",is_glasses=?"
    cur = con.execute(f"UPDATE products SET {sets} WHERE product_key=?",
                       [vals[k] for k in PRODUCT_FIELDS] + [is_glasses, pk])
    con.commit()
    if cur.rowcount == 0:
        raise ValueError("対象の商品が見つかりません")
    return get_product(con, pk)


def delete_product(con, product_key):
    """商品の削除(誤登録の訂正用)。販売履歴(sale_lines)に紐づく商品は削除しない
    (削除すると購入履歴の商品名解決ができなくなるため)。画像ファイル名を返すので、
    実ファイルの削除はapp.py側(ディスク操作)で行う。"""
    pk = str(product_key or "").strip()
    if not pk:
        raise ValueError("商品が指定されていません")
    used = con.execute("SELECT COUNT(*) FROM sale_lines WHERE product_key=? AND COALESCE(voided,0)=0", (pk,)).fetchone()[0]
    if used:
        raise ValueError(f"この商品は販売履歴({used}件)と紐づいているため削除できません。誤登録の場合は内容の修正をご利用ください。")
    row = con.execute("SELECT image_file FROM products WHERE product_key=?", (pk,)).fetchone()
    if not row:
        raise ValueError("対象の商品が見つかりません")
    image_file = row[0]
    con.execute("DELETE FROM products WHERE product_key=?", (pk,))
    con.commit()
    return {"deleted": pk, "image_file": image_file}


def update_sale_line(con, p):
    """購入明細(番号なし行=自由入力の売上)の品名・商品情報を直す。
    仕入れた在庫品ではない明細(product_key が無い行)は商品台帳が無く、これまで顧客詳細から
    何も直せなかったため。金額は売上集計・累計購入額に影響するのでここでは変更しない
    (返品・訂正=取消してから打ち直す運用にする)。"""
    try:
        line_id = int(p.get("line_id"))
    except (TypeError, ValueError):
        raise ValueError("明細が指定されていません")
    row = con.execute("SELECT product_key, COALESCE(voided,0) v FROM sale_lines WHERE line_id=?",
                      (line_id,)).fetchone()
    if not row:
        raise ValueError("明細が見つかりません")
    if row[1]:
        raise ValueError("取消済みの明細は編集できません")
    if row[0]:
        raise ValueError("在庫品の明細です。品名は商品台帳(商品の修正)から直してください")
    name = str(p.get("name") or "").strip()
    if not name:
        raise ValueError("品名を入力してください")
    info = str(p.get("info") or "").strip() or None
    con.execute("UPDATE sale_lines SET free_name=?, info=? WHERE line_id=?", (name, info, line_id))
    # この明細に処方箋が紐づいている場合は、処方箋側の品名も合わせる(表示のねじれを防ぐ)
    con.execute("UPDATE prescriptions SET lens_name=? "
                "WHERE sale_line_id=? AND COALESCE(lens_name,'')<>'' ", (name, line_id))
    con.commit()
    return {"line_id": line_id, "name": name, "info": info}


def add_prescription(con, p):
    """メガネ処方箋の新規登録/編集。id があれば更新、無ければ採番して新規。
    合計金額はレンズ金額+フレーム金額を優先(無ければ total_sell を使用)。"""
    cur = con.cursor()

    def v(k):
        x = p.get(k)
        x = str(x).strip() if x is not None else ""
        return x or None

    def n_int(k):
        try:
            return int(str(p.get(k)).replace(",", ""))
        except (TypeError, ValueError):
            return None

    lens_price, frame_price = n_int("lens_price"), n_int("frame_price")
    total = (lens_price or 0) + (frame_price or 0)
    if not total:
        total = n_int("total_sell")

    cols = ("purpose", "lens_name", "frame_name", "frame_type",
            "sph_r", "sph_l", "cyl_r", "cyl_l", "ax_r", "ax_l", "pri_r", "pri_l", "base_r", "base_l",
            "pri2_r", "pri2_l", "base2_r", "base2_l", "add_r", "add_l",
            "pd_far_both", "pd_far_r", "pd_far_l", "pd_near_both", "pd_near_r", "pd_near_l",
            "naked_both", "naked_r", "naked_l", "corrected_both", "corrected_r", "corrected_l",
            "handler", "rx_date")
    vals = [v(c) for c in cols]
    slid = n_int("sale_line_id")

    def _sync_sale_line_name():
        # 処方箋で品名(レンズ/フレーム)を直したら、紐づく購入明細(番号なし行)の表示名も
        # 合わせて更新する。これで購入一覧の品名も処方箋の修正が反映される。
        # 在庫品(product_key有り)の名前は商品側が正なので触らない(番号なし行のみ)。
        disp = v("lens_name") or v("frame_name")
        if slid and disp:
            cur.execute("UPDATE sale_lines SET free_name=? WHERE line_id=? AND product_key IS NULL",
                        (disp, slid))

    rx_id = n_int("id")
    if rx_id:  # 編集(既存を更新)
        setclause = ",".join(f"{c}=?" for c in cols) + ",lens_price=?,frame_price=?,total_sell=?,sale_line_id=?"
        cur.execute(f"UPDATE prescriptions SET {setclause} WHERE id=?",
                    vals + [lens_price, frame_price, total, slid, rx_id])
        _sync_sale_line_name()
        con.commit()
        row = con.execute("SELECT rx_no FROM prescriptions WHERE id=?", (rx_id,)).fetchone()
        return {"id": rx_id, "rx_no": row[0] if row else None, "total": total}

    n = con.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
    rx_no = f"RX-{n + 1:04d}"
    cur.execute(f"""INSERT INTO prescriptions
        (customer_id,rx_no,{",".join(cols)},lens_price,frame_price,total_sell,sale_line_id,jewelry_misassign)
        VALUES (?,?,{",".join("?" * len(cols))},?,?,?,?,0)""",
        [str(p.get("customer_id")), rx_no] + vals + [lens_price, frame_price, total, slid])
    _sync_sale_line_name()
    con.commit()
    return {"id": cur.lastrowid, "rx_no": rx_no, "total": total}


REPAIR_STATUSES = ["預かり中", "修理中", "連絡済み", "引渡済み"]


def add_repair(con, p):
    """修理伝票の新規登録(預かり)。伝票番号を採番して返す。"""
    cur = con.cursor()

    def n_int(k):
        try:
            return int(str(p.get(k)).replace(",", ""))
        except (TypeError, ValueError):
            return None

    n = con.execute("SELECT COUNT(*) FROM repairs").fetchone()[0]
    repair_no = f"R-{n + 1:06d}"
    cur.execute("""INSERT INTO repairs
        (repair_no,customer_id,item_name,issue,estimate,received_at,promised_at,status,staff_name,note)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (repair_no, str(p.get("customer_id")), p.get("item_name"), p.get("issue"),
         n_int("estimate"), p.get("received_at"), p.get("promised_at"), "預かり中",
         p.get("staff_name"), p.get("note")))
    con.commit()
    return {"id": cur.lastrowid, "repair_no": repair_no, "status": "預かり中"}


def add_repair_photos(con, repair_id, filenames):
    """修理伝票に写真ファイル名を追加する(既存に追記)。戻り値は更新後の全ファイル名リスト。"""
    if not repair_id:
        raise ValueError("修理伝票が指定されていません")
    row = con.execute("SELECT photo_files FROM repairs WHERE id=?", (repair_id,)).fetchone()
    if not row:
        raise ValueError("対象の修理伝票が見つかりません")
    cur = [x for x in (row[0] or "").split(",") if x]
    cur.extend([f for f in (filenames or []) if f])
    con.execute("UPDATE repairs SET photo_files=? WHERE id=?", (",".join(cur), repair_id))
    con.commit()
    return {"id": repair_id, "photos": cur}


def update_repair_status(con, p):
    """修理の進捗を更新(預かり中→修理中→連絡済み→引渡済み)。引渡済みの完了日はサーバー日時を正とする。"""
    repair_id = p.get("id")
    status = p.get("status")
    if status not in REPAIR_STATUSES:
        raise ValueError(f"不正な状態です: {status}")
    completed_at = datetime.date.today().isoformat() if status == "引渡済み" else None
    con.execute("UPDATE repairs SET status=?, completed_at=? WHERE id=?",
                (status, completed_at, repair_id))
    con.commit()
    return {"id": repair_id, "status": status, "completed_at": completed_at}


def add_receivable_payment(con, p):
    """売掛の入金を記録する(特定の売掛行の残高を減らし、入金履歴に1行追加)。"""
    receivable_id = p.get("receivable_id")
    amount = p.get("amount")
    if not receivable_id or not amount or int(amount) <= 0:
        raise ValueError("入金額を正しく入力してください")
    amount = int(amount)
    paid_at = p.get("paid_at") or datetime.date.today().isoformat()
    row = con.execute("SELECT customer_id, balance FROM receivables WHERE id=?", (receivable_id,)).fetchone()
    if not row:
        raise ValueError("対象の売掛が見つかりません")
    cid, balance = row[0], row[1] or 0
    new_balance = balance - amount
    method = (p.get("method") or "現金").strip() or "現金"  # 現金/銀行振込/カード/その他
    cur = con.cursor()
    cur.execute("UPDATE receivables SET balance=?, last_paid_at=? WHERE id=?", (new_balance, paid_at, receivable_id))
    cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid,note,method)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (cid, "入金", paid_at, None, None, amount, p.get("note"), method))
    con.commit()
    return {"receivable_id": receivable_id, "new_balance": new_balance, "paid_at": paid_at,
            "amount": amount, "method": method}


def receivable_summary(con):
    """売掛残高のある顧客ごとの合計(売掛管理の一覧用)。誰がいくら・件数・最古買上日・
    最終入金日を返し、総合計と対象顧客数も付ける。残高の多い順。"""
    con.row_factory = sqlite3.Row
    rows, total = [], 0
    for r in con.execute("""
        SELECT r.customer_id cid, c.name cname, c.staff_name staff, c.tel tel,
               COUNT(*) cnt, SUM(r.balance) bal, MAX(r.last_paid_at) last_paid, MIN(r.bought_at) oldest
        FROM receivables r LEFT JOIN customers c ON c.customer_id = r.customer_id
        WHERE COALESCE(r.balance,0) > 0
        GROUP BY r.customer_id
        HAVING SUM(r.balance) > 0
        ORDER BY bal DESC"""):
        bal = r["bal"] or 0
        total += bal
        rows.append({"customer_id": r["cid"], "name": r["cname"] or r["cid"], "staff": r["staff"],
                     "tel": r["tel"], "count": r["cnt"], "balance": bal,
                     "last_paid": r["last_paid"], "oldest": r["oldest"]})
    return {"rows": rows, "total": total, "count": len(rows)}


def add_receivable(con, p):
    """既存顧客に売掛(未回収残高)を手動で追加する。レジ会計を経由しない過去分の登録用。
    payload: {customer_id, product_name, amount, bought_at}"""
    cid = str(p.get("customer_id") or "").strip()
    if not cid:
        raise ValueError("顧客が指定されていません")
    try:
        amount = int(str(p.get("amount")).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("金額を数字で入力してください")
    if amount <= 0:
        raise ValueError("売掛金額を正しく入力してください")
    bought_at = p.get("bought_at") or datetime.date.today().isoformat()
    name = p.get("product_name") or None
    cur = con.cursor()
    cur.execute("""INSERT INTO receivables(customer_id,product_name,bought_at,down_payment,balance,last_paid_at)
                   VALUES (?,?,?,?,?,?)""", (cid, name, bought_at, 0, amount, None))
    rid = cur.lastrowid
    cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                   VALUES (?,?,?,?,?,?)""", (cid, "掛売", bought_at, name, amount, None))
    con.commit()
    return {"id": rid, "customer_id": cid, "product_name": name, "bought_at": bought_at,
            "down_payment": 0, "balance": amount, "last_paid_at": None}


def update_receivable(con, p):
    """売掛1件の修正(商品名・残高・買上日)。入力ミスの訂正用。"""
    rid = p.get("id")
    if not rid:
        raise ValueError("対象の売掛が指定されていません")
    row = con.execute("SELECT customer_id FROM receivables WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ValueError("対象の売掛が見つかりません")
    try:
        balance = int(str(p.get("amount")).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("金額を数字で入力してください")
    if balance < 0:
        raise ValueError("残高は0以上で入力してください")
    name = p.get("product_name") or None
    bought_at = p.get("bought_at") or None
    con.execute("UPDATE receivables SET product_name=?, balance=?, bought_at=? WHERE id=?",
                (name, balance, bought_at, rid))
    con.commit()
    return {"id": rid, "customer_id": row[0], "product_name": name, "bought_at": bought_at,
            "balance": balance}


def delete_receivable(con, rid):
    """売掛1件を削除(誤登録の訂正用)。売掛残高から消える。入金履歴の記録は残す。"""
    if not rid:
        raise ValueError("対象の売掛が指定されていません")
    row = con.execute("SELECT customer_id FROM receivables WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ValueError("対象の売掛が見つかりません")
    con.execute("DELETE FROM receivables WHERE id=?", (rid,))
    con.commit()
    return {"deleted": rid, "customer_id": row[0]}


def add_cash_movement(con, p):
    """レジ入出金(代引手数料・収入印紙・両替・経費等)を記録する。amountは +入金 / -出金。"""
    try:
        amount = int(str(p.get("amount")).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("金額を数字で入力してください")
    if amount == 0:
        raise ValueError("金額を入力してください(出金はマイナス)")
    occurred_at = p.get("occurred_at") or datetime.date.today().isoformat()
    cur = con.cursor()
    cur.execute("""INSERT INTO cash_movements(category,amount,note,staff_name,occurred_at)
                   VALUES (?,?,?,?,?)""",
                (p.get("category") or "その他", amount, p.get("note"), p.get("staff_name"), occurred_at))
    con.commit()
    return {"id": cur.lastrowid, "category": p.get("category") or "その他", "amount": amount,
            "note": p.get("note"), "staff_name": p.get("staff_name"), "occurred_at": occurred_at}


def list_cash_movements(con, limit=500):
    """レジ入出金の一覧(新しい順)。画面の日報・ホーム集計に使う。"""
    con.row_factory = sqlite3.Row
    try:
        limit = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        limit = 500
    return [{"id": r["id"], "category": r["category"], "amount": r["amount"], "note": r["note"],
             "staff_name": r["staff_name"], "occurred_at": r["occurred_at"]}
            for r in con.execute(
                "SELECT id,category,amount,note,staff_name,occurred_at FROM cash_movements "
                "ORDER BY occurred_at DESC, id DESC LIMIT ?", (limit,))]


def checkout(con, payload):
    """会計を実DBに書き込む。伝票+明細+支払内訳+在庫引落+ポイント加算を1トランザクションで。

    支払は複数方法に分けられる(例: 現金5万+クレジット5万)。payments=[{method,amount},...]
    を渡すと、その内訳ごとに sale_payments へ記録し、method="掛売" の内訳は自動的に
    売掛(receivables/receivable_entries)を起票する(店外イベント等の一部後払いに対応)。
    payments を渡さない場合は pay_method 1本(従来どおり)として扱う。

    sold_at を渡すと当日以外の日付(過去)で登録できる(店外イベントの後日精算など)。
    未来日は不可。created_at(登録日時)は別途サーバー時刻で自動記録されるため、
    実際の入力日は後から追跡できる。

    ★write_lock で排他する: 在庫の確認から伝票作成までを1つのトランザクションに入れないと、
      店内共有で2台が同じ1点ものを同時に会計した時に二重販売が成立してしまう。
    """
    with write_lock(con):
        return _checkout_locked(con, payload)


def _checkout_locked(con, payload):
    """checkout の本体(呼び出し元が write_lock を保持している前提。自分ではcommitしない)。"""
    cur = con.cursor()
    today = datetime.date.today().isoformat()
    sold_at = payload.get("sold_at") or today
    try:
        sd = datetime.date.fromisoformat(sold_at)
    except (ValueError, TypeError):
        raise ValueError("売上日の形式が正しくありません(YYYY-MM-DD)")
    if sd > datetime.date.today():
        raise ValueError("売上日は本日より後の日付にはできません")

    cid = str(payload.get("customer_id"))
    lines = payload.get("lines", [])
    # 二重販売の防止(在庫品は1点もの)。同一商品キーの重複 / すでに売却済みの品を弾く。
    line_keys = [l.get("product_key") for l in lines if l.get("product_key")]
    dupes = sorted({k for k in line_keys if line_keys.count(k) > 1})
    if dupes:
        raise ValueError("同じ在庫品が明細に重複しています(在庫1点の品は1会計で1回だけ販売できます)")
    for pk in dict.fromkeys(line_keys):
        prow = con.execute("SELECT state, name FROM products WHERE product_key=?", (pk,)).fetchone()
        if prow and prow[0] == "売上":
            raise ValueError(f"「{prow[1] or pk}」はすでに販売済みです(在庫にありません)。返品してから再販売してください")
    total = sum(int(l.get("amount") or 0) for l in lines)

    payments = payload.get("payments") or [{"method": payload.get("pay_method", "現金"), "amount": total}]
    pay_total = sum(int(p.get("amount") or 0) for p in payments)
    if pay_total != total:
        raise ValueError(f"支払方法の内訳合計(¥{pay_total:,})が請求金額(¥{total:,})と一致しません")
    methods = [p.get("method") for p in payments if p.get("method") and int(p.get("amount") or 0) > 0]
    pay_label = "+".join(dict.fromkeys(methods)) if methods else "現金"

    # ── ポイント計算(ルールは設定マスタ。既定 100円=1pt) ──
    ps = point_settings(con)
    rate = max(1, int(ps["point_rate_yen"]))
    try:  # レジで会計ごとに倍率を変えられる(2倍デー等)。0=付与なし
        mult = float(payload.get("point_mult", 1))
    except (ValueError, TypeError):
        mult = 1.0
    mult = max(0.0, min(mult, 100.0))
    earned = int(total * mult / rate)
    # ポイント支払い(1pt=1円)。残高を確認し、使用した会計は付与なし(設定で変更可)
    points_used = sum(int(p.get("amount") or 0) for p in payments
                      if p.get("method") == "ポイント")
    bal_row = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
    point_bal = int(bal_row[0] or 0) if bal_row else 0
    if points_used > point_bal:
        raise ValueError(f"ポイント残高が不足しています(残高 {point_bal:,} pt / 使用 {points_used:,} pt)")
    if points_used and ps["point_use_no_grant"]:
        earned = 0

    # レシートの一言(この会計だけ)。4行200文字まで・空行は捨てる(全体設定と同じ整形)
    note = "\n".join(ln.strip() for ln in str(payload.get("receipt_note") or "").splitlines()[:4]
                     if ln.strip())[:200]
    cur.execute("""INSERT INTO sales_slips(customer_id,staff_name,store_code,sold_at,pay_method,
                                           earned_points,used_points,receipt_note)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (cid, payload.get("staff_name"), "01", sold_at, pay_label, earned,
                 points_used or None, note or None))
    slip_id = cur.lastrowid

    lines_out = []
    for l in lines:
        pk = l.get("product_key")
        amt = int(l.get("amount") or 0)
        cur.execute("""INSERT INTO sale_lines(slip_id,product_key,free_name,amount,spec_pending)
                       VALUES (?,?,?,?,?)""",
                    (slip_id, pk, l.get("free_name"), amt, 1 if l.get("spec_pending") else 0))
        line_id = cur.lastrowid
        name = l.get("free_name")
        cat = None
        is_glass = bool(GLASS_PAT.search(name or ""))
        if pk:
            prow = con.execute("SELECT name,is_glasses,category FROM products WHERE product_key=?", (pk,)).fetchone()
            if prow:
                name, cat = prow[0], prow[2]
                is_glass = is_glass or prow[1] == 1
            cur.execute("UPDATE products SET state='売上' WHERE product_key=?", (pk,))
            cur.execute("""INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id)
                           VALUES (?,?,?,?)""", (pk, "売上引落", -1, slip_id))
        lines_out.append({"line_id": line_id, "name": name, "amount": amt,
                          "glasses": is_glass, "kind": glass_kind(cat, name)})

    item_names = [ln["name"] for ln in lines_out if ln["name"]]
    summary_name = "、".join(dict.fromkeys(item_names)) or None
    if summary_name and len(summary_name) > 60:
        summary_name = summary_name[:59] + "…"

    # 併用払いの内訳テキスト(2種類以上のときだけ)。売掛明細に「同時の支払」として出す
    _parts = [(p.get("method") or "現金", int(p.get("amount") or 0)) for p in payments]
    _parts = [(m, a) for m, a in _parts if a > 0]
    pay_text = " / ".join(f"{m} ¥{a:,}" for m, a in _parts) if len(_parts) > 1 else None

    receivables_out = []
    for p in payments:
        method = p.get("method") or "現金"
        amt = int(p.get("amount") or 0)
        if amt <= 0:
            continue
        cur.execute("INSERT INTO sale_payments(slip_id,method,amount) VALUES (?,?,?)", (slip_id, method, amt))
        if method == "掛売":
            # slip_id を持たせて、売掛明細から「同じ会計で現金/クレジットをいくら受け取ったか」を
            # 後から辿れるようにする(併用払いの内訳表示用)。
            cur.execute("""INSERT INTO receivables(customer_id,product_name,bought_at,down_payment,balance,last_paid_at,slip_id)
                           VALUES (?,?,?,?,?,?,?)""", (cid, summary_name, sold_at, 0, amt, None, slip_id))
            rid = cur.lastrowid  # 画面側でD.urikakeを即時更新できるよう新しい売掛行を返す
            cur.execute("""INSERT INTO receivable_entries(customer_id,entry_type,entry_date,product_name,amount,paid)
                           VALUES (?,?,?,?,?,?)""", (cid, "掛売", sold_at, summary_name, amt, None))
            receivables_out.append({"id": rid, "product_name": summary_name, "bought_at": sold_at,
                                    "down_payment": 0, "balance": amt, "last_paid_at": None,
                                    "pay_text": pay_text})

    # ポイントの使用→加算の順に記録し、残高は最後に1回で更新する
    newbal = point_bal
    if points_used:
        newbal -= points_used
        cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,use_points,balance,ref_slip_id,occurred_at)
                       VALUES (?,?,?,?,?,?,?)""", (cid, "使用", points_used, points_used, newbal, slip_id, sold_at))
    if earned:
        newbal += earned
        cur.execute("""INSERT INTO point_transactions(customer_id,tx_type,points,add_points,balance,ref_slip_id,occurred_at)
                       VALUES (?,?,?,?,?,?,?)""", (cid, "加算", earned, earned, newbal, slip_id, sold_at))
    if points_used or earned:
        cur.execute("""INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)
                       ON CONFLICT(customer_id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
                    (cid, newbal, sold_at))

    # commit は write_lock が行う(ここで commit するとロックが切れて排他が壊れる)
    return {"slip_id": slip_id, "earned": earned, "total": total, "lines": lines_out,
            "sold_at": sold_at, "pay_method": pay_label, "receivables": receivables_out,
            "points_used": points_used, "point_balance": newbal}


def receipt_data(con, slip_id, deposit=None):
    """レシート印字用のデータを伝票から組み立てる(会計直後の印字・後からの再印字の両対応)。
    devices.build_receipt_bytes() に渡す dict を返す。"""
    con.row_factory = sqlite3.Row
    s = con.execute("""SELECT s.slip_id, s.sold_at, s.staff_name, s.customer_id,
                              s.earned_points, s.used_points, s.receipt_note, c.name cname
                       FROM sales_slips s LEFT JOIN customers c ON c.customer_id = s.customer_id
                       WHERE s.slip_id=?""", (int(slip_id),)).fetchone()
    if not s:
        raise ValueError("伝票が見つかりません")
    # (品名, 売価, 定価)。定価があり売価が下回る明細は、レシートに定価と割引率を印字する
    lines = [(r["nm"], int(r["amount"] or 0), int(r["lp"]) if r["lp"] else None)
             for r in con.execute(
        """SELECT COALESCE(l.free_name, p.name) nm, l.amount, p.list_price lp
           FROM sale_lines l
           LEFT JOIN products p ON p.product_key = l.product_key
           WHERE l.slip_id=? AND COALESCE(l.voided,0)=0 ORDER BY l.line_id""", (s["slip_id"],))]
    payments = [(r["method"] or "現金", int(r["amount"] or 0)) for r in con.execute(
        "SELECT method, amount FROM sale_payments WHERE slip_id=? ORDER BY id", (s["slip_id"],))]
    total = sum(a for _, a, _lp in lines)
    bal_row = con.execute("SELECT balance FROM point_balances WHERE customer_id=?",
                          (str(s["customer_id"]),)).fetchone()
    cash_due = sum(a for m, a in payments if m == "現金")
    try:
        deposit = int(deposit) if deposit else None
    except (ValueError, TypeError):
        deposit = None
    if deposit is not None and deposit < cash_due:
        deposit = None  # 不正な預り額は印字しない
    return {"slip_id": s["slip_id"], "sold_at": s["sold_at"], "staff": shorten_staff(s["staff_name"]),
            "customer": s["cname"], "lines": lines, "payments": payments, "total": total,
            "earned": int(s["earned_points"] or 0), "points_used": int(s["used_points"] or 0),
            "point_balance": int(bal_row[0] or 0) if bal_row else 0,
            "deposit": deposit, "cash_due": cash_due,
            "note": s["receipt_note"] or "",                          # この会計だけの一言
            "thanks": point_settings(con).get("receipt_thanks", ""),  # 感謝の一文(設定で変更可)
            "message": point_settings(con).get("receipt_message", "")}  # 全レシート共通


# 印紙税: 「金銭の受領」に当たる支払方法だけが課税対象。クレジット・分割(信販)・PayPay等の
# 電子マネー・掛売(その場で受領なし)・ポイントは信用取引/非受領のため対象外。
# 対象額が5万円以上のとき収入印紙が必要(記載金額5万円未満は非課税)。
STAMP_CASH_METHODS = ("現金", "銀行振込", "振込")
STAMP_THRESHOLD = 50000


def receipt_doc_data(con, slip_id, to_name=None, note=None, reissue=False):
    """領収書用のデータを伝票から組み立てる(レシートプリンタ版・A4版で共用)。

    印紙の要否を支払方法から自動判定する(貼り忘れ・貼りすぎを防ぐ)。
    宛名は未指定なら顧客名、顧客が無ければ「上様」。但し書きは未指定なら「お品代として」。
    """
    con.row_factory = sqlite3.Row
    s = con.execute("""SELECT s.slip_id, s.sold_at, s.customer_id, s.voided, c.name cname
                       FROM sales_slips s LEFT JOIN customers c ON c.customer_id = s.customer_id
                       WHERE s.slip_id=?""", (int(slip_id),)).fetchone()
    if not s:
        raise ValueError("伝票が見つかりません")
    if s["voided"]:
        raise ValueError("取消済みの伝票の領収書は発行できません")
    total = con.execute("""SELECT COALESCE(SUM(amount),0) FROM sale_lines
                           WHERE slip_id=? AND COALESCE(voided,0)=0""", (s["slip_id"],)).fetchone()[0]
    total = int(total or 0)
    if total <= 0:
        raise ValueError("金額が0円のため領収書を発行できません")
    payments = [(r["method"] or "現金", int(r["amount"] or 0)) for r in con.execute(
        "SELECT method, amount FROM sale_payments WHERE slip_id=? ORDER BY id", (s["slip_id"],))]
    # 印紙の判定: 現金・振込の合計だけを対象額とする
    cash_amount = sum(a for m, a in payments if m in STAMP_CASH_METHODS)
    credit_methods = [m for m, a in payments if m not in STAMP_CASH_METHODS and a > 0]
    stamp_required = cash_amount >= STAMP_THRESHOLD
    tax = total * 10 // 110

    name = str(to_name or "").strip() or (s["cname"] or "").strip() or "上様"
    return {"slip_id": s["slip_id"], "issued_at": datetime.date.today().isoformat(),
            "sold_at": s["sold_at"], "to_name": name,
            "note": str(note or "").strip() or "お品代として",
            "total": total, "tax": tax, "payments": payments,
            "cash_amount": cash_amount, "stamp_required": stamp_required,
            "credit_methods": credit_methods, "reissue": bool(reissue)}


def void_receipt_data(con, line_id=None, slip_id=None):
    """返品レシート用のデータ(取消済みの明細/伝票から組み立てる)。

    返品は現金が出ていく取引なので、お客様控と店控(受領サイン用)を出せるようにする。
    元の支払方法も返す: 現金で受け取った分があればドロワーを開ける判断に使う
    (クレジットの返金はカード会社経由のため現金は動かない)。
    """
    con.row_factory = sqlite3.Row
    if line_id is not None:
        rows = con.execute("""SELECT l.line_id, l.slip_id, l.amount,
                                     COALESCE(l.free_name, p.name) nm,
                                     l.voided_at, l.voided_staff, l.voided_reason, l.voided_by
                              FROM sale_lines l LEFT JOIN products p ON p.product_key = l.product_key
                              WHERE l.line_id=? AND COALESCE(l.voided,0)=1""", (int(line_id),)).fetchall()
        if not rows:
            raise ValueError("取消済みの明細が見つかりません")
        slip_id = rows[0]["slip_id"]
        kind = "明細取消"
    else:
        rows = con.execute("""SELECT l.line_id, l.slip_id, l.amount,
                                     COALESCE(l.free_name, p.name) nm,
                                     l.voided_at, l.voided_staff, l.voided_reason, l.voided_by
                              FROM sale_lines l LEFT JOIN products p ON p.product_key = l.product_key
                              WHERE l.slip_id=? AND COALESCE(l.voided,0)=1
                              ORDER BY l.line_id""", (int(slip_id),)).fetchall()
        if not rows:
            raise ValueError("取消済みの明細が見つかりません")
        kind = "伝票取消(返品)"

    s = con.execute("""SELECT s.slip_id, s.sold_at, s.staff_name, s.customer_id, c.name cname
                       FROM sales_slips s LEFT JOIN customers c ON c.customer_id = s.customer_id
                       WHERE s.slip_id=?""", (int(slip_id),)).fetchone()
    payments = [(r["method"] or "現金", int(r["amount"] or 0)) for r in con.execute(
        "SELECT method, amount FROM sale_payments WHERE slip_id=? ORDER BY id", (int(slip_id),))]
    total = sum(int(r["amount"] or 0) for r in rows)
    first = rows[0]
    # この取消で動いたポイント(返品調整)と現在の残高。レシートに出して行き違いを防ぐ
    pt = con.execute("""SELECT COALESCE(add_points,0), COALESCE(use_points,0), balance
                        FROM point_transactions
                        WHERE ref_slip_id=? AND tx_type='返品調整'
                        ORDER BY id DESC LIMIT 1""", (int(slip_id),)).fetchone()
    point_delta = (int(pt[0] or 0) - int(pt[1] or 0)) if pt else 0
    point_balance = int(pt[2] or 0) if pt else None
    if point_balance is None and s and s["customer_id"]:
        bal = con.execute("SELECT balance FROM point_balances WHERE customer_id=?",
                          (str(s["customer_id"]),)).fetchone()
        point_balance = int(bal[0] or 0) if bal else None
    return {"kind": kind, "slip_id": int(slip_id), "sold_at": s["sold_at"] if s else "",
            "customer": (s["cname"] if s else "") or "", "staff": shorten_staff(s["staff_name"] if s else ""),
            "lines": [(r["nm"] or "お品物", int(r["amount"] or 0)) for r in rows],
            "total": total, "tax": total * 10 // 110, "payments": payments,
            "cash_refund": any(m == "現金" and a > 0 for m, a in payments),
            "point_delta": point_delta, "point_balance": point_balance,
            "voided_at": first["voided_at"] or "", "voided_staff": first["voided_staff"] or "",
            "voided_reason": first["voided_reason"] or "", "voided_by": first["voided_by"] or ""}


def card_face_data(con, customer_id):
    """カード券面リライト印字用のデータ(devices.card_face_print に渡す dict)。
    名前・有効期限(最終購入日+N年)・ポイント残高・券面メッセージ。会計直後に呼ぶ想定
    (checkoutがコミット済みなので、残高・最終購入日は今回の会計を含む)。"""
    cid = str(customer_id or "").strip()
    row = con.execute("SELECT name FROM customers WHERE customer_id=?", (cid,)).fetchone()
    if not row:
        raise ValueError(f"顧客({cid})が見つかりません")
    ps = point_settings(con)
    bal = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
    last = con.execute("""SELECT MAX(sold_at) FROM sales_slips
                          WHERE customer_id=? AND COALESCE(voided,0)=0""", (cid,)).fetchone()
    base = str(last[0])[:10] if last and last[0] else datetime.date.today().isoformat()
    try:
        d = datetime.date.fromisoformat(base)
    except ValueError:
        d = datetime.date.today()
    years = max(1, int(ps.get("card_expiry_years") or 5))
    try:
        exp = d.replace(year=d.year + years)
    except ValueError:      # 2/29 起点で加算先が閏年でない場合
        exp = d.replace(year=d.year + years, day=28)
    return {"name": row[0] or "", "issued": None, "expiry": exp.strftime("%Y.%m.%d"),
            "points": int(bal[0] or 0) if bal else 0,
            "message": ps.get("card_message") or ""}


def shorten_staff(name):
    """担当者名を姓だけに(レシートの幅節約)。"""
    return str(name or "").split()[0] if name else ""


def _restock_line(con, line_id):
    """取消する明細に在庫品が紐づいていれば在庫に戻す(売上→在庫)。返品の在庫戻し。"""
    row = con.execute("SELECT product_key, slip_id FROM sale_lines WHERE line_id=?", (line_id,)).fetchone()
    if not row:
        return
    pk = row[0]
    if pk:
        con.execute("UPDATE products SET state='在庫' WHERE product_key=? AND state='売上'", (pk,))
        con.execute("""INSERT INTO stock_events(product_key,event_type,qty_delta,ref_slip_id)
                       VALUES (?,?,?,?)""", (pk, "返品", 1, row[1]))


def _reverse_points_for_void(con, slip_id, voided_amount, reason):
    """取消に伴うポイントの戻し。取り消した金額の割合で按分する。

      付与ポイント … 取り消す(マイナス。返した商品の分は付けない)
      使用ポイント … 戻す(プラス。お客様が払ったポイントを返す)

    一部だけ取り消した場合も金額按分で同じ考え方になる(全額取消なら100%戻る)。
    ★残高は0未満にしない: 付与分を既に使い切っている場合にマイナス残高が出ると、
      以後の「残高不足」判定が分かりにくくなるため。実際に適用した値を履歴に残す。
    戻り値: {earned_reversed, used_restored, delta, balance} / 対象なしなら None
    """
    s = con.execute("""SELECT customer_id, COALESCE(earned_points,0), COALESCE(used_points,0)
                       FROM sales_slips WHERE slip_id=?""", (int(slip_id),)).fetchone()
    if not s:
        return None
    cid, earned, used = str(s[0] or ""), int(s[1] or 0), int(s[2] or 0)
    if not cid or (earned == 0 and used == 0):
        return None
    # 元の会計金額(明細は会計時にしか作られないため、取消済みも含めた合計が元の金額)
    orig = con.execute("SELECT COALESCE(SUM(amount),0) FROM sale_lines WHERE slip_id=?",
                       (int(slip_id),)).fetchone()[0]
    orig = int(orig or 0)
    if orig <= 0:
        return None
    ratio = min(1.0, max(0.0, int(voided_amount or 0) / orig))
    earned_rev = int(round(earned * ratio))     # 取り消す付与pt
    used_res = int(round(used * ratio))         # 戻す使用pt
    if earned_rev == 0 and used_res == 0:
        return None

    bal_row = con.execute("SELECT balance FROM point_balances WHERE customer_id=?", (cid,)).fetchone()
    bal = int(bal_row[0] or 0) if bal_row else 0
    delta = used_res - earned_rev
    newbal = max(0, bal + delta)                # 0未満にしない
    applied = newbal - bal                      # 実際に動いた分(履歴と残高を食い違わせない)
    today = datetime.date.today().isoformat()
    con.execute("""INSERT INTO point_transactions
                     (customer_id,tx_type,points,add_points,use_points,balance,product_name,
                      ref_slip_id,occurred_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (cid, "返品調整", abs(applied),
                 applied if applied > 0 else None, -applied if applied < 0 else None,
                 newbal, f"返品調整: {reason}"[:100], int(slip_id), today))
    con.execute("""INSERT INTO point_balances(customer_id,balance,updated_at) VALUES (?,?,?)
                   ON CONFLICT(customer_id) DO UPDATE SET balance=excluded.balance,
                     updated_at=excluded.updated_at""", (cid, newbal, today))
    return {"earned_reversed": earned_rev, "used_restored": used_res,
            "delta": applied, "balance": newbal, "clamped": (bal + delta) < 0}


# 返金方法の選択肢。取消時に選ぶ(基本は「現金は現金・カードはカード・ポイントはポイント」
# だが、カードの返金期限切れ等で現金返金になるケースがあるため固定にしない。2026-08-06)。
REFUND_METHODS = ("現金", "クレジット", "銀行振込", "ポイント", "その他")


def _void_record(operator, staff, reason, refund_method=None):
    """取消の記録を検証して返す。担当者と理由は必須(監査で後から追えるようにするため)。
    返金方法は未指定なら現金(現金締めに関わるため、画面では必ず選ばせる)。"""
    staff = str(staff or "").strip()
    reason = str(reason or "").strip()[:200]
    rm = str(refund_method or "現金").strip()
    if not staff:
        raise ValueError("取消した担当者を選んでください")
    if not reason:
        raise ValueError("取消の理由を入力してください")
    if rm not in REFUND_METHODS:
        raise ValueError("返金方法の指定が正しくありません")
    return (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(operator or ""), staff, reason, rm)


def void_sale_line(con, line_id, operator=None, staff=None, reason=None, refund_method=None):
    """明細1行を取消(訂正/一部返品)。集計・履歴から除外し、在庫品なら在庫に戻す。
    最終正データのみ表示する方針のため、取消済み行は各画面に出さない。

    記録する3点(電子帳簿保存法の訂正削除履歴・店舗の内部統制):
      operator … ログインユーザー(サーバーが認証情報から入れる。詐称できない)
      staff    … 取消操作をした担当者(レジと同じワンタップ選択。実務の記録)※必須
      reason   … 取消理由 ※必須
    """
    line_id = int(line_id)
    now, op, stf, rsn, rm = _void_record(operator, staff, reason, refund_method)  # 先に検証
    with write_lock(con):   # 二重取消・在庫戻しとポイント調整の競合を防ぐ
        row = con.execute("SELECT voided FROM sale_lines WHERE line_id=?", (line_id,)).fetchone()
        if not row:
            raise ValueError("対象の明細が見つかりません")
        if row[0]:
            return {"line_id": line_id, "already": True}
        lr = con.execute("SELECT slip_id, COALESCE(amount,0) FROM sale_lines WHERE line_id=?",
                         (line_id,)).fetchone()
        _restock_line(con, line_id)
        con.execute("""UPDATE sale_lines SET voided=1, voided_at=?, voided_by=?, voided_staff=?,
                              voided_reason=?, refund_method=? WHERE line_id=?""",
                    (now, op, stf, rsn, rm, line_id))
        # 付与ptを取り消し、使用ptを戻す(取り消した金額の割合で按分)
        pts = _reverse_points_for_void(con, lr[0], lr[1], rsn) if lr else None
    return {"line_id": line_id, "voided": True, "voided_at": now, "refund_method": rm,
            "voided_by": op, "voided_staff": stf, "voided_reason": rsn, "points": pts}


def void_sale_slip(con, slip_id, operator=None, staff=None, reason=None, refund_method=None):
    """伝票ごと取消(返品)。伝票の全明細を無効化し、在庫品は在庫に戻す。
    記録内容は void_sale_line と同じ(明細・伝票の両方に残す)。
    ※集計の扱いは日報のルールに従う: 当日中の取消=訂正として消える /
      日をまたいだ取消=売った日はそのまま・取消日にマイナス計上。"""
    slip_id = int(slip_id)
    now, op, stf, rsn, rm = _void_record(operator, staff, reason, refund_method)  # 先に検証
    with write_lock(con):
        row = con.execute("SELECT voided FROM sales_slips WHERE slip_id=?", (slip_id,)).fetchone()
        if not row:
            raise ValueError("対象の伝票が見つかりません")
        # まだ取り消していない明細だけが今回の対象(既に取消済みの分はポイントも戻し済み)
        live = con.execute("""SELECT line_id, COALESCE(amount,0) FROM sale_lines
                              WHERE slip_id=? AND COALESCE(voided,0)=0""", (slip_id,)).fetchall()
        for lr in live:
            _restock_line(con, lr[0])
        con.execute("""UPDATE sale_lines SET voided=1, voided_at=?, voided_by=?, voided_staff=?,
                              voided_reason=?, refund_method=? WHERE slip_id=? AND COALESCE(voided,0)=0""",
                    (now, op, stf, rsn, rm, slip_id))
        con.execute("""UPDATE sales_slips SET voided=1, voided_at=?, voided_by=?, voided_staff=?,
                              voided_reason=?, refund_method=? WHERE slip_id=?""",
                    (now, op, stf, rsn, rm, slip_id))
        pts = _reverse_points_for_void(con, slip_id, sum(int(r[1] or 0) for r in live), rsn)
    return {"slip_id": slip_id, "voided": True, "voided_at": now, "refund_method": rm,
            "voided_by": op, "voided_staff": stf, "voided_reason": rsn, "points": pts}


# ── ログイン認証・ロール制御(アクセス制御④。docs/access-control.md) ──
ROLE_LABELS = {"admin": "管理者", "staff": "社員", "part": "パート"}

# ログインの有効時間(ログインしてからの経過時間)。2026-08-01 に60日→12時間へ短縮。
# 理由: 店頭PCが常時ログインのままだと、権限(管理者/社員/パート)を分けても他人の
# ログインをそのまま使えてしまい、取消の操作者記録も全部同じ人になってしまうため。
# 開店から閉店までは持ち、翌日は必ずログインし直す長さとして12時間にしている。
SESSION_HOURS = 12


def _hash_pw(password, salt=None):
    """パスワードをPBKDF2でハッシュ化して 'salt$hash' 形式で返す(標準ライブラリのみ)。"""
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return salt + "$" + h


def _check_pw(password, stored):
    """保存済みハッシュとパスワードを照合する。"""
    try:
        salt, h = (stored or "").split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return secrets.compare_digest(calc, h)


def list_login_users(con):
    """ログイン画面のユーザー選択用(有効ユーザーのみ・ハッシュは返さない)。"""
    con.row_factory = sqlite3.Row
    return [{"id": r["user_id"], "name": r["display_name"] or r["user_id"],
             "has_pw": bool(r["pass_hash"])}
            for r in con.execute("""SELECT user_id, display_name, pass_hash FROM app_users
                                    WHERE active=1 ORDER BY role='admin' DESC, user_id""")]


def login_user(con, user_id, password):
    """ログイン。パスワード未設定(初回)なら入力されたものを設定して通す。
    成功時 {token, user:{id,name,role}, first_time} / 失敗は ValueError。"""
    row = con.execute("""SELECT user_id, display_name, role, pass_hash, active
                         FROM app_users WHERE user_id=?""", (str(user_id or ""),)).fetchone()
    if not row or not row[4]:
        raise ValueError("ユーザーが見つかりません")
    first = not row[3]
    if first:
        if len(password or "") < 4:
            raise ValueError("初回ログインです。パスワードを4文字以上で決めて入力してください")
        con.execute("UPDATE app_users SET pass_hash=? WHERE user_id=?", (_hash_pw(password), row[0]))
    elif not _check_pw(password, row[3]):
        raise ValueError("パスワードが違います")
    token = secrets.token_hex(32)
    con.execute("INSERT INTO app_sessions(token, user_id, created_at) VALUES (?,?,datetime('now','localtime'))",
                (token, row[0]))
    # 期限切れセッションの掃除(SESSION_HOURS でログインし直し)
    con.execute(f"DELETE FROM app_sessions WHERE created_at < datetime('now','-{SESSION_HOURS} hours','localtime')")
    con.commit()
    return {"token": token, "first_time": first,
            "user": {"id": row[0], "name": row[1] or row[0], "role": row[2] or "staff"}}


def session_user(con, token):
    """セッショントークンからログインユーザーを引く。無効・期限切れならNone。"""
    if not token:
        return None
    row = con.execute(f"""SELECT u.user_id, u.display_name, u.role,
                                 datetime(s.created_at, '+{SESSION_HOURS} hours') expires_at
                          FROM app_sessions s JOIN app_users u ON u.user_id = s.user_id
                          WHERE s.token=? AND u.active=1
                            AND s.created_at >= datetime('now','-{SESSION_HOURS} hours','localtime')""",
                      (token,)).fetchone()
    if not row:
        return None
    # expires_at は画面が「まもなく期限切れ」を予告するために使う(会計中の強制ログアウト防止)
    return {"id": row[0], "name": row[1] or row[0], "role": row[2] or "staff",
            "expires_at": row[3]}


def logout_user(con, token):
    """セッションを破棄する。"""
    if token:
        con.execute("DELETE FROM app_sessions WHERE token=?", (token,))
        con.commit()
    return {"ok": True}


def list_app_users(con):
    """ユーザー管理画面用の一覧(管理者のみ)。ハッシュ本体は返さない。"""
    con.row_factory = sqlite3.Row
    return [{"id": r["user_id"], "name": r["display_name"] or r["user_id"],
             "role": r["role"] or "staff", "active": bool(r["active"]),
             "has_pw": bool(r["pass_hash"])}
            for r in con.execute("""SELECT user_id, display_name, role, pass_hash, active
                                    FROM app_users ORDER BY role='admin' DESC, user_id""")]


def save_app_user(con, p):
    """ユーザーの追加・更新(管理者のみ)。reset_password=Trueでパスワードを未設定に戻す
    (次回そのユーザーがログインする時に新しいパスワードを設定する)。"""
    uid = str(p.get("id") or "").strip()
    if not uid or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", uid):
        raise ValueError("ログインIDは半角英数字(1〜20文字)で入力してください")
    role = str(p.get("role") or "staff")
    if role not in ROLE_LABELS:
        raise ValueError("役割は 管理者/社員/パート から選んでください")
    name = str(p.get("name") or "").strip() or uid
    active = 1 if p.get("active", True) else 0
    exists = con.execute("SELECT 1 FROM app_users WHERE user_id=?", (uid,)).fetchone()
    # 安全装置: 最後の有効な管理者を降格・無効化してロックアウトしない
    if exists and (role != "admin" or not active):
        others = con.execute("""SELECT COUNT(*) FROM app_users
                                WHERE role='admin' AND active=1 AND user_id != ?""", (uid,)).fetchone()[0]
        was_admin = con.execute("SELECT 1 FROM app_users WHERE user_id=? AND role='admin' AND active=1",
                                (uid,)).fetchone()
        if was_admin and others == 0:
            raise ValueError("最後の管理者は降格・無効化できません(先に別の管理者を作ってください)")
    if exists:
        con.execute("UPDATE app_users SET display_name=?, role=?, active=? WHERE user_id=?",
                    (name, role, active, uid))
    else:
        con.execute("INSERT INTO app_users(user_id, display_name, role, active) VALUES (?,?,?,?)",
                    (uid, name, role, active))
    if p.get("reset_password"):
        con.execute("UPDATE app_users SET pass_hash=NULL WHERE user_id=?", (uid,))
        con.execute("DELETE FROM app_sessions WHERE user_id=?", (uid,))  # 使い回し防止
    if not active:
        con.execute("DELETE FROM app_sessions WHERE user_id=?", (uid,))  # 無効化=即ログアウト
    con.commit()
    return {"users": list_app_users(con)}


def logout_user_all(con, uid):
    """指定ユーザーを全端末から強制ログアウト(セッションを全破棄)。
    パスワード・有効状態は変えないので、本人は同じパスワードで入り直せる。"""
    uid = str(uid or "").strip()
    if not uid:
        raise ValueError("ユーザーが指定されていません")
    con.execute("DELETE FROM app_sessions WHERE user_id=?", (uid,))
    con.commit()
    return {"users": list_app_users(con), "logged_out": uid}


# ── DMを出さない印(住所の先頭に付ける記号) ───────────────────────────────
# 店の運用では、DMが届かない/出さない顧客の住所の先頭に記号を3つ重ねて書いている
# (例「ＴＴＴ豊田市桜町1-18」)。住所を見ただけで理由が分かり、万一ラベルに印字されても
# 気付けるようにするための仕組み。ここではその記号を機械にも読ませ、宛名の書き出し・
# 印刷から自動で除外する。
# ★同じ判定を画面側(tokiwa-ui.html の DM_BLOCK_REASONS / dmBlockReason)にも持っている。
#   記号を増やす時は両方を直すこと(サーバー=B2書き出し / 画面=24面ラベル印刷)。
DM_BLOCK_REASONS = {
    "T": "転居", "S": "死去", "M": "店の都合", "K": "本人希望", "F": "福祉(生活保護)",
}


def dm_block_reason(address):
    """住所の先頭の記号からDMを出さない理由を返す。該当しなければ None。

    全角(ＴＴＴ)・半角(TTT)・小文字(ttt)のどれで書かれていても拾う。
    日本語の住所がこれらの並びで始まることはないため、誤検知の心配はない。
    """
    s = unicodedata.normalize("NFKC", str(address or "")).strip().upper()
    for letter, reason in DM_BLOCK_REASONS.items():
        if s.startswith(letter * 3):
            return reason
    return None


# ── DM区分(customers.dm_ok)の表記ゆれ ────────────────────────────────────
# 同じ列に取込元ごとの表記が混在している(CSV取込=送る/送らない、xlsx取込=元の列の値を
# そのまま、旧UI=可/不可)。表記を「送る/送らない」に寄せる過程でも古い値が残るため、
# 読み取り側で吸収する。
# ★ここに無い値は「送る」として扱う。実データに別の表記(有/無 等)があれば必ず足すこと。
#   空欄は「送る」= 店の運用で「出したくない意思がある時だけ値を入れている」ため。
DM_NO_VALUES = ("送らない", "送付しない", "送付不可", "不可", "無", "無し", "なし",
                "いいえ", "×", "x", "2")
_DM_NO_NORM = tuple(sorted({normjp(v) for v in DM_NO_VALUES}))


def dm_is_blocked(dm_ok):
    """DM区分が「送らない」を意味するかを返す(空欄・不明な値は「送る」扱い)。"""
    return normjp(str(dm_ok or "").strip()) in _DM_NO_NORM


def _count_reasons(reasons):
    """理由の一覧を「転居1件・死去2件」の形にまとめる(案内文用)。"""
    counts = {}
    for r in reasons:
        counts[r] = counts.get(r, 0) + 1
    return "・".join(f"{k}{v}件" for k, v in counts.items())


def kuroneko_b2_customers(con, ids):
    """クロネコB2(DM便)書き出し用に、選ばれた顧客の必須項目を集める。

    2種類の理由で書き出さない顧客がいる。取り違えると原因が分からなくなるため分けて返す。
      blocked … DMを出さない相手。住所の先頭の記号(転居・死去など)か、DM区分の「送らない」
      skipped … 電話番号・郵便番号・住所・名前のいずれかが無い(B2側の必須項目)
    ★とくに「死去」の顧客をヤマトへ送ってしまうと取り返しがつかないため、
      出さない判定は必須項目の確認より先に行う。
    """
    con.row_factory = sqlite3.Row
    rows, skipped, blocked = [], [], []
    for cid in ids or []:
        r = con.execute("SELECT name,tel,postal,address,address2,dm_ok FROM customers WHERE customer_id=?",
                         (cid,)).fetchone()
        if not r:
            continue
        # 住所の記号とDM区分のどちらか一方でも「出さない」なら出さない(安全側に倒す)
        reason = dm_block_reason(r["address"]) or ("送らない" if dm_is_blocked(r["dm_ok"]) else None)
        if reason:
            blocked.append(reason)
            continue
        if not (r["name"] and r["tel"] and r["postal"] and r["address"]):
            skipped.append(r["name"] if r["name"] else cid)
            continue
        rows.append({"name": r["name"], "tel": r["tel"], "postal": r["postal"],
                     "address": r["address"], "address2": r["address2"] or ""})
    return rows, skipped, _count_reasons(blocked)
