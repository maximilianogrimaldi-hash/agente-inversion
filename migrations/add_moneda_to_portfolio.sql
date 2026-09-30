-- Migración: agregar columna moneda a la tabla portfolio
-- Ejecutar en Supabase SQL Editor o en la consola de Railway
-- Fecha: 2026-09

ALTER TABLE portfolio
  ADD COLUMN IF NOT EXISTS moneda TEXT NOT NULL DEFAULT 'ARS';

-- Verificar
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'portfolio' AND column_name = 'moneda';
