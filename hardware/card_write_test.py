# -*- coding: utf-8 -*-
"""トキワ カード書き込みテスト(TCP300II・★カードに書き込みます)。

宝飾ナビ→トキワ移行で唯一残った未検証点=「このリーダーでカードに書き込めるか」を
確定させるためのツール。手順はシンプルに:

    書く → その場で読み戻す → 一致すれば成功(=書込機能OK)

★★★★★ 重要・安全のための注意 ★★★★★
このツールは磁気トラック2を **上書き** します。実行するとそのカードの
既存の磁気データ(宝飾ナビ会員カードとしての中身)は **消えて元に戻せません**。
必ず「消えても構わない予備カード(白紙のリライトカード等)」で行ってください。
実際のお客様の会員カードは絶対に使わないでください。
★★★★★★★★★★★★★★★★★★★★★★★★★★★

書式について:
  この実機では「逆7bit」読み取りが実証済み(宝飾ナビと同形式)なので、
  既定は「逆7bitで書く → 逆7bitで読み戻す」。往復が一致すれば、
  将来トキワが独自形式(顧客ID平文など)でカードを書き換える方式が成立する。

pyserial が必要: pip install pyserial
宝飾ナビ起動中は COM を開けないので終了してから実行してください。
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOG = os.path.join(HERE, "card_write_test.log")

try:
    from tcp300ii import TCP300II, TCP300IIError, find_port, status_text
    from serial.tools import list_ports
except ImportError:
    print("[エラー] pyserial が入っていません。 pip install pyserial を実行してください。")
    input("Enterキーで終了...")
    sys.exit(1)

# 書式プリセット: (ラベル, データ設定コマンド, 読み戻しフォーマット指定)
FORMATS = {
    "1": ("逆7bit(宝飾ナビと同形式・推奨)", TCP300II.DATASET_REV7, "4"),
    "2": ("7bit(JIS X 6302)", TCP300II.DATASET_7BIT, "0"),
}


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


def valid_write_str(s: str):
    """磁気に書ける文字か検査。1文字1バイト・印字ASCII(0x20〜0x7E)のみ許可。
    仕様上のデータ域は 01h〜7Eh(02h/03h除く)だが、安全のため印字文字に限定する。"""
    if not s:
        return "空です"
    if len(s) > 69:
        return f"長すぎます({len(s)}文字)。7bitは最大69文字までです"
    for ch in s:
        c = ord(ch)
        if c < 0x20 or c > 0x7E:
            return f"使えない文字が含まれます: {ch!r}(印字ASCIIのみ可)"
    return None


def save_log(dev, note=""):
    try:
        with open(LOG, "w", encoding="utf-8-sig") as f:
            f.write("TCP300II 書き込みテスト 通信ログ\n")
            if note:
                f.write(f"メモ: {note}\n")
            f.write("-" * 40 + "\n")
            if dev is None or not dev.trace:
                f.write("(通信なし)\n")
            else:
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


def eject_card(dev):
    """成否に関わらずカードを取り出す。50h→ダメならリセットで排出(実機の癖に対応)。"""
    try:
        print("\nカードを排出します...")
        time.sleep(1.0)  # 直後の排出はDLE拒否されやすい(実測)ため少し待つ
        _, est, _ = dev.eject()
        print(f"排出結果: {status_text(est)}")
    except Exception as e:  # noqa: BLE001
        print(f"排出コマンドが通りません({e})")
        print("→ リセットで初期化します(約3秒)。初期化時にカードは排出されます...")
        try:
            dev.reset()
            print("→ カードが出てきているはずです。取り出してください。")
        except Exception as e2:  # noqa: BLE001
            print(f"リセットも失敗: {e2}")
            print("→ カード排出.bat か、リーダーの電源入れ直しで取り出してください。")


def main():
    print("==================================================")
    print("  トキワ カード書き込みテスト(TCP300II)")
    print("==================================================")
    print("★このツールはカードの磁気を【上書き】します。元に戻せません。")
    print("★必ず『消えても構わない予備カード』で実行してください。")
    print("★お客様の会員カードは絶対に使わないでください。\n")

    show_ports()

    # 二重の確認(誤実行防止)
    ans = input("予備カード(消えてもよいカード)を使いますか? [yes/no]: ").strip().lower()
    if ans not in ("yes", "y"):
        print("中止しました。")
        return
    kw = input('続けるには KAKIKOMI と入力してください: ').strip()
    if kw != "KAKIKOMI":
        print("入力が一致しないため中止しました。")
        return

    default = find_port() or "COM3"
    port = input(f"\nカードリーダーの COM ポート [{default}]: ").strip() or default

    print("\n=== 書き込む書式を選んでください ===")
    for k, (label, _cmd, _rf) in FORMATS.items():
        print(f"  {k}: {label}")
    fk = input("番号 [1]: ").strip() or "1"
    if fk not in FORMATS:
        print("不明な選択です。中止しました。")
        return
    fmt_label, dataset_cmd, read_fmt = FORMATS[fk]

    default_data = "TOKIWA-TEST-0001"
    data_str = input(f"書き込む文字列 [{default_data}]: ").strip() or default_data
    err = valid_write_str(data_str)
    if err:
        print(f"[エラー] {err}")
        return
    data = data_str.encode("ascii")

    print("\n--- 実行内容の確認 ---")
    print(f"  ポート    : {port}")
    print(f"  書式      : {fmt_label}")
    print(f"  書込データ: {data_str}  ({len(data)}文字)")
    go = input("この内容で書き込みます。よろしいですか? [yes/no]: ").strip().lower()
    if go not in ("yes", "y"):
        print("中止しました。")
        return

    dev = None
    note = f"fmt={fmt_label} data={data_str}"
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
        # 疎通確認
        try:
            st, _ = dev.status_request()
            print(f"\n装置ステータス: {status_text(st)}")
        except TCP300IIError as e:
            print(f"\n(ステータス要求はスキップ: {e})")

        # --- 書き込み ---
        print("\n>> カードを挿入してください(書き込みます。最大30秒待ちます)...")
        try:
            wst = dev.write_track2(data, dataset_cmd=dataset_cmd, resp_timeout=30.0)
        except TCP300IIError as e:
            note += f" | write失敗: {e}"
            print(f"\n[書き込みエラー] {e}")
            print("→ このリーダー/カードでは書き込めない可能性。ログを確認してください。")
            return
        print(f"書き込みステータス: {status_text(wst)}")
        if wst != 0x20:
            note += f" | write status={status_text(wst)}"
            print("→ 正常に書き込めませんでした。")
            return
        print("書き込み成功(装置の自動ベリファイも通過)。")

        # --- 読み戻し ---
        print("\n>> 書いた内容を読み戻して照合します...")
        try:
            rst, rdata = dev.read_track2_fmt(read_fmt, resp_timeout=15.0)
        except TCP300IIError as e:
            # カードが排出済み等で読めない場合は再挿入を促して1回だけ再試行
            print(f"(読み戻しで例外: {e} → カードを入れ直して再試行します)")
            input("  カードを入れ直したら Enter を押してください...")
            rst, rdata = dev.read_track2_fmt(read_fmt, resp_timeout=30.0)

        print(f"読み戻しステータス: {status_text(rst)}")
        if rst == 0x20:
            print("読み戻した磁気データ:")
            dump(rdata)
            if rdata == data:
                print("\n==================================================")
                print("  ★★ 判定: 成功(書いた内容と完全一致)★★")
                print("  → このリーダーでカード書き込みができることを確認。")
                print("  → トキワ独自形式でのカード書き換え方式が成立します。")
                print("==================================================")
                note += " | RESULT=PASS"
            else:
                print("\n[不一致] 書いた内容と読み戻しが違います。")
                print(f"  書込: {data_str}")
                print(f"  読戻: {rdata.decode('ascii', 'replace')}")
                print("  → 書式(逆7bit/7bit)の選択が合っていない可能性。別書式でも試してください。")
                note += " | RESULT=MISMATCH"
        else:
            print("読み戻せませんでした(書式違い/カード種別違いの可能性)。")
            note += f" | read status={status_text(rst)}"
    finally:
        if dev is not None:
            eject_card(dev)
            save_log(dev, note)
            dev.close()

    print("\n完了。画面の判定結果(または card_write_test.log)を共有してください。")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    input("\nEnterキーで終了...")
