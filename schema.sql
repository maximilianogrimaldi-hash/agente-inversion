-- AGENTE DE INVERSION - Schema Supabase
-- Ejecutar en: Supabase > SQL Editor

CREATE TABLE IF NOT EXISTS watchlist (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('CEDEAR', 'CRYPTO')),
    notas       TEXT DEFAULT '',
    activo      BOOLEAN DEFAULT TRUE,
    creado_en   TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist (ticker);
CREATE INDEX IF NOT EXISTS idx_watchlist_tipo ON watchlist (tipo);
CREATE INDEX IF NOT EXISTS idx_watchlist_activo ON watchlist (activo);

CREATE TABLE IF NOT EXISTS alertas (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    tipo            TEXT NOT NULL,
    precio          NUMERIC,
    variacion_pct   NUMERIC,
    senal           TEXT NOT NULL CHECK (senal IN ('BUY', 'SELL', 'WATCH', 'NEUTRAL')),
    fuerza          TEXT NOT NULL CHECK (fuerza IN ('FUERTE', 'MODERADA', 'DEBIL')),
    motivos         JSONB DEFAULT '[]',
    indicadores     JSONB DEFAULT '{}',
    creado_en       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alertas_ticker ON alertas (ticker);
CREATE INDEX IF NOT EXISTS idx_alertas_creado_en ON alertas (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_senal ON alertas (senal);

CREATE TABLE IF NOT EXISTS config (
    id          BIGSERIAL PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,
    value       TEXT NOT NULL,
    creado_en   TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO watchlist (ticker, tipo, notas) VALUES
    ('AAPL',  'CEDEAR', 'Apple'),
    ('GOOGL', 'CEDEAR', 'Alphabet'),
    ('MSFT',  'CEDEAR', 'Microsoft'),
    ('AMZN',  'CEDEAR', 'Amazon'),
    ('TSLA',  'CEDEAR', 'Tesla'),
    ('NVDA',  'CEDEAR', 'NVIDIA'),
    ('META',  'CEDEAR', 'Meta'),
    ('BRK',   'CEDEAR', 'Berkshire Hathaway'),
    ('BTCUSDT',  'CRYPTO', 'Bitcoin'),
    ('ETHUSDT',  'CRYPTO', 'Ethereum'),
    ('SOLUSDT',  'CRYPTO', 'Solana'),
    ('BNBUSDT',  'CRYPTO', 'BNB'),
    ('XRPUSDT',  'CRYPTO', 'XRP'),
    ('ADAUSDT',  'CRYPTO', 'Cardano')
ON CONFLICT (ticker) DO NOTHING;

INSERT INTO config (key, value) VALUES
    ('rsi_oversold',       '30'),
    ('rsi_overbought',     '70'),
    ('price_change_alert', '3.0'),
    ('volume_spike_mult',  '2.0'),
    ('interval_minutes',   '15'),
    ('dedup_minutes',      '60')
ON CONFLICT (key) DO NOTHING;

ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE alertas   ENABLE ROW LEVEL SECURITY;
ALTER TABLE config    ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON watchlist
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON alertas
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON config
    FOR ALL USING (auth.role() = 'service_role');
