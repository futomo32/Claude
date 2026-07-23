#!/usr/bin/env python3
"""tokiwa.db のバックアップを取る(タイムスタンプ付き)。正式運用の締め・移行前などに実行。

  python3 scripts/backup_db.py            # db/backups/ に tokiwa_YYYYMMDD_HHMMSS.db を作成
  python3 scripts/backup_db.py /path/dir  # 保存先を指定

WALモードのままコピーすると取りこぼす恐れがあるため、sqlite3 のオンラインバックアップAPIで
一貫性のあるコピーを作る(サーバー起動中でも安全)。古いバックアップは自動削除しない。
"""
import os, sqlite3, sys, datetime

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")


def main():
    if not os.path.exists(DB):
        print(f"[エラー] DBがありません: {DB}")
        sys.exit(1)
    dest_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "db", "backups")
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(dest_dir, f"tokiwa_{stamp}.db")

    src = sqlite3.connect(DB)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)   # オンラインバックアップ(WALも整合)
    dst.close()
    src.close()

    size_mb = os.path.getsize(dest) / (1024 * 1024)
    print(f"バックアップ作成: {os.path.abspath(dest)} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
