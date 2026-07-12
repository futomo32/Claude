# -*- coding: utf-8 -*-
"""トキワ 機器疎通テスト（レシートプリンター CT-S601 + ドロワー）

トキワ本体と同じ「自分のコードから COM ポート経由で機器を叩く」経路を検証する。
pyserial が必要:  pip install pyserial

注意: 宝飾ナビ起動中は COM ポートが使用中で開けない。テスト時は宝飾ナビを終了すること。
"""
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("[エラー] pyserial が入っていません。")
    print("  コマンドプロンプトで  pip install pyserial  を実行してください。")
    sys.exit(1)

ESC = b"\x1b"
GS = b"\x1d"
FS = b"\x1c"
DRAWER_KICK = ESC + b"p" + b"\x00" + b"\x19" + b"\xfa"  # ESC p 0 25 250 (2番ピン)


def list_all():
    ports = list(list_ports.comports())
    print("=== 認識されている COM ポート ===")
    if not ports:
        print("  （COM ポートが見つかりません）")
    for p in ports:
        print(f"  {p.device} : {p.description}  [{p.hwid}]")
    print()
    return ports


def guess_printer(ports):
    """CITIZEN CT-S601 らしき COM を推測（VID 1D90 / 名称）。"""
    for p in ports:
        blob = ((p.description or "") + " " + (p.hwid or "")).upper()
        if "1D90" in blob or "CITIZEN" in blob or "CT-S601" in blob:
            return p.device
    return None


def receipt_bytes():
    buf = bytearray()
    buf += ESC + b"@"           # 初期化
    buf += ESC + b"a" + b"\x01"  # 中央寄せ
    buf += b"TOKIWA DEVICE TEST\n"
    buf += time.strftime("%Y-%m-%d %H:%M:%S\n").encode("ascii")
    buf += FS + b"&"            # 漢字モード ON
    buf += "トキワ 機器テスト\n".encode("shift_jis", "replace")
    buf += "レシート印字 OK\n".encode("shift_jis", "replace")
    buf += FS + b"."            # 漢字モード OFF
    buf += ESC + b"a" + b"\x00"  # 左寄せ
    buf += b"--------------------------------\n"
    buf += b"If you can read this, printing works.\n"
    buf += b"\n\n\n"
    buf += GS + b"V" + b"\x00"   # フルカット
    return bytes(buf)


def main():
    print("========================================")
    print("  トキワ 機器疎通テスト（プリンター/ドロワー）")
    print("========================================")
    print("※ 宝飾ナビ起動中は COM を開けません。終了してから実行してください。\n")

    ports = list_all()
    default = guess_printer(ports) or "COM7"
    ans = input(f"プリンター(CT-S601)の COM ポート [{default}]: ").strip() or default

    print(f"\n{ans} に接続します...")
    try:
        ser = serial.Serial(ans, 115200, timeout=2)
    except Exception as e:  # noqa: BLE001
        print(f"[エラー] {ans} を開けませんでした: {e}")
        print("  → 宝飾ナビが起動中だと使用中で開けません。終了して再実行してください。")
        print("  → COM 番号が違う場合は、上の一覧から正しい番号を指定してください。")
        sys.exit(1)

    try:
        ser.write(receipt_bytes())
        ser.flush()
        time.sleep(0.3)
        print("→ レシートを送信しました。プリンターから紙が出れば「印字OK」です。\n")

        yn = input("ドロワーも開けてみますか？ (y/N): ").strip().lower()
        if yn == "y":
            ser.write(DRAWER_KICK)
            ser.flush()
            print("→ ドロワーキックを送信しました。引き出しが開けば「ドロワーOK」です。")
        else:
            print("ドロワーはスキップしました。")
    finally:
        ser.close()

    print("\n完了。結果（印字/ドロワー それぞれ OK か）を記録しておいてください。")


if __name__ == "__main__":
    main()
