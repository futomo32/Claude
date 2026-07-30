# -*- coding: utf-8 -*-
"""トキワ 機器制御層(フェーズ2)。レシートプリンター CT-S601・ドロワー・
リライトカードR/W TCP300II を、会計フローから使うための入口をまとめる。

★機器モード(ENABLED)がOFFの間は、どの関数も機器に一切送信せず
  {"skipped": "機器OFFモード"} を返す。宝飾ナビがCOMポートを使っていても安全。
  切替は起動方法で行う(app.py 引数 "kiki"。機器ありで起動.bat)。

接続方式(docs/hardware-report.md の実測に基づく):
- レシート: スプーラー経由RAW印字(win32print)を優先。双方向サポートONのまま共存できる。
  win32print(pywin32)が無い環境では直接COM(pyserial)にフォールバック
  (この場合はプリンターの「双方向サポート」をOFFにする必要がある)。
- ドロワー: レシートと同じ経路に ESC p を送る(プリンター背面キック端子)。
- カード: hardware/tcp300ii.py の自作ドライバ(COM3・磁気トラック2)。

カードの磁気データ(トキワ形式・方式B):
  "TKW" + 顧客ID(そのまま平文)。例: TKW01-4335
  宝飾ナビ形式(60文字の独自エンコード)のカードは初回挿入時に店員が顧客を選んで
  紐付け→この形式に書き換える。以後はカード挿入だけで顧客を自動呼出できる。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hardware"))

# app.py の main() が起動引数に応じて True にする(既定は必ずOFF)
ENABLED = False

# 本番機実測値。機器構成が変わったらここを直す
PRINTER_NAME = "CITIZEN CT-S601"   # Windowsスプーラーのプリンター名(RAW印字)
PRINTER_COM = "COM7"               # 直接COMフォールバック用
CARD_PORT = "COM3"                 # TCP300II
RECEIPT_WIDTH = 34                 # 印字桁数。桁数テストでは36桁=432ドットまで出たが、432は印字幅の
                                   # 上限ちょうど(余白ゼロ)で、紙の左右の遊びで右端が欠けた(2026-07-31実測。
                                   # ¥998→¥99・109pt→109p 等)。安全マージン2桁を引いて34桁=408ドットに
# 店名・電話・インボイス登録番号は store_info.py が唯一の正(帳票側と共通)
import store_info                  # noqa: E402
STORE_TEL = store_info.STORE_TEL
STORE_REG_NO = store_info.INVOICE_REG_NO
LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")
# PAPER_DOTS は実機で確定済み(2026-07-30 桁数テスト): 36桁=432ドットが折り返さず印字された
# → 実効印字幅は 432ドット(=54mm。CT-S601の58mm紙の最大値)。
# 中央寄せテストの目盛りが400ドット過ぎまで印字されていたこととも整合する。
PAPER_DOTS = 432                   # 実効印字幅(ドット)。中央寄せの基準
LOGO_DOTS = 336                    # ロゴ印字幅の上限(ドット≒42mm)。最大432まで上げられる(紙幅いっぱい)
LOGO_MAX_H = 336                   # ロゴ高さの上限(ドット≒42mm)。実機の見比べでGパターンを採用(2026-07-30)
LOGO_OFFSET_DOTS = -12             # 中央寄せの微調整。右へずらすドット数(負=左へ。1ドット単位)。
                                   # 文字は34桁(408dot)の枠中央=204dot、ロゴは物理幅432dotの中央=216dot と
                                   # 基準がずれるため、-12 で文字と同じ軸に揃える(2026-07-31 実機写真で確認)
LOGO_DITHER = False                # 二値化方式: False=しきい値(ベタ塗り・線画ロゴ向き。エッジがパリッと出る)
                                   #             True=Floyd-Steinbergディザ(濃淡・グラデのあるロゴ向き)
LOGO_THRESHOLD = 160               # しきい値方式のときの白黒境界(0-255。上げると太く・黒く印字される)

ESC = b"\x1b"
GS = b"\x1d"
FS = b"\x1c"
DRAWER_KICK = ESC + b"p" + b"\x00\x19\xfa"  # ESC p 0 25 250 (2番ピン)


def _skip():
    return {"skipped": True, "message": "機器OFFモードのため送信していません(機器ありで起動.bat でON)"}


# ── レシート印字 ──────────────────────────────────────

def _w(s):
    """印字幅(全角=2桁・半角=1桁)。"""
    return sum(2 if ord(c) > 0xFF else 1 for c in s)


def _pad_line(left, right):
    """左右寄せの1行。"""
    space = RECEIPT_WIDTH - _w(left) - _w(right)
    return left + " " * max(1, space) + right


def _center(s):
    """中央寄せの1行(手動スペース詰め)。ESC a の中央寄せはラスタ画像に効かない・
    機種や漢字モードで挙動が揺れるため、印字桁数から自前で計算する(確実)。"""
    return " " * max(0, (RECEIPT_WIDTH - _w(s)) // 2) + s


def _wrap(text, width=None):
    """幅に収まるよう折り返して行のリストを返す(長い品名のはみ出し防止)。"""
    width = width or RECEIPT_WIDTH
    lines, cur, cw = [], "", 0
    for c in str(text):
        w = 2 if ord(c) > 0xFF else 1
        if cw + w > width:
            lines.append(cur)
            cur, cw = c, w
        else:
            cur += c
            cw += w
    if cur:
        lines.append(cur)
    return lines or [""]


def _raster_from_image(img, offset_dots=0):
    """1bit画像(PIL)をESC/POSのラスタ画像(GS v 0)に変換する。

    offset_dots: 左に入れる白ドット数。**ビット単位でずらす**ので1ドット刻みで位置調整できる
    (ESC $ の絶対位置指定はラスタに効かない機種があるため、データ側でずらす確実な方法にする)。
    """
    w, h = img.size
    px = img.load()
    off = max(0, int(offset_dots))
    row_bytes = (off + w + 7) // 8
    data = bytearray()
    for y in range(h):
        row = bytearray(row_bytes)
        for x in range(w):
            if px[x, y] == 0:            # 黒
                bit = off + x
                row[bit >> 3] |= 0x80 >> (bit & 7)
        data += row
    head = GS + b"v0" + b"\x00" + bytes([row_bytes & 0xFF, row_bytes >> 8, h & 0xFF, h >> 8])
    return bytes(head) + bytes(data)


def _logo_raster():
    """assets/logo.png をESC/POSのラスタ画像(GS v 0)に変換して返す。
    高解像度PNG → LANCZOS縮小 → 二値化(LOGO_DITHERで しきい値/ディザ を切替)。
    ラスタにはESC aの中央寄せが効かないため、左に白ドットを足して紙幅の中央に寄せる
    (微調整は LOGO_OFFSET_DOTS)。
    Pillowが無い・ロゴが無い・変換失敗のときは None(呼び出し側が文字の店名にフォールバック)。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(LOGO_PATH).convert("LA")
        # 透過PNG対策: 透明部分は白として扱う
        bg = Image.new("L", img.size, 255)
        bg.paste(img.getchannel("L"), mask=img.getchannel("A"))
        img = bg
        # 絵柄の周りの白い縁を自動で切り落とす。縁ごと縮小すると絵柄が小さくなり
        # 上下に大きな空白が出るため(実ロゴは絵柄が画像の高さ30%しかなかった 2026-07-30)
        bbox = img.point(lambda p: 255 if p < 240 else 0).getbbox()
        if bbox:
            img = img.crop(bbox)
        # 幅・高さ両方の上限に収める(縦横比は維持)。幅は8の倍数に丸める
        scale = min(LOGO_DOTS / img.width, LOGO_MAX_H / img.height)
        w = max(8, int(img.width * scale) // 8 * 8)
        h = max(1, round(img.height * w / img.width))
        img = img.resize((w, h), Image.LANCZOS)  # 高解像度ロゴからの縮小でも輪郭を滑らかに
        if LOGO_DITHER:
            img = img.convert("1")  # Floyd-Steinbergディザ(濃淡をドット密度で再現)
        else:
            img = img.point(lambda p: 0 if p < LOGO_THRESHOLD else 255, mode="1")
        offset = max(0, (PAPER_DOTS - w) // 2) + LOGO_OFFSET_DOTS   # 中央寄せ + 実機に合わせた微調整
        return _raster_from_image(img, offset)
    except Exception:  # noqa: BLE001 ロゴが読めなくてもレシートは出す
        return None


def build_receipt_bytes(r):
    """レシートのESC/POSバイト列を組み立てる。r = db_query.receipt_data() の dict。
    漢字はShift-JIS(FS C 1)・FS &/FS . で漢字モード切替(実測2026-07-12)。"""
    def sj(text):
        return text.encode("shift_jis", "replace")

    buf = bytearray()
    buf += ESC + b"@"            # 初期化
    buf += FS + b"C" + b"\x01"   # 漢字コード = Shift-JIS
    buf += FS + b"&"             # 漢字モードON
    # 中央寄せは _center()(スペース詰め)で行う。ESC a はラスタに効かず機種差もあるため使わない
    logo = _logo_raster()
    if logo:
        buf += logo              # ロゴ画像(あれば店名の代わりに。中央寄せ済みラスタ)
        buf += b"\n"
    else:
        buf += GS + b"!" + b"\x01"   # 縦2倍
        buf += sj(_center(store_info.STORE_NAME) + "\n")
        buf += GS + b"!" + b"\x00"
    buf += sj(_center("御計算書") + "\n")
    buf += sj(_center(f"TEL {STORE_TEL}") + "\n")
    if STORE_REG_NO:               # インボイス登録番号(適格簡易請求書の必須記載事項)
        buf += sj(_center(f"登録番号 {STORE_REG_NO}") + "\n")
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    buf += sj(f"日付: {r['sold_at']} 伝票#{r['slip_id']}\n")
    if r.get("customer"):
        buf += sj(_pad_line(f"{r['customer']} 様", "") + "\n")
    if r.get("staff"):
        buf += sj(f"担当: {r['staff']}\n")
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    for line in r["lines"]:
        name, amount = line[0], line[1]
        lp = line[2] if len(line) > 2 else None
        nm = str(name or "お品物")
        amt = f"\\{amount:,}"
        wide = _w(nm) + len(amt) + 1 > RECEIPT_WIDTH
        if lp and amount < lp:
            # 定価より安く売った明細: 品名 → 「 定価\79,200 33%引   \53,000」(宝飾ナビと同じ見せ方)
            rate = round((lp - amount) / lp * 100)
            for seg in _wrap(nm):
                buf += sj(seg + "\n")
            buf += sj(_pad_line(f" 定価\\{lp:,} {rate}%引", amt) + "\n")
        elif wide:
            for seg in _wrap(nm):
                buf += sj(seg + "\n")
            buf += sj(_pad_line("", amt) + "\n")
        else:
            buf += sj(_pad_line(nm, amt) + "\n")
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    tax = r["total"] * 10 // 110
    buf += sj(_pad_line("合計(税込)", f"\\{r['total']:,}") + "\n")
    buf += sj(_pad_line("(内消費税10%)", f"\\{tax:,}") + "\n")
    for method, amount in r["payments"]:
        label = f"{amount:,}pt" if method == "ポイント" else f"\\{amount:,}"
        buf += sj(_pad_line(f"  {method}", label) + "\n")
    if r.get("deposit"):
        buf += sj(_pad_line("お預かり", f"\\{r['deposit']:,}") + "\n")
        buf += sj(_pad_line("お釣り", f"\\{r['deposit'] - r['cash_due']:,}") + "\n")
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    # ポイント(使用/加算/残高)。カード券面の代わりに残高が分かる(レシート残高印字)
    if r.get("points_used"):
        buf += sj(_pad_line("ご使用ポイント", f"{r['points_used']:,}pt") + "\n")
    buf += sj(_pad_line("加算ポイント", f"{r.get('earned', 0):,}pt") + "\n")
    buf += sj(_pad_line("ポイント残高", f"{r.get('point_balance', 0):,}pt") + "\n")
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    # 感謝の一文(設定画面で変更可。修理のお客様向けに中立な文言に変える等。空=印字なし)
    thanks = str(r.get("thanks", "お買上げありがとうございます") or "").strip()
    if thanks:
        buf += sj(_center(thanks) + "\n")
    # レシート下部メッセージ。この会計だけの一言(note)を上に、全レシート共通(message)を下に。
    # どちらも空なら何も印字しない。
    for text in (r.get("note"), r.get("message")):
        text = str(text or "").strip()
        if not text:
            continue
        buf += b"\n"
        for ln in text.splitlines():
            for seg in _wrap(ln):
                buf += sj(_center(seg) + "\n")
    buf += FS + b"."             # 漢字モードOFF
    # カッターは印字ヘッドより上にあるため、送りが少ないと最終行が切断位置にかかる
    # (実機で最下行が切れた 2026-07-29)。6行送ってからカットする
    buf += b"\n\n\n\n\n\n"
    buf += GS + b"V" + b"\x00"   # フルカット
    return bytes(buf)


def _send_to_printer(data: bytes):
    """スプーラーRAW(優先) → 直接COM の順で送る。"""
    try:
        import win32print
        h = win32print.OpenPrinter(PRINTER_NAME)
        try:
            win32print.StartDocPrinter(h, 1, ("トキワ レシート", None, "RAW"))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, data)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
        return "spooler"
    except ImportError:
        pass  # pywin32なし → 直接COMへ(双方向サポートOFFが必要)
    import serial
    ser = serial.Serial(PRINTER_COM, 115200, timeout=2)
    try:
        ser.write(data)
        ser.flush()
    finally:
        ser.close()
    return "com"


def print_receipt(receipt, drawer=True):
    """レシートを印字し、必要ならドロワーを開ける。"""
    if not ENABLED:
        return _skip()
    data = build_receipt_bytes(receipt)
    if drawer:
        data += DRAWER_KICK
    try:
        via = _send_to_printer(data)
        return {"ok": True, "via": via, "drawer": bool(drawer)}
    except Exception as e:  # noqa: BLE001 機器エラーで会計を壊さない(呼び出し側でトースト表示)
        return {"error": f"レシート印字に失敗: {e}"}


def open_drawer():
    """ドロワーだけ開ける(売掛入金の現金授受など)。"""
    if not ENABLED:
        return _skip()
    try:
        via = _send_to_printer(bytes(DRAWER_KICK))
        return {"ok": True, "via": via}
    except Exception as e:  # noqa: BLE001
        return {"error": f"ドロワーを開けられませんでした: {e}"}


# ── リライトカード(TCP300II) ──────────────────────────

CARD_PREFIX = "TKW"  # トキワ形式の磁気: "TKW"+顧客ID


def card_read(timeout=30.0):
    """カード挿入を待って磁気(トラック2)を読む。読んだ後カードは装置内に残る。
    トキワ形式: 顧客を返し、カードは保持したまま(宝飾ナビと同じ運用。会計確定時に
    券面を書き換えて排出する。会計しない場合は card_eject で返す)。2026-07-31 案A採用。
    未知カード: 続けて card_link で書換できるように保持。
    戻り {customer_id, held} | {unknown: true, raw} | {error} | {skipped}。"""
    if not ENABLED:
        return _skip()
    try:
        from tcp300ii import TCP300II, status_text
        with TCP300II(CARD_PORT) as dev:
            status, payload = dev.read_track2_fmt("4", resp_timeout=timeout)  # 逆7bit(宝飾ナビ/トキワ共通)
            if status != 0x20:
                try:
                    dev.reset()
                except Exception:  # noqa: BLE001
                    pass
                return {"error": "カードを読めませんでした: " + status_text(status)}
            raw = payload.decode("ascii", "replace").strip()
            if raw.startswith(CARD_PREFIX):
                cid = raw[len(CARD_PREFIX):]
                return {"customer_id": cid, "raw": raw, "held": True}
            return {"unknown": True, "raw": raw,
                    "message": "宝飾ナビ形式のカードです。顧客を選んで紐付けるとトキワ形式に書き換わります(カードは入れたまま)"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"カード読取に失敗: {e}"}


def card_link(customer_id, timeout=30.0):
    """装置内のカード(または新たに挿入されたカード)へ、トキワ形式
    ("TKW"+顧客ID)を逆7bitで磁気書込して排出する。初回紐付け(方式B)と再発行の両方に使う。"""
    if not ENABLED:
        return _skip()
    cid = str(customer_id or "").strip()
    if not cid:
        return {"error": "顧客が指定されていません"}
    data = (CARD_PREFIX + cid).encode("ascii", "replace")
    try:
        from tcp300ii import TCP300II, status_text
        with TCP300II(CARD_PORT) as dev:
            status = dev.write_track2(data, dataset_cmd=TCP300II.DATASET_REV7)
            if status != 0x20:
                return {"error": "磁気書込に失敗: " + status_text(status)}
            _eject_safe(dev)
            return {"ok": True, "customer_id": cid, "written": CARD_PREFIX + cid}
    except Exception as e:  # noqa: BLE001
        return {"error": f"カード書込に失敗: {e}"}


# ── 券面リライト印字(カード表面の文字の書き換え) ──
# 座標系(2026-07-29 実機グリッド印字で確定):
#   ・Yは小さいほど上(Y23〜319が使える。白枠上端≈Y0)
#   ・白枠内で印字できるのは X0〜約255(X240の目盛りが右端ぎりぎりだった)
#   ・文字は全角≈24ドット幅・半角≈12ドット幅
# 配置方向: '0'(縦置き+上書き)=カードを縦に持って横書き(宝飾ナビと同じ向き)。
# 縦置きグリッドの実測(2026-07-29): 使える範囲は X0〜約300 / Y約20〜230
#   (Y40〜Y200は白枠内・Y280は枠外の赤地。X240の目盛りは枠内に収まる)
FACE_DIR = "0"
FACE_LABEL_X = 20     # 項目名のX
FACE_VALUE_X = 130    # 値のX(有効期限=全角4文字96ドットの右に余白)
FACE_MAX_X = 300      # 白枠の右端
FACE_TOP_Y = 40       # 1行目のY(Y小=上)
FACE_LINE_H = 45      # 行送り。長い名前の5行構成(最終行Y220)でも下端230に収まる


def _dots(s):
    """印字幅(ドット)。全角24・半角12。"""
    return sum(24 if ord(c) > 0xFF else 12 for c in str(s))


ESC_B = b"\x1b"  # 41hテキスト中のESCシーケンス(文字サイズ指定等)


def _cmd(x, y, payload: bytes):
    """41hデータ列1件(ヘッダー+テキスト)。テキストにカンマを含み得るためヘッダーは常に付ける。"""
    return f"{FACE_DIR},{x},{y},".encode("ascii") + payload


def build_card_face_cmds(name, issued, expiry, points, message=""):
    """券面レイアウトを41hコマンドのデータ列(複数)にして返す(2026-07-29 レイアウト確定版)。
      お名前 ＋ 名前(縦倍)  … 長い名前(値幅170ドット超)は次の行に通常サイズで
      有効期限(通常)
      ポイント ＋ 数値(縦横倍)
      フリーメッセージ 最大2行(ラベルなし・全角22文字まで。空なら印字しない)
    発行日は券面から廃止(DBで見られるため)。余白は4ドットで詰める。
    ESC E11/E21/E22 で文字サイズを行ごとに明示する(前の行のサイズを引きずらない)。"""
    def sj(t):
        return str(t).encode("shift_jis", "replace")

    name_v = f"{name} 様"
    cmds = []
    long_name = FACE_VALUE_X + _dots(name_v) > FACE_MAX_X
    # 1行目: お名前ラベル(通常) + 名前(縦倍48ドット)。下端揃え
    y = FACE_TOP_Y + 28  # 縦倍の分だけ下端を下げる(上端は枠上部ぎりぎり)
    if not long_name:
        cmds.append(_cmd(FACE_LABEL_X, y, ESC_B + b"E11" + sj("お名前")))
        cmds.append(_cmd(FACE_VALUE_X, y, ESC_B + b"E21" + sj(name_v)))
    else:  # 長い名前: ラベル行の下に全幅・通常サイズで(行が1本増える)
        cmds.append(_cmd(FACE_LABEL_X, y, ESC_B + b"E11" + sj("お名前")))
        y += 28
        cmds.append(_cmd(30, y, ESC_B + b"E11" + sj(name_v)))
    # 有効期限(通常24ドット)
    y += 28
    cmds.append(_cmd(FACE_LABEL_X, y, ESC_B + b"E11" + sj("有効期限")))
    cmds.append(_cmd(FACE_VALUE_X, y, ESC_B + b"E11" + sj(str(expiry or ""))))
    # ポイント(数値は名前と同じ縦倍48ドット)。ラベルと下端揃え
    y += 52
    cmds.append(_cmd(FACE_LABEL_X, y, ESC_B + b"E11" + sj("ポイント")))
    cmds.append(_cmd(FACE_VALUE_X, y, ESC_B + b"E21" + sj(f"{int(points or 0):,}")))
    # フリーメッセージ(通常・ラベルなし)。ポイントとの間に半行(16ドット)の余白を入れる。
    # 長い名前の時は行が1本増えているため1行まで
    gap = 16
    for seg in _face_message_lines(message, max_lines=1 if long_name else 2):
        y += 28 + gap
        gap = 0  # 余白はメッセージ1行目の前だけ
        cmds.append(_cmd(FACE_LABEL_X, y, ESC_B + b"E11" + sj(seg)))
    return cmds


def _face_message_lines(message, max_lines=2):
    """券面メッセージを枠幅(全角11文字=264ドット)で最大2行に整形する。改行も尊重。"""
    out = []
    width = FACE_MAX_X - FACE_LABEL_X
    for raw in str(message or "").splitlines():
        raw = raw.strip()
        cur, cw = "", 0
        for c in raw:
            w = 24 if ord(c) > 0xFF else 12
            if cw + w > width:
                out.append(cur)
                cur, cw = c, w
            else:
                cur += c
                cw += w
        if cur:
            out.append(cur)
    return [s for s in out if s][:max_lines]


def build_card_grid_cmds():
    """座標グリッド(較正用)の41hデータ列。カードに座標の目盛りを印字し、写真から
    白枠の正確な範囲(X/Yの上限下限)を割り出すために使う。
    縦置き(FACE_DIR='0')の座標範囲: X0〜319 / Y0〜479。"""
    cmds = []
    for y in (40, 120, 200, 280, 360, 440):
        cmds.append(f"{FACE_DIR},0,{y},Y{y}".encode("ascii"))
    for x in (80, 160, 240):
        cmds.append(f"{FACE_DIR},{x},40,X{x}".encode("ascii"))
    return cmds


def card_face_print(face):
    """カード券面を消去→印字→排出する(46h)。face={name, issued, expiry, points}。
    カードが装置内に無ければ挿入を待つ。磁気は触らない(磁気書換は card_link)。"""
    if not ENABLED:
        return _skip()
    try:
        from tcp300ii import TCP300II, status_text
        with TCP300II(CARD_PORT) as dev:
            st = dev.print_buffer_clear()
            if st != 0x20:
                return {"error": "印字バッファクリアに失敗: " + status_text(st)}
            for c in build_card_face_cmds(face.get("name") or "", face.get("issued"),
                                          face.get("expiry"), face.get("points"),
                                          face.get("message") or ""):
                st = dev.set_print_text(c)
                if st != 0x20:
                    return {"error": "印字データ設定に失敗: " + status_text(st)}
            st = dev.erase_print_eject()
            if st != 0x20:
                return {"error": "券面の消去+印字に失敗: " + status_text(st)}
            return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"error": f"券面印字に失敗: {e}"}


def card_eject():
    """装置内のカードを排出する(紐付け中止など)。"""
    if not ENABLED:
        return _skip()
    try:
        from tcp300ii import TCP300II
        with TCP300II(CARD_PORT) as dev:
            _eject_safe(dev)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"error": f"カード排出に失敗: {e}"}


def _eject_safe(dev):
    """排出。読取直後にDLE拒否される個体差があるため、失敗したらリセットで排出する。"""
    try:
        dev.eject()
    except Exception:  # noqa: BLE001
        try:
            dev.reset()
        except Exception:  # noqa: BLE001
            pass


def hw_status():
    """機器モードと接続情報(画面の設定・診断表示用)。"""
    return {"enabled": ENABLED, "printer": PRINTER_NAME, "printerCom": PRINTER_COM,
            "cardPort": CARD_PORT}

# メモ: 券面レイアウトの座標(FACE_*)は実機の印字結果を見て調整する。
# テストは 券面印字テスト.bat (hardware/card_face_test.py) で行う。
