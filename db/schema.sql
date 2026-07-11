-- トキワ 宝飾店総合管理システム — SQLite スキーマ v1
-- docs/db-design.md の設計に基づく。列は後から ALTER TABLE ADD COLUMN で拡張する前提。
-- 変更は必ず db/migrations/ に追記し schema_migrations に記録する。

PRAGMA foreign_keys = ON;

-- ── マイグレーション管理 ──────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     INTEGER PRIMARY KEY,
  note        TEXT NOT NULL,
  applied_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ── マスター ──────────────────────────────
CREATE TABLE stores (
  store_code  TEXT PRIMARY KEY,
  name        TEXT NOT NULL
);

CREATE TABLE staff (
  staff_code  TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  store_code  TEXT REFERENCES stores(store_code),
  active      INTEGER NOT NULL DEFAULT 1
);

-- ── 顧客 ──────────────────────────────────
CREATE TABLE customers (
  customer_id   TEXT PRIMARY KEY,
  name          TEXT,
  kana          TEXT,
  tel           TEXT,
  tel2          TEXT,
  postal        TEXT,
  address       TEXT,
  gender        TEXT,
  birthday      TEXT,           -- YYYY-MM-DD
  wedding_day   TEXT,
  rank          TEXT,
  dm_ok         TEXT,
  email         TEXT,
  ring_size     TEXT,
  pierce        TEXT,
  staff_code    TEXT REFERENCES staff(staff_code),
  staff_name    TEXT,           -- 移行中の参照用。正式運用では staff_code に一本化
  store_code    TEXT REFERENCES stores(store_code),
  registered_at TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_customers_kana ON customers(kana);
CREATE INDEX idx_customers_tel  ON customers(tel);
CREATE INDEX idx_customers_name ON customers(name);

CREATE TABLE customer_families (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id  TEXT NOT NULL REFERENCES customers(customer_id),
  name         TEXT,
  relation     TEXT,
  gender       TEXT,
  birthday     TEXT
);
CREATE INDEX idx_families_cust ON customer_families(customer_id);

-- 顧客メモ01〜10 の固定列を1対多に置き換え
CREATE TABLE customer_memos (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id  TEXT NOT NULL REFERENCES customers(customer_id),
  seq          INTEGER,
  body         TEXT,
  updated_at   TEXT
);
CREATE INDEX idx_memos_cust ON customer_memos(customer_id);

-- ── 商品 ──────────────────────────────────
CREATE TABLE products (
  product_key   TEXT PRIMARY KEY,   -- 商品キー(現行の値を継承)
  product_no    TEXT,               -- 商品番号(スキャン用)
  name          TEXT,
  info          TEXT,
  category      TEXT,               -- 大分類名
  supplier      TEXT,
  cost_price    INTEGER,            -- 仕入単価
  list_price    INTEGER,            -- 上代価格
  state         TEXT,               -- 在庫/売上/受託/返品
  location      TEXT,               -- 保管場所
  center_stone  TEXT,
  center_carat  TEXT,
  color         TEXT,
  clarity       TEXT,
  cut           TEXT,
  cert_no       TEXT,               -- 鑑別書no
  is_glasses    INTEGER NOT NULL DEFAULT 0, -- メガネ商品フラグ(1=メガネ)
  registered_at TEXT
);
CREATE INDEX idx_products_no    ON products(product_no);
CREATE INDEX idx_products_state ON products(state);
CREATE INDEX idx_products_cat   ON products(category);

CREATE TABLE stock_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  product_key  TEXT NOT NULL REFERENCES products(product_key),
  event_type   TEXT NOT NULL,      -- 仕入/売上引落/返品/棚卸調整
  qty_delta    INTEGER NOT NULL,
  ref_slip_id  INTEGER,
  occurred_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_stock_product ON stock_events(product_key);

-- ── 売上(伝票ヘッダ + 明細)──────────────────
CREATE TABLE sales_slips (
  slip_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  slip_no       TEXT,              -- 伝票番号(現行値。空欄は移行時に採番)
  customer_id   TEXT REFERENCES customers(customer_id),
  staff_code    TEXT REFERENCES staff(staff_code),
  staff_name    TEXT,
  store_code    TEXT,
  sold_at       TEXT,              -- 販売日
  pay_method    TEXT,              -- 現金/掛売/クレジット/PayPay/分割…
  credit_kind   TEXT,
  motive        TEXT,              -- 購入動機
  place         TEXT,              -- 購入場所
  used_points   INTEGER DEFAULT 0,
  earned_points INTEGER DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_slips_cust ON sales_slips(customer_id);
CREATE INDEX idx_slips_date ON sales_slips(sold_at);

CREATE TABLE sale_lines (
  line_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  slip_id       INTEGER NOT NULL REFERENCES sales_slips(slip_id),
  product_key   TEXT REFERENCES products(product_key), -- 在庫品のみ。番号なし品はNULL
  free_name     TEXT,              -- 番号なし品(修理・電池・レンズ等)の品名
  info          TEXT,
  list_price    INTEGER,           -- 定価
  amount        INTEGER,           -- 買上金額(編集可)
  discount_rate REAL,              -- 割引率
  tax           INTEGER,
  spec_pending  INTEGER NOT NULL DEFAULT 0 -- 1=仕様未定(後日入力するレンズ等)
);
CREATE INDEX idx_lines_slip ON sale_lines(slip_id);

-- ── 売掛 ──────────────────────────────────
CREATE TABLE receivables (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
  product_key   TEXT,
  product_name  TEXT,
  bought_at     TEXT,
  down_payment  INTEGER DEFAULT 0,
  balance       INTEGER DEFAULT 0,
  last_paid_at  TEXT
);
CREATE INDEX idx_recv_cust ON receivables(customer_id);

CREATE TABLE receivable_entries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
  entry_type    TEXT,              -- 売掛発生/入金 など
  entry_date    TEXT,
  product_name  TEXT,
  amount        INTEGER,           -- 購入金額
  paid          INTEGER,           -- 入金・頭金
  note          TEXT
);
CREATE INDEX idx_recve_cust ON receivable_entries(customer_id);

-- ── ポイント(取引1本 + 残高キャッシュ)────────
CREATE TABLE point_transactions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
  tx_type       TEXT,              -- 加算/使用/失効/サービス/調整
  points        INTEGER,           -- 符号付き(加算+ / 使用-)
  add_points    INTEGER DEFAULT 0,
  use_points    INTEGER DEFAULT 0,
  balance       INTEGER,           -- 取引後残高(履歴の値をそのまま保持)
  product_name  TEXT,
  ref_slip_id   INTEGER,
  occurred_at   TEXT
);
CREATE INDEX idx_pt_cust ON point_transactions(customer_id);

