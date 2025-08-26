-- Add created_at on checkout_cart and ensure one cart per user.
-- Safe to run multiple times.

ALTER TABLE IF EXISTS checkout_cart
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

-- Guarantee one cart per user (works even if it already exists)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'uq_checkout_cart_user'
      AND conrelid = 'checkout_cart'::regclass
  ) THEN
    ALTER TABLE checkout_cart
      ADD CONSTRAINT uq_checkout_cart_user UNIQUE (user_id);
  END IF;
END $$;

-- Optional but nice: index for ORDER BY created_at
CREATE INDEX IF NOT EXISTS idx_checkout_cart_created_at
  ON checkout_cart(created_at DESC);
