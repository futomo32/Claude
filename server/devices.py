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
RECEIPT_WIDTH = 30                 # 58mm紙の実測桁数(右端欠け対策)

ESC = b"\x1b"
GS = b"\x1d"
FS = b"\x1c"
DRAWER_KICK = ESC + b"p" + b"\x00\x19\xfa"  # ESC p 0 25 250 (2番ピン)


def _skip():
    return {"skipped": True, "message": "機器OFFモードのため送信していません(機器ありで起動.bat でON)"}


# ── レシート印字 ──────────────────────────────────────

def _pad_line(left, right):
    """左右寄せの1行(全角=2桁で幅を数える)。"""
    def w(s):
        return sum(2 if ord(c) > 0xFF else 1 for c in s)
    space = RECEIPT_WIDTH - w(left) - w(right)
    return left + " " * max(1, space) + right


def build_receipt_bytes(r):
    """レシートのESC/POSバイト列を組み立てる。r = db_query.receipt_data() の dict。
    漢字はShift-JIS(FS C 1)・FS &/FS . で漢字モード切替(実測2026-07-12)。"""
    def sj(text):
        return text.encode("shift_jis", "replace")

    buf = bytearray()
    buf += ESC + b"@"            # 初期化
    buf += FS + b"C" + b"\x01"   # 漢字コード = Shift-JIS
    buf += FS + b"&"             # 漢字モードON
    buf += ESC + b"a" + b"\x01"  # 中央寄せ
    buf += GS + b"!" + b"\x01"   # 縦2倍
    buf += sj("宝石・メガネ・時計 ヤナセ\n")
    buf += GS + b"!" + b"\x00"
    buf += sj("御計算書\n")
    buf += ESC + b"a" + b"\x00"  # 左寄せ
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    buf += sj(f"日付: {r['sold_at']}  伝票 #{r['slip_id']}\n")
    if r.get("customer"):
        buf += sj(_pad_line(f"{r['customer']} 様", "") + "\n")
    if r.get("staff"):
        buf += sj(f"担当: {r['staff']}\n")
    buf += sj("-" * RECEIPT_WIDTH + "\n")
    for name, amount in r["lines"]:
        nm = str(name or "お品物")
        amt = f"\\{amount:,}"
        if sum(2 if ord(c) > 0xFF else 1 for c in nm) + len(amt) + 1 > RECEIPT_WIDTH:
            buf += sj(nm + "\n")
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
    buf += ESC + b"a" + b"\x01"
    buf += sj("お買い上げありがとうございます\n")
    buf += FS + b"."             # 漢字モードOFF
    buf += b"\n\n\n"
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
    """カード挿入を待って磁気(トラック2)を読む。読んだ後カードは装置内に残る
    (未知カードなら続けて card_link で書換できるように)。トキワ形式なら排出する。
    戻り {customer_id} | {unknown: true, raw} | {error} | {skipped}。"""
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
                _eject_safe(dev)
                return {"customer_id": cid, "raw": raw}
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

# ── 未実装(次フェーズ) ──
# 券面リライト印字(46h 消去+印字→排出): 印字データ設定(41h)のデータ形式
# (位置指定・フォント指定のエスケープ)がコマンド仕様書の書き起こしにまだ無い。
# 本番機の仕様書から 41h のデータ形式を docs/tcp300ii-protocol.md に追記してから実装する。
# レイアウト: 名前・発行日・有効期限(最終購入日+card_expiry_years年)・ポイント・案内文。
