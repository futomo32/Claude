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
import integrity  # noqa: E402


def main():
    db = os.path.join(BASE, "db", "tokiwa.db")
    if not os.path.exists(db):
        print(f"[エラー] DBがありません: {db}")
        sys.exit(1)

    # 保存先・世代数は画面の設定(app_settings)を使い、件数の記録と結果の記録も行う。
    # 引数があればその1か所を店外保存先として上書きする(設定より優先)。
    if len(sys.argv) > 1:
        con = sqlite3.connect(db)
        try:
            db_query.save_backup_settings(con, dict(db_query.backup_settings(con),
                                                    backup_dirs=sys.argv[1]))
        finally:
            con.close()
        print(f"店外保存先を引数で指定: {sys.argv[1]}")

    con = sqlite3.connect(db)
    try:
        result = backup.run_with_history(db, con, "コマンド")
        st = db_query.backup_settings(con)
    finally:
        con.close()

    print("バックアップ: " + result["message"])
    for p in result["saved"]:
        print(f"  保存: {os.path.abspath(p)}")
    for p in result["removed"]:
        print(f"  世代削除: {os.path.abspath(p)}")
    for w in result.get("count_warnings", []):
        print(f"  ⚠ {w} ← 誤削除・取り込み事故の可能性。控えを確認してください")
    if not str(st.get("backup_dirs") or "").strip():
        print("  ※店外の保存先が未設定です。設定→バックアップ で外付けHDDやOneDrive等を指定してください"
              "(火災・盗難・PC故障で店内の控えごと失います)。")

    # 続けてデータ点検も実行する(破損・参照切れ・残高と履歴の矛盾)
    con = sqlite3.connect(db)
    try:
        ig = integrity.run_and_record(db, con)
    finally:
        con.close()
    print("データ点検: " + ig["summary"])
    for c in ig["checks"]:
        if c["count"] != 0:
            mark = "✕" if c["level"] == "error" else "⚠"
            print(f"  {mark} {c['name']}: " +
                  ("点検できず" if c["count"] < 0 else f"{c['count']:,}件") +
                  (f" — {c['detail']}" if c["detail"] else ""))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
