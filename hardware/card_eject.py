# -*- coding: utf-8 -*-
"""TCP300II カード排出ツール(中に残ったカードを取り出す)。

排出コマンド(50h)を送る。ダメならリセット(5Fh)→排出を試す。
カードには書き込みません。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from tcp300ii import TCP300II, TCP300IIError, find_port, status_text
except ImportError:
    print("[エラー] pyserial が入っていません。 pip install pyserial を実行してください。")
    input("Enterキーで終了...")
    sys.exit(1)


def main():
    print("========================================")
    print("  TCP300II カード排出ツール")
    print("========================================\n")
    default = find_port() or "COM3"
    port = input(f"カードリーダーの COM ポート [{default}]: ").strip() or default

    try:
        dev = TCP300II(port)
    except Exception as e:  # noqa: BLE001
        print(f"[エラー] {port} を開けませんでした: {e}")
        print("  → 宝飾ナビ等が起動中なら終了してから再実行してください。")
        return

    try:
        print("排出コマンド(50h)を送信します...")
        try:
            _, status, _ = dev.eject()
            print(f"排出結果: {status_text(status)}")
            if status == 0x20:
                print("→ カードが出てきたはずです。抜き取ってください。")
                return
        except TCP300IIError as e:
            print(f"排出失敗: {e}")

        print("\nリセット(5Fh)を送って初期化します(約3秒)...")
        dev.reset()
        print("もう一度排出コマンドを送信します...")
        try:
            _, status, _ = dev.eject()
            print(f"排出結果: {status_text(status)}")
            if status == 0x20:
                print("→ カードが出てきたはずです。抜き取ってください。")
            else:
                print("→ 出てこない場合は、リーダーの電源を一度切って入れ直してください。")
        except TCP300IIError as e:
            print(f"排出失敗: {e}")
            print("→ リーダーの電源を一度切って入れ直してください(初期化時に排出されます)。")
    finally:
        dev.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
    input("\nEnterキーで終了...")
