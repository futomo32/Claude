#!/usr/bin/env python3
"""tokiwa.db のバックアップを取る(店内+店外・世代管理・整合性チェック)。

  python3 scripts/backup_db.py            # 設定(画面で指定した店外保存先・世代数)に従って実行
  python3 scripts/backup_db.py /path/dir  # 店外保存先をこの1か所に上書きして実行

実処理は server/backup.py。オンラインバックアップAPIを使うのでサーバー起動中(営業中)でも
安全に取れる。コピー後に整合性チェックを行い、壊れていたら採用しない。
店内(db/backups)には常に保存し、追加で設定の保存先(外付けHDD・クラウド同期フォルダ)へ複製する。

Windowsのタスクスケジューラに登録して閉店後に自動実行する場合は「バックアップ.bat」を使う。
運用手順と復元手順は docs/backup.md。
"""
import os
import sqlite3
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(BASE, "server"))

import backup  # noqa: E402
import db_query  # noqa: E402


def main():
    db = os.path.join(BASE, "db", "tokiwa.db")
    if not os.path.exists(db):
        print(f"[エラー] DBがありません: {db}")
        sys.exit(1)

    # 保存先と世代数は画面の設定(app_settings)を使う。引数があればそれを店外保存先にする
    extra, keep = [], backup.KEEP_DEFAULT
    try:
        con = sqlite3.connect(db)
        try:
            st = db_query.backup_settings(con)
        finally:
            con.close()
        extra = [d.strip() for d in str(st.get("backup_dirs") or "").splitlines() if d.strip()]
        keep = st.get("backup_keep") or backup.KEEP_DEFAULT
    except Exception as e:  # noqa: BLE001 設定が読めなくてもバックアップ自体は取る
        print(f"[注意] 設定を読めませんでした({e})。既定値で実行します。")

    if len(sys.argv) > 1:
        extra = [sys.argv[1]]

    result = backup.run_backup(db, extra, keep)
    print("バックアップ: " + backup.summary(result))
    for p in result["saved"]:
        print(f"  保存: {os.path.abspath(p)}")
    for p in result["removed"]:
        print(f"  世代削除: {os.path.abspath(p)}")
    if not extra:
        print("  ※店外の保存先が未設定です。設定→バックアップ で外付けHDD等を指定してください"
              "(火災・盗難・PC故障で店内の控えごと失います)。")

    # 実行結果を画面の「最終バックアップ」に反映する
    try:
        con = sqlite3.connect(db)
        try:
            db_query.record_backup_result(con, result["at"], backup.summary(result))
        finally:
            con.close()
    except Exception:  # noqa: BLE001 記録できなくてもバックアップは成立している
        pass

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
