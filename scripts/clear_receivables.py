#!/usr/bin/env python3
"""売掛(未回収残高)を全件クリアするメンテナンス用スクリプト。

初期運用を空で始め、正式運用時に紙媒体の売掛を「＋売掛を追加」で手入力していく運用向け。
実行前に db/tokiwa.db のバックアップ(タイムスタンプ付き)を自動で取る。取り消せない操作のため
既定では確認プロンプトを出す(--yes で省略可)。

  python3 scripts/clear_receivables.py            # 売掛残高(receivables)のみクリア
  python3 scripts/clear_receivables.py --with-history  # 入金履歴(receivable_entries)も一緒に消す
  python3 scripts/clear_receivables.py --yes      # 確認を省略(バックアップは必ず取る)

※再取込(import_csv.py)すると宝飾ナビの d_kakeuri から売掛が復活する。恒久的に空で始めるなら
  取込時に `python3 scripts/import_csv.py --no-receivables` を使うのが確実。
"""
import os, shutil, sqlite3, sys, datetime

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")


def main():
    args = sys.argv[1:]
    with_history = "--with-history" in args
    assume_yes = "--yes" in args

    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        sys.exit(1)

    con = sqlite3.connect(DB)
    n_recv = con.execute("SELECT COUNT(*) FROM receivables").fetchone()[0]
    n_bal = con.execute("SELECT COUNT(*) FROM receivables WHERE COALESCE(balance,0) > 0").fetchone()[0]
    try:
        n_hist = con.execute("SELECT COUNT(*) FROM receivable_entries").fetchone()[0]
    except sqlite3.Error:
        n_hist = 0
    con.close()

    print("=== 売掛クリア ===")
    print(f"  対象DB          : {os.path.abspath(DB)}")
    print(f"  売掛(receivables): {n_recv}件(うち残高あり {n_bal}件)")
    print(f"  入金履歴         : {n_hist}件  {'← これも消す(--with-history)' if with_history else '← 残す'}")
    print()

    if not assume_yes:
        ans = input("この内容でクリアします。よろしいですか? (yes/no): ").strip().lower()
        if ans not in ("y", "yes"):
            print("中止しました。")
            return

    # 必ずバックアップを取る
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB + f".bak_{stamp}"
    shutil.copy2(DB, backup)
    print(f"バックアップを作成: {os.path.abspath(backup)}")

    con = sqlite3.connect(DB)
    con.execute("DELETE FROM receivables")
    if with_history:
        con.execute("DELETE FROM receivable_entries")
    con.commit()
    con.execute("VACUUM")
    con.close()

    print("完了: 売掛残高をクリアしました" + ("(入金履歴も削除)" if with_history else "(入金履歴は保持)") + "。")
    print("元に戻すには、上のバックアップファイルを db/tokiwa.db に戻してください。")


if __name__ == "__main__":
    main()
