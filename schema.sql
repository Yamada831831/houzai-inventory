-- 1. 包材マスタ（袋・表シール・裏シール）
CREATE TABLE materials (
  id SERIAL PRIMARY KEY,
  type TEXT NOT NULL, -- 袋 / 表シール / 裏シール
  name TEXT NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 半完成品マスタ（表シール＋袋＋閾値）
CREATE TABLE semi_products (
  id SERIAL PRIMARY KEY,
  label_material_id INTEGER NOT NULL REFERENCES materials(id),
  bag_material_id INTEGER NOT NULL REFERENCES materials(id),
  threshold INTEGER NOT NULL,
  replenish_quantity INTEGER NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. 完成品マスタ（裏シール＋半完との紐付け）
CREATE TABLE finished_products (
  id SERIAL PRIMARY KEY,
  destination TEXT NOT NULL,
  product_name TEXT NOT NULL,
  size TEXT NOT NULL,
  origin TEXT NOT NULL,
  seal_material_id INTEGER NOT NULL REFERENCES materials(id),
  semi_product_id INTEGER NOT NULL REFERENCES semi_products(id),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. 作業者マスタ
CREATE TABLE workers (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  note TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. 作業予定テーブル
CREATE TABLE work_schedules (
  id SERIAL PRIMARY KEY,
  product_type TEXT NOT NULL,  -- 'finished' or 'semi'
  product_id INTEGER NOT NULL,
  worker_id INTEGER REFERENCES workers(id),
  quantity INTEGER NOT NULL,
  comment TEXT,
  status TEXT NOT NULL DEFAULT '予定',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. 作業完了ログ
CREATE TABLE work_logs (
  id SERIAL PRIMARY KEY,
  schedule_id INTEGER REFERENCES work_schedules(id),
  product_type TEXT NOT NULL,
  product_id INTEGER NOT NULL,
  worker_id INTEGER REFERENCES workers(id),
  quantity INTEGER NOT NULL,
  comment TEXT,
  completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. 出荷予定データ
CREATE TABLE shipments (
  id SERIAL PRIMARY KEY,
  shipment_date DATE NOT NULL,
  destination TEXT NOT NULL,
  product_name TEXT NOT NULL,
  size TEXT NOT NULL,
  origin TEXT NOT NULL,
  packaging_type TEXT,
  quantity INTEGER NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. 蔵出しログ（戻し含む）
CREATE TABLE dispatch_logs (
  id SERIAL PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES finished_products(id),
  quantity INTEGER NOT NULL,
  is_return BOOLEAN DEFAULT FALSE,
  comment TEXT,
  dispatched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. 棚卸
CREATE TABLE stock_adjust_logs (
  id SERIAL PRIMARY KEY,
  item_type TEXT NOT NULL,          -- material / semi / finished
  item_id INTEGER NOT NULL,
  old_stock INTEGER NOT NULL,
  new_stock INTEGER NOT NULL,
  diff INTEGER NOT NULL,
  comment TEXT,
  adjusted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

