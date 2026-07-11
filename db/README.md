# トキワ データベース

SQLite で構築するトキワのDB。`db/tokiwa.db` は再生成できるため Git 管理外。

## ファイル

- `schema.sql` … テーブル定義(DDL)。スキーマの正
- `migrations/` … v2以降のスキーマ変更を追記(ALTER TABLE 等)
- `tokiwa.db` … 生成物(gitignore)

## 使い方

```bash
# デモデータ(data/demo/*.xlsx)から tokiwa.db を再構築
python3 scripts/import_to_sqlite.py
```

再実行すると tokiwa.db を作り直す(冪等)。

## 項目を後から増やすとき

1. `db/migrations/00X_説明.sql` を作り `ALTER TABLE ... ADD COLUMN ...` を書く
2. 末尾に `INSERT INTO schema_migrations(version,note) VALUES (X,'説明');`
3. アプリ起動時に schema_migrations の最大versionと比較し、未適用分だけ実行

既存データは保持されるため、運用開始後でも安全に列を追加できる。

## 設計方針

`docs/db-design.md` を参照。要点:
- 名前のコピーを持たず ID 参照に正規化
- 売上は伝票ヘッダ(sales_slips)+明細(sale_lines)の2階層
- ポイントは取引1本(point_transactions)、残高はキャッシュ
- メモ・家族などの固定枠列は子テーブル化
