# -*- coding: utf-8 -*-
"""TCP300II 券面リライト印字テスト(★必ず予備カードで実行すること)。

やること: 印字バッファクリア → 見本レイアウト(お名前/発行日/有効期限/ポイント)を設定
→ 消去+印字→排出(46h)。カードが入っていなければ挿入を待つ。
磁気ストライプには一切触らない(印字面のみ)。

レイアウト座標は server/devices.py の FACE_* 定数を使う。印字結果の写真を見て
FACE_LABEL_X / FACE_VALUE_X / FACE_TOP_Y / FACE_LINE_H を調整する。

注意: 宝飾ナビ起動中はCOMポートを開けません。終了してから実行してください。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
sys.path.insert(0, os.path.dirname(__file__))

from tcp300ii import TCP300II, TCP300IIError, find_port, status_text  # noqa: E402
import devices  # noqa: E402  レイアウト定数(FACE_*)を共用


SAMPLE = {"name": "児玉 香", "issued": "2026.07.29", "expiry": "2031.07.28", "points": 1234,
          "message": "新春セール開催中！\n1/10までポイント2倍"}


def main():
    print("=" * 48)
    print("  TCP300II 券面リライト印字テスト")
    print("=" * 48)
    print("★必ず予備カードで実行してください(券面が書き変わります)")
    print("※宝飾ナビ起動中はCOMを開けません。終了してから実行。")
    print()
    print("印字する見本データ:")
    for k, v in SAMPLE.items():
        print(f"  {k}: {v}")
    print(f"レイアウト: 方向={devices.FACE_DIR} 項目X={devices.FACE_LABEL_X} 値X={devices.FACE_VALUE_X}"
          f" 先頭Y={devices.FACE_TOP_Y} 行送り={devices.FACE_LINE_H}")
    print()

    print("モードを選んでください:")
    print("  1: 見本レイアウト印字(お名前/発行日/有効期限/ポイント)")
    print("  2: 座標グリッド印字(白枠の範囲を測る較正用。X/Yの目盛りを印字)")
    mode = input("モード [1]: ").strip() or "1"

    port = find_port() or "COM3"
    ans = input(f"カードR/W(TCP300II)のCOMポート [{port}]: ").strip() or port
    if input("実行しますか? (y/N): ").strip().lower() != "y":
        print("中止しました。")
        return

    if mode == "2":
        cmds = devices.build_card_grid_cmds()
    else:
        cmds = devices.build_card_face_cmds(SAMPLE["name"], SAMPLE["issued"],
                                            SAMPLE["expiry"], SAMPLE["points"],
                                            SAMPLE.get("message", ""))

    try:
        with TCP300II(ans) as dev:
            print("→ 印字バッファクリア(40h)...")
            st = dev.print_buffer_clear()
            print("   ", status_text(st))
            if st != 0x20:
                return

            print("→ 印字データ設定(41h)...")
            for c in cmds:
                st = dev.set_print_text(c)
                print(f"    {c.decode('shift_jis', 'replace')!r} → {status_text(st)}")
                if st != 0x20:
                    return

            print("→ 消去+印字→排出(46h)。カードが入っていなければ挿入してください...")
            st = dev.erase_print_eject()
            print("   ", status_text(st))
            if st == 0x20:
                print("\n★ 印字完了。カード券面を確認して写真を撮ってください。")
                print("  位置がずれている場合は server/devices.py の FACE_* を調整します。")
            else:
                print("\n印字に失敗しました。上のステータスを報告してください。")
    except TCP300IIError as e:
        print("[エラー]", e)
        print("  → 宝飾ナビが起動中だとCOMを開けません。")
    except Exception as e:  # noqa: BLE001
        print("[エラー]", e)


if __name__ == "__main__":
    main()
