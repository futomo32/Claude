# -*- coding: utf-8 -*-
"""トキワ DBバックアップ(世代管理・複数保存先・整合性チェック)。

データ消失対策はトキワを作った元々の動機であり、正式運用開始の絶対条件。
docs/backup.md に運用手順と復元手順をまとめている。

方針:
- sqlite3 のオンラインバックアップAPIでコピーする。WALモードのままファイルを
  コピーすると取りこぼす恐れがあるが、この方式ならサーバー起動中(営業中)でも
  一貫性のあるコピーが取れる。
- コピー直後に PRAGMA integrity_check を実行し、壊れていないことを確認してから採用する
  (壊れたバックアップを「取れているつもり」で放置するのが最悪のパターンのため)。
- 保存先は複数指定できる。店内(db/backups)は常に取り、追加で店外(外付けHDD・
  クラウド同期フォルダ)にも複製する。火災・盗難・PC故障で店内の複製ごと失うのを防ぐ。
- 世代管理: 保存先ごとに新しい順に keep 個だけ残す。1世代だけの運用は、DBが壊れた状態や
  ランサムウェアで暗号化された状態を上書きしてしまうと復旧不能になるため危険。

★安全策: 削除するのは自分が作った命名規則(tokiwa_YYYYMMDD_HHMMSS.db)に一致する
  ファイルだけ。ユーザーが保存先に指定したフォルダの他のファイルには絶対に触らない。
"""
import datetime
import glob
import os
import shutil
import sqlite3

BASE = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(BASE, "db", "tokiwa.db")
LOCAL_DIR = os.path.join(BASE, "db", "backups")   # 店内の既定保存先(常にここにも取る)
PREFIX = "tokiwa_"
SUFFIX = ".db"
KEEP_DEFAULT = 14


def _stamp(now=None):
    return (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")


def _name(stamp):
    return f"{PREFIX}{stamp}{SUFFIX}"


def _mine(path):
    """自分が作ったバックアップファイルか(世代削除の対象にしてよいか)。"""
    b = os.path.basename(path)
    return b.startswith(PREFIX) and b.endswith(SUFFIX)


def list_backups(dirs):
    """保存先ごとのバックアップ一覧。[{dir, files:[{name,size,at}], error}] を返す。"""
    out = []
    for d in dirs:
        item = {"dir": d, "files": [], "error": ""}
        try:
            paths = [p for p in glob.glob(os.path.join(d, PREFIX + "*" + SUFFIX)) if _mine(p)]
            for p in sorted(paths, reverse=True):
                st = os.stat(p)
                item["files"].append({
                    "name": os.path.basename(p),
                    "size": st.st_size,
                    "at": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        except OSError as e:
            item["error"] = str(e)   # 外付けHDDが繋がっていない等
        out.append(item)
    return out


def _integrity_ok(path):
    """コピーしたDBが壊れていないか確認する。"""
    try:
        con = sqlite3.connect(path)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
        finally:
            con.close()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False


def prune(directory, keep=KEEP_DEFAULT):
    """保存先の古いバックアップを削除し、削除したファイル名のリストを返す。
    自分の命名規則に一致するファイルだけを対象にする(他のファイルは触らない)。"""
    keep = max(1, int(keep or KEEP_DEFAULT))
    removed = []
    try:
        paths = [p for p in glob.glob(os.path.join(directory, PREFIX + "*" + SUFFIX)) if _mine(p)]
    except OSError:
        return removed
    for p in sorted(paths, reverse=True)[keep:]:   # 名前が時刻順なので新しい順に keep 個残す
        try:
            os.remove(p)
            removed.append(os.path.basename(p))
        except OSError:
            pass   # 使用中・権限なし等。次回に回す(バックアップ自体は失敗させない)
    return removed


def run_backup(db_path=None, extra_dirs=(), keep=KEEP_DEFAULT):
    """バックアップを実行する。戻り値の dict を画面とログにそのまま出せる形にする。

    手順: (1)店内 db/backups へオンラインバックアップ → (2)整合性チェック →
    (3)追加の保存先(店外)へ複製 → (4)保存先ごとに世代削除。

    店内へのコピーが失敗した場合のみ ok=False。店外の一部が失敗しても
    ok=True + errors に理由を入れる(外付けHDD未接続でも店内の控えは残るため)。
    """
    db_path = db_path or DB
    now = datetime.datetime.now()
    stamp = _stamp(now)
    result = {"ok": False, "at": now.strftime("%Y-%m-%d %H:%M:%S"), "name": _name(stamp),
              "size": 0, "saved": [], "removed": [], "errors": []}
    if not os.path.exists(db_path):
        result["errors"].append(f"DBがありません: {db_path}")
        return result

    # (1) 店内へオンラインバックアップ(営業中・サーバー起動中でも安全)
    local = os.path.join(LOCAL_DIR, _name(stamp))
    try:
        os.makedirs(LOCAL_DIR, exist_ok=True)
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(local)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except (sqlite3.Error, OSError) as e:
        result["errors"].append(f"バックアップの作成に失敗: {e}")
        return result

    # (2) 壊れたバックアップを採用しない(取れているつもりを防ぐ)
    if not _integrity_ok(local):
        result["errors"].append("作成したバックアップの整合性チェックに失敗しました(破棄しました)")
        try:
            os.remove(local)
        except OSError:
            pass
        return result

    result["ok"] = True
    result["size"] = os.path.getsize(local)
    result["saved"].append(local)

    # (3) 店外へ複製(外付けHDD・クラウド同期フォルダ)。失敗しても店内の控えは残す
    for d in extra_dirs:
        d = str(d).strip()
        if not d or os.path.abspath(d) == os.path.abspath(LOCAL_DIR):
            continue
        try:
            os.makedirs(d, exist_ok=True)
            shutil.copy2(local, os.path.join(d, _name(stamp)))
            result["saved"].append(os.path.join(d, _name(stamp)))
        except OSError as e:
            result["errors"].append(f"{d} へ複製できませんでした: {e}")

    # (4) 世代削除(保存先ごと)
    for d in [LOCAL_DIR] + [str(x).strip() for x in extra_dirs if str(x).strip()]:
        for name in prune(d, keep):
            result["removed"].append(os.path.join(d, name))
    return result


def summary(result):
    """人が読む1行メッセージ(画面表示・コンソール出力の共通表記)。"""
    if not result.get("ok"):
        return "失敗: " + ("・".join(result.get("errors")) or "原因不明")
    mb = result.get("size", 0) / (1024 * 1024)
    msg = f"成功 {result['name']}({mb:.1f}MB)・保存先{len(result.get('saved', []))}か所"
    if result.get("errors"):
        msg += " ※一部の保存先に失敗: " + "・".join(result["errors"])
    return msg
