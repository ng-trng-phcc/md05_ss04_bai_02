# Session 04 / Exercise 02 — StoreX Healthchecks and Persistence

This repository extends the authorized minimal Spring Boot fixture from
[Exercise 01](https://github.com/ng-trng-phcc/md05_ss04_bai_01). The original
StoreX backend v2 source/image was not provided. This is a functional
demonstration of real PostgreSQL/Redis connectivity, dependency readiness, and
PostgreSQL persistence, not the original StoreX business application.

## Architecture

- Project: `rikkei-ss04-storex02`, separate from Exercise 01.
- Backend: `storex-backend:v2`, Java 21, Spring Boot 3.5.16, JDBC/HikariCP,
  Spring Data Redis/Lettuce, Web, and Actuator. Host mapping `8080:8080`.
- PostgreSQL: `postgres:13`, database `storex_db`, user/password `admin`/`admin`.
  These are the assignment's fixed lab values, not personal credentials.
- JDBC: `jdbc:postgresql://postgres:5432/storex_db`.
- Redis: `redis:alpine`, host `redis`, port `6379`.
- Both dependencies have healthchecks, and backend requires `service_healthy`
  for both. No PostgreSQL or Redis ports are published to the host.
- Named PostgreSQL volume: `rikkei-ss04-storex02_postgres-data` mounted at
  `/var/lib/postgresql/data`. Redis `/data` uses ephemeral tmpfs so recreating
  the cache does not leave anonymous volumes.

Short-form `depends_on` only orders startup. A running container may not be ready
for commands. Long-form `service_healthy` waits for checks to pass; it does not
guarantee automatic recovery after a later dependency failure. See
[HEALTHCHECK_EXPLANATION.md](HEALTHCHECK_EXPLANATION.md) for mechanisms and limits.

## Reproducible build and run

Requires Docker/Compose, internet access to registries/Maven Central, and a free
host port 8080. The multi-stage build uses Maven 3.9.11 and Java 21; base images
are pinned by digest, dependencies by the Spring Boot parent, and the JAR
timestamp is fixed. Required database/cache tags remain mutable; record their
resolved image digests when comparing runs. No local Maven install is needed.

Exercise 01 was stopped with explicit user authorization to free port 8080;
its repository, containers, and named database volume were preserved.

```bash
ss -ltnp '( sport = :8080 )'
docker build -t storex-backend:v2 .
docker image inspect storex-backend:v2
docker compose config -q
docker compose config
docker compose up -d
docker compose ps
docker compose logs --tail 50 postgres
docker compose logs --tail 50 redis
docker compose logs --tail 50 backend
```

The backend uses `pull_policy: never`; build the local image before startup.

## Real dependency verification

```bash
curl -i http://localhost:8080/db-check
curl -i http://localhost:8080/redis-check
curl -i http://localhost:8080/actuator/health
docker compose exec -T postgres pg_isready -h postgres -U admin -d storex_db
docker compose exec -T redis redis-cli ping
```

`/db-check` executes `SELECT 1`, `current_database()`, and database server
address/port through the configured JdbcTemplate. `/redis-check` executes Redis
PING through StringRedisTemplate and verifies the actual returned `PONG`.
Every request performs the operation again; failed operations return HTTP 503
without exposing credentials. Startup runners perform both operations too.

## Persistence acceptance test

The reproducible test driver records health/start events, inserts a dedicated
marker once, and performs this project's down/up cycle without `-v`:

```bash
python3 scripts/verify-runtime.py --output-dir /tmp/opencode/storex02-run
```

Run the driver on the built, stopped/new project; it deliberately recreates
only `rikkei-ss04-storex02`. A repeated run retains existing markers and inserts
a new run-unique marker. Raw events, command output, and results are written to
the chosen external directory, not committed as generated build artifacts.

Manual outline:

1. Wait for PostgreSQL healthy, create the dedicated `ss04_bai02_persistence`
   table, insert one unique `SS04_BAI02_PERSISTENCE_TEST_...` marker, and read it.
2. Record PostgreSQL container ID and named volume metadata.
3. Run `docker compose down` **without `-v`**.
4. Verify the named volume remains, then run `docker compose up -d`.
5. Wait for dependency health and actual backend connectivity.
6. Verify the PostgreSQL container ID changed, volume metadata is unchanged,
   and the exact marker/row is still present. Do not reinsert it after restart.

Never delete database volumes or use global Docker cleanup commands. Keep the
verified stack running; `docker compose stop` can stop it later without deletion.

## Observed results and evidence

Executed on **2026-11-11 (UTC+07:00)**, NixOS 26.11, Docker Engine 29.5.3,
Compose 5.1.4. Container/event/HTTP times below are UTC. Observed results:

| Acceptance check | Result |
|---|---|
| Build | Maven `BUILD SUCCESS`; `storex-backend:v2` inspected; Temurin 21.0.13 runtime |
| Static Compose validation | `docker compose config -q` passed; effective JSON assertions passed |
| PostgreSQL | PostgreSQL 13.23, healthy; `storex_db` exists; TCP `pg_isready` accepts connections |
| Redis | Redis 8.10.3, healthy; healthcheck output and direct PING both returned `PONG` |
| Backend | Running on required host port 8080, zero restarts, successful SQL and Redis startup probes |
| SQL endpoint, before and after recreation | HTTP 200; `queryResult=1`, `database=storex_db`, real SQL server address matched the Compose database |
| Redis endpoint, before and after recreation | HTTP 200; `pingExecuted=true`, `response=PONG` from Spring Redis connection |
| Actuator | HTTP 200; database and Redis health indicators both `UP` |
| Logs | Actual `DB_CHECK SUCCESS` and `REDIS_CHECK SUCCESS`; no backend connection errors in either cycle |
| Startup ordering | Docker events proved both dependency health events preceded backend start in both cycles |
| Persistence | Exact marker and original row timestamp survived `down`/`up`; no reinsertion |
| Container recreation | PostgreSQL ID changed; all project containers were removed during down |
| Volume | Same named volume, CreatedAt, labels, and mountpoint after down and after up |
| Isolation | No database/cache host publishing; Exercise 01 stayed stopped with files/containers/volume preserved |

### Timestamped startup ordering

These are recorded Docker events, not inference from final service status:

| Cycle | PostgreSQL healthy (UTC) | Redis healthy (UTC) | Backend start (UTC) |
|---|---|---|---|
| Initial | `18:39:55.528978` | `18:39:55.494795` | `18:39:56.203945` |
| After down/up | `18:40:10.044033` | `18:40:10.051220` | `18:40:10.733479` |

All events occurred on **2026-11-10 UTC** (2026-11-11 local time). The driver
asserted ordering using the original nanosecond timestamps. Raw events and
results are also attached to the Release for auditability.

### Persistence record

Inserted exactly once before down, and queried again after up:

```text
marker:     SS04_BAI02_PERSISTENCE_TEST_3f397521db9d473e93a7da8342c3dd2a
created_at: 2026-11-10 18:40:02.771668+00
before row = after row

PostgreSQL container BEFORE:
730fb69b93df0addc0845debc7f969b523cf1d3fa0a18f82c86d19cf7312de1e
PostgreSQL container AFTER:
27bb7b655bb742235a8e1041e180dd018145557b09602b02f24c5a098acc0c49

Volume:    rikkei-ss04-storex02_postgres-data
CreatedAt: 2026-11-11T01:39:50+07:00 (unchanged)
Mount:     /var/lib/postgresql/data
```

After recreation SQL observed `172.25.0.2/32:5432`; before recreation it observed
`172.25.0.3/32:5432`. These are measured dynamic addresses, never hardcoded in
configuration. Service-name DNS remained valid after address changes.

Resolved images used for this run:

```text
storex-backend:v2  sha256:12f3c38bb4f77d167adabd98f835a581206588076c28d923c4934183859c61c5
postgres:13        sha256:4689940c683801b4ab839ab3b0a0a3555a5fe425371422310944e89eca7d8068
redis:alpine       sha256:71885d8cc6e42f2bc0aa2eb853bfc4be200b5108a46ac50e117ae1df0531fb80
```

### Authentic evidence

Unmodified 2560×1440 PNGs were captured from real Foot terminals under Hyprland
using grim. PNG integrity and OCR checks passed. The current session cannot
visually inspect image attachments; OCR confirmed the required captured content.
Screenshots are Release assets, not committed build artifacts:

- [Release ss04-bai-02](https://github.com/ng-trng-phcc/md05_ss04_bai_02/releases/tag/ss04-bai-02)
- [evidence_02.png](https://github.com/ng-trng-phcc/md05_ss04_bai_02/releases/download/ss04-bai-02/evidence_02.png):
  healthy dependencies, running backend, real SQL/Redis responses, success logs,
  and a live SELECT of the persisted marker.
- [evidence_02_persistence.png](https://github.com/ng-trng-phcc/md05_ss04_bai_02/releases/download/ss04-bai-02/evidence_02_persistence.png):
  clearly labeled recorded before/after results, current container/volume/row,
  and recorded dependency/start event ordering.
- [results.json](https://github.com/ng-trng-phcc/md05_ss04_bai_02/releases/download/ss04-bai-02/results.json)
  and [docker-events.jsonl](https://github.com/ng-trng-phcc/md05_ss04_bai_02/releases/download/ss04-bai-02/docker-events.jsonl):
  actual integration results and raw project-scoped Docker events.

SHA-256:

```text
e09c2c8236376cb441962e366e2bca02096f36f2a92146b0bae1a54bf62d2133  evidence_02.png
00cf19640acfcd7740d6682ce53484f4ef339c6458979e5d3bd7f7798e3fbcf0  evidence_02_persistence.png
```

### Resource preservation

The authorized Exercise 01 `docker compose stop` freed port 8080 without
removing its containers or data. A subsequent before/after audit preserved all
31 pre-existing containers, 41 volumes, 10 networks, and 27 images, as well as
Exercise 01 files, host PostgreSQL service/PID, global Git identity, and existing
home worktree changes. New runtime resources are three Exercise 02 containers,
one project network, one named database volume, the backend v2 and Redis images,
and retained Docker build cache. Initial Exercise 02 containers/network were
removed only as part of the required persistence test; no volumes were deleted.
Audit helpers, transcripts, events, results, and screenshot helpers remain under
`/tmp/opencode/`. The verified Exercise 02 stack remains running.

## Scope

This lab does not implement StoreX business features or claim production
readiness. Healthcheck success, SQL success, Redis success, and persistence are
separate acceptance checks. No Redis durability claim is made.
