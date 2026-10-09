-- Least-privilege database user for the app (third safety layer).
-- Run as the admin user, passing the new password as a psql variable:
--   psql -d northwind -v reader_password='<long random password>' -f sql/readonly_role.sql
-- Then point DATABASE_URL at agent_reader instead of the admin user.

CREATE ROLE agent_reader LOGIN PASSWORD :'reader_password' CONNECTION LIMIT 10;

GRANT CONNECT ON DATABASE northwind TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;

-- Even a session opened by this user cannot write or run for long.
ALTER ROLE agent_reader SET default_transaction_read_only = on;
ALTER ROLE agent_reader SET statement_timeout = '5s';