-- 残高は point_transactions から集計可能だが、参照高速化のためキャッシュを持つ
CREATE TABLE point_balances (
  customer_id   TEXT PRIMARY KEY REFERENCES customers(customer_id),
  balance       INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT
);

-- ── アプローチ履歴(お声がけ)────────────────
CREATE TABLE approach_history (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
  approach_date TEXT,
  kind          TEXT,              -- 来店/DM/TEL/手紙 など
  title         TEXT,
  staff_name    TEXT,
  done          INTEGER NOT NULL DEFAULT 0 -- ホームの「お声がけ」チェックで更新
);
CREATE INDEX idx_ap_cust ON approach_history(customer_id);

-- ── メガネ処方箋 ──────────────────────────
CREATE TABLE prescriptions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
  rx_no         TEXT,
  purpose       TEXT,              -- 用途名称
  lens_name     TEXT,
  frame_name    TEXT,
  lens_key      TEXT,              -- 商品ID(レンズ)
  frame_key     TEXT,              -- 商品ID(フレーム)
  sph_r TEXT, sph_l TEXT, cyl_r TEXT, cyl_l TEXT,
  ax_r  TEXT, ax_l  TEXT, add_r TEXT, add_l TEXT,
  pd_far_r TEXT, pd_far_l TEXT, pd_far_both TEXT,
  pd_near_r TEXT, pd_near_l TEXT, pd_near_both TEXT,
  total_list  INTEGER,
  total_sell  INTEGER,
  handler     TEXT,               -- 対応者名
  rx_date     TEXT,
  jewelry_misassign INTEGER NOT NULL DEFAULT 0 -- 1=宝飾品が誤って紐づいている(要修正)
);
CREATE INDEX idx_rx_cust ON prescriptions(customer_id);

-- ── 運用系 ────────────────────────────────
-- オフライン時の未送信キュー(将来のクラウド同期用。単機運用では未使用)
CREATE TABLE sync_queue (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id    TEXT,
  op_type      TEXT,
  payload      TEXT,
  dedupe_key   TEXT UNIQUE,       -- 二重登録防止
  state        TEXT NOT NULL DEFAULT 'pending',
  created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE app_users (
  user_id      TEXT PRIMARY KEY,
  store_code   TEXT,
  display_name TEXT,
  role         TEXT NOT NULL DEFAULT 'staff', -- staff/manager/admin
  pass_hash    TEXT,
  active       INTEGER NOT NULL DEFAULT 1
);
