# -*- coding: utf-8 -*-
"""トキワ カード読み取りテスト(TCP300II・読み取り専用)。

カードを挿入 → 第2トラックの磁気を読み取り → hex/ASCII 表示。
券面(名前・発行日・ポイント)の裏で、磁気に何が記録されているか(=顧客キー)を確認する。

★このツールはカードに書き込みません(読み取りのみ)。
★終了時に必ずカード排出を試みます。エラーでも画面は消えません。
★通信ログを hardware/card_test.log に保存します(トラブル解析用)。

pyserial が必要: pip install pyserial
宝飾ナビ起動中は COM を開けないので終了してから実行してください。
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOG = os.path.join(HERE, "card_test.log")

try:
    from tcp300ii import TCP300II, TCP300IIError, find_port, status_text
    from serial.tools import list_ports
except ImportError:
    print("[エラー] pyserial が入っていません。 pip install pyserial を実行してください。")
    input("Enterキーで終了...")
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


def save_log(dev, note=""):
    """通信トレースをログファイルに保存(次のデバッグ用)。"""
    try:
        with open(LOG, "w", encoding="utf-8-sig") as f:
            f.write("TCP300II 通信ログ\n")
            if note:
                f.write(f"メモ: {note}\n")
            f.write("-" * 40 + "\n")
            if dev is None or not dev.trace:
                f.write("(通信なし)\n")
            else:
                # RXの連続バイトはまとめて見やすく
                out, cur_dir, cur = [], None, []
                for d, h in dev.trace:
                    if d != cur_dir:
                        if cur:
                            out.append((cur_dir, " ".join(cur)))
                        cur_dir, cur = d, [h]
                    else:
                        cur.append(h)
                if cur:
                    out.append((cur_dir, " ".join(cur)))
                for d, h in out:
                    f.write(f"{d}: {h}\n")
        print(f"\n(通信ログを保存しました: {LOG})")
    except Exception:  # noqa: BLE001
        pass


def main():
    print("==================================================")
    print("  トキワ カード読み取りテスト(TCP300II・読取専用)")
    print("==================================================")
    print("※ 宝飾ナビ終了後に実行してください。カードには書き込みません。")
    print("※ 終了時に必ずカード排出を試みます。\n")

    show_ports()
    default = find_port() or "COM3"
    port = input(f"カードリーダーの COM ポート [{default}]: ").strip() or default

    dev = None
    note = ""
    try:
        dev = TCP300II(port)
    except TCP300IIError as e:
        print(f"[エラー] {e}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"[エラー] {port} を開けませんでした: {e}")
        print("  → 宝飾ナビ起動中/COM番号違いの可能性。上の一覧を確認してください。")
        return

    try:
        # まず装置ステータスを確認(疎通チェック)
        try:
            st, _ = dev.status_request()
            print(f"装置ステータス: {status_text(st)}\n")
        except TCP300IIError as e:
            print(f"(ステータス要求はスキップ: {e})\n")

        print(">> カードを挿入してください(最大30秒待ちます)...")
        # 実測(2026-07-12): 7bit指定('0')はLRCエラーになった。宝飾ナビは逆7bit書込の
        # 可能性が高いため '4' を先に試す(成功すれば書込形式の確定にもなる)。
        # ダメなら自動識別(22h)へフォールバック。
        method = "逆7bit指定(24h '2,4')"
        try:
            status, data = dev.read_track2_fmt("4", resp_timeout=30.0)
            if status != 0x20:
                print(f"(逆7bit指定リード: {status_text(status)} → 自動識別で再試行)")
                method = "自動識別(22h)"
                status, data = dev.read_track2(resp_timeout=15.0)
        except TCP300IIError as e:
            note = f"read 失敗: {e}"
            print(f"\n[読み取りエラー] {e}")
            print("→ 通信ログを確認します。カードは排出を試みます。")
            return
        print(f"読み取り方式: {method}")

        print(f"\n読取ステータス: {status_text(status)}")
        note = f"{method} status={status_text(status)}"
        if status == 0x20:
            print("第2トラックの磁気データ:")
            dump(data)
            print("\n→ この値が顧客を特定するキー(会員番号など)のはずです。")
            print("  券面の名前/ポイントと突き合わせて、桁数・書式を確認してください。")
        else:
            print("正常に読み取れませんでした。逆差し/磁気なし/カード種別違いの可能性。")
    finally:
        if dev is not None:
            # 成否に関わらず必ず排出を試みる(カードを飲み込んだままにしない)
            try:
                print("\nカードを排出します...")
                _, est, _ = dev.eject()
                print(f"排出結果: {status_text(est)}")
            except Exception as e:  # noqa: BLE001
                print(f"排出できませんでした: {e}")
                print("→ リセット後にもう一度排出を試みます(約3秒)...")
                try:
                    dev.reset()
                    _, est, _ = dev.eject()
                    print(f"排出結果: {status_text(est)}")
                except Exception as e2:  # noqa: BLE001
                    print(f"それでも排出できませんでした: {e2}")
                    print("→ カード排出.bat か、リーダーの電源入れ直しで取り出してください。")
            save_log(dev, note)
            dev.close()

    print("\n完了。読み取れた HEX/ASCII (または card_test.log) を共有してください。")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    # ダブルクリック起動でも画面が消えないように必ず待つ
    input("\nEnterキーで終了...")
