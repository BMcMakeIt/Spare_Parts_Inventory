-- Run after tables are created
\set ON_ERROR_STOP on

CREATE INDEX IF NOT EXISTS idx_inventory_part_no     ON inventory(part_no);
CREATE INDEX IF NOT EXISTS idx_ledger_event_time     ON ledger(event_time);
CREATE INDEX IF NOT EXISTS idx_ledger_part_no        ON ledger(part_no);
CREATE INDEX IF NOT EXISTS idx_ledger_work_order     ON ledger(work_order_no);
