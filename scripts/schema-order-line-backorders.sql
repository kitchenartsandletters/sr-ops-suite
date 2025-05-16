-- scripts/schema-order-line-backorders.sql
CREATE TABLE IF NOT EXISTS order_line_backorders (
  order_id            TEXT        NOT NULL,
  line_item_id        TEXT        NOT NULL,
  variant_id          TEXT        NOT NULL,
  ordered_qty         INTEGER     NOT NULL,
  initial_available   INTEGER     NOT NULL,
  initial_backordered INTEGER     NOT NULL,
  snapshot_ts         TIMESTAMP   NOT NULL DEFAULT NOW(),
  status              TEXT        NOT NULL DEFAULT 'open',
  override_flag       BOOLEAN     NOT NULL DEFAULT FALSE,
  override_reason     TEXT,
  override_ts         TIMESTAMP,
  PRIMARY KEY (order_id, line_item_id)
);