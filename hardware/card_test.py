# -*- coding: utf-8 -*-
"""トキワ カード読み取りテスト(TCP300II・読み取り専用)。

カードを挿入 → 第2トラックの磁気を読み取り → hex/ASCII 表示。
券面(名前・発行日・ポイント)の裏で、磁気に何が記録されているか(=顧客キー)を確認する。

★このツールはカードに書き込みません(読み取りのみ)。安全に試せます。
pyserial が必要: pip install pyserial
宝飾ナビ起動中は COM を開けないので終了してから実行してください。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from tcp300ii import TCP300II, TCP300IIError, find_port, status_text
    from serial.tools import list_ports
except ImportError:
    print("[エラー] pyserial が入っていません。 pip install pyserial を実行してください。")
    sys.exit(1)


def show_ports():
    print("=== 認識されている COM ポート ===")
    ports = list(list_ports.comports())
    for p in ports:
        print(f"  {p.device} : {p.description}  [{p.hwid}]")
    if not ports:
        print("  (COMポートが見つかりません)")
    print()


def dump(data: bytes):
    if not data:
        print("  (データ無し)")
        return
    ascii_str = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)
    hex_str = " ".join(f"{b:02X}" for b in data)
    print(f"  文字数 : {len(data)}")
    print(f"  ASCII  : {ascii_str}")
    print(f"  HEX    : {hex_str}")


def main():
    print("==================================================")
    print("  トキワ カード読み取りテスト(TCP300II・読取専用)")
    print("==================================================")
    print("※ 宝飾ナビ終了後に実行してください。カードには書き込みません。\n")

    show_ports()
    default = find_port() or "COM3"
    port = input(f"カードリーダーの COM ポート [{default}]: ").strip() or default

    try:
        dev = TCP300II(port)
    except TCP300IIError as e:
        print(f"[エラー] {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"[エラー] {port} を開けませんでした: {e}")
        print("  → 宝飾ナビ起動中/COM番号違いの可能性。上の一覧を確認してください。")
        sys.exit(1)

    try:
        # まず装置ステータスを確認(疎通チェック)
        try:
            st, _ = dev.status_request()
            print(f"装置ステータス: {status_text(st)}\n")
        except TCP300IIError as e:
            print(f"(ステータス要求はスキップ: {e})\n")

        print(">> カードを挿入してください(最大30秒待ちます)...")
        status, data = dev.read_track2(resp_timeout=30.0)
        print(f"\n読取ステータス: {status_text(status)}")
        if status == 0x20:
            print("第2トラックの磁気データ:")
            dump(data)
            print("\n→ この値が顧客を特定するキー(会員番号など)のはずです。")
            print("  券面の名前/ポイントと突き合わせて、桁数・書式を確認してください。")
        else:
            print("正常に読み取れませんでした。逆差し/磁気なし/カード種別違いの可能性。")

        # 読み終えたらカードを返す
        try:
            dev.eject()
            print("\nカードを排出しました。")
        except TCP300IIError:
            pass
    finally:
        dev.close()

    print("\n完了。読み取れた HEX/ASCII をそのまま記録・共有してください。")


if __name__ == "__main__":
    main()
