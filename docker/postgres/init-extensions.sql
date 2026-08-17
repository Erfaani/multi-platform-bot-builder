-- Extensions required by the schema. Applied once at cluster initialization.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";      -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS "btree_gist";  -- appointment double-booking exclusion constraint
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- search
CREATE EXTENSION IF NOT EXISTS "vector";      -- AI knowledge base embeddings
