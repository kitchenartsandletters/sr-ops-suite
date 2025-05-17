-- 001_add_order_date.sql

BEGIN;

-- Add a timestamp column to record when the order was placed
ALTER TABLE order_line_backorders
ADD COLUMN order_date TIMESTAMPTZ;

-- (Optional) If you want to query by order date quickly, add an index:
CREATE INDEX idx_order_line_backorders_order_date
  ON order_line_backorders (order_date);

COMMIT;