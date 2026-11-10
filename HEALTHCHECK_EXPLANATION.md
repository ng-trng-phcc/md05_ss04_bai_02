# Healthchecks, dependency readiness, and persistence

## Why startup order alone fails

Short-form `depends_on` orders container startup, not application readiness. A
running PostgreSQL container may still be initializing its database, and a
running Redis container may not yet accept commands. Container `running` and
healthcheck `healthy` are separate states.

## PostgreSQL healthcheck

Every 5 seconds, Compose's container healthcheck runs:

```text
pg_isready -h postgres -U admin -d storex_db
```

The timeout is 3 seconds, retries are 10, and start period is 10 seconds.
`-h postgres` tests TCP service access, avoiding the temporary Unix-socket-only
server used during first database initialization. `pg_isready` checks whether
the server accepts connections; it does not prove that credentials work or an
application query succeeds. The backend's real JDBC query verifies those
separately. A successful check during the start period can mark the service
healthy before that period ends; the period is not a fixed startup delay.

## Redis healthcheck

The check runs `redis-cli ping` with a 5-second interval, 3-second timeout,
10 retries, and a 5-second start period. Successful execution returns `PONG`.
The integration test also inspects the successful healthcheck output and calls
the backend's Redis PING endpoint using the actual Spring Redis connection.

## Long-form dependency gate

```yaml
depends_on:
  postgres:
    condition: service_healthy
  redis:
    condition: service_healthy
```

Compose waits for both dependencies' healthchecks before starting the backend.
This submission records timestamped Docker `health_status: healthy` and backend
`start` events on initial startup and after container recreation; final `ps`
output alone cannot prove sequencing. The fixture's startup runners also
execute real SQL and Redis PING and fail startup if either operation fails.

`depends_on` primarily handles initial sequencing. It does not continuously
gate requests, restart the backend automatically when a dependency becomes
unhealthy, or guarantee recovery after a later outage. Client reconnection,
application retry/error handling, and monitoring remain separate concerns.
These endpoints perform real operations each time and return HTTP 503 on
connection/query failure; their success is not a hardcoded readiness flag.

## Named PostgreSQL volume

The declared volume `postgres-data` is mounted at `/var/lib/postgresql/data`.
Compose scopes it to **`rikkei-ss04-storex02_postgres-data`**. It is independent
of container lifecycle and distinct from Exercise 01's volume.

`docker compose down` normally removes this project's containers and network,
but preserves the named volume. Subsequent `docker compose up -d` creates new
containers and remounts that same volume, retaining the PostgreSQL cluster and
rows. The persistence test inserts a dedicated marker once, reads it, runs
down/up, verifies a different PostgreSQL container ID, verifies unchanged volume
metadata, then reads the same marker without reinserting it.

**Do not use `docker compose down -v` for this test.** The `-v` flag removes
declared named volumes, deleting the storage that the test must preserve.
Redis is an ephemeral cache here (`/data` tmpfs); Redis durability is outside the
assignment's persistence requirement. No database/cache host ports are needed:
the backend reaches `postgres:5432` and `redis:6379` via Compose DNS.
