"""Project-scoped real integration and down/up persistence acceptance test."""

import argparse
import json
import shlex
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "rikkei-ss04-storex02"
VOLUME = PROJECT + "_postgres-data"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
assert args.output_dir.parent.is_dir(), "Output parent directory must already exist"
args.output_dir.mkdir(exist_ok=False)
transcript = (args.output_dir / "commands.log").open("w")


def emit(message):
    print(message, flush=True)
    transcript.write(message + "\n")
    transcript.flush()


def run(*command):
    emit("$ " + shlex.join(command))
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    emit(result.stdout.rstrip())
    result.check_returncode()
    return result.stdout.strip()


def compose(*command):
    return run("docker", "compose", *command)


def inspect(kind, name):
    return json.loads(run("docker", kind, "inspect", name))[0]


def inspect_service(service):
    # Inspect only this project's container ID, never another project's resources.
    container_id = subprocess.check_output(["docker", "compose", "ps", "-q", service],
                                            cwd=ROOT, text=True).strip()
    assert container_id, f"No running container for {service}"
    return json.loads(subprocess.check_output(["docker", "inspect", container_id], text=True))[0]


def http(path):
    try:
        with urllib.request.urlopen("http://localhost:8080" + path, timeout=12) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def wait_for_application():
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            db_code, db = http("/db-check")
            redis_code, redis = http("/redis-check")
            if db_code == redis_code == 200:
                assert db["queryResult"] == 1 and db["database"] == "storex_db"
                assert db["databaseReachable"] is True and db["queryExecuted"] is True
                assert redis["response"] == "PONG" and redis["pingExecuted"] is True
                assert redis["redisReachable"] is True
                postgres = inspect_service("postgres")
                cache = inspect_service("redis")
                backend = inspect_service("backend")
                assert postgres["State"]["Health"]["Status"] == "healthy"
                assert cache["State"]["Health"]["Status"] == "healthy"
                assert backend["State"]["Running"] and backend["RestartCount"] == 0
                assert db["serverAddress"].split("/")[0] == postgres["NetworkSettings"]["Networks"][PROJECT + "_default"]["IPAddress"]
                assert "SPRING_DATASOURCE_URL=jdbc:postgresql://postgres:5432/storex_db" in backend["Config"]["Env"]
                assert "SPRING_DATA_REDIS_HOST=redis" in backend["Config"]["Env"]
                assert not postgres["HostConfig"]["PortBindings"] and not cache["HostConfig"]["PortBindings"]
                assert any(h["ExitCode"] == 0 and h["Output"].strip() == "PONG"
                           for h in cache["State"]["Health"]["Log"])
                code, actuator = http("/actuator/health")
                assert code == 200 and actuator["components"]["db"]["status"] == "UP"
                assert actuator["components"]["redis"]["status"] == "UP"
                emit("LIVE SQL: " + json.dumps(db))
                emit("LIVE REDIS: " + json.dumps(redis))
                return {"db": db, "redis": redis, "actuator": actuator,
                        "ids": {"postgres": postgres["Id"], "redis": cache["Id"], "backend": backend["Id"]}}
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise AssertionError("Application/dependencies did not become ready")


def sql(statement):
    return compose("exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
                   "-U", "admin", "-d", "storex_db", "-At", "-c", statement)


def logs(suffix):
    compose("ps")
    for service in ("postgres", "redis", "backend"):
        content = compose("logs", "--no-color", "--tail", "50", service)
        (args.output_dir / f"{service}-{suffix}.log").write_text(content + "\n")
        if service == "backend":
            assert "DB_CHECK SUCCESS database=storex_db queryResult=1" in content
            assert "REDIS_CHECK SUCCESS command=PING response=PONG" in content
            assert "ERROR" not in content and "CHECK FAILURE" not in content


compose("config", "-q")
config = json.loads(compose("config", "--format", "json"))
assert config["name"] == PROJECT
assert set(config["services"]) == {"backend", "postgres", "redis"}
b, p, r = (config["services"][s] for s in ("backend", "postgres", "redis"))
assert [b["image"], p["image"], r["image"]] == ["storex-backend:v2", "postgres:13", "redis:alpine"]
assert all(b["depends_on"][s]["condition"] == "service_healthy" for s in ("postgres", "redis"))
assert b["ports"][0]["published"] == "8080" and b["ports"][0]["target"] == 8080
assert b["environment"] == {"SPRING_DATASOURCE_URL": "jdbc:postgresql://postgres:5432/storex_db",
    "SPRING_DATASOURCE_USERNAME": "admin", "SPRING_DATASOURCE_PASSWORD": "admin",
    "SPRING_DATA_REDIS_HOST": "redis", "SPRING_DATA_REDIS_PORT": "6379"}
assert p["environment"] == {"POSTGRES_DB": "storex_db", "POSTGRES_USER": "admin", "POSTGRES_PASSWORD": "admin"}
assert not p.get("ports") and not r.get("ports")
assert p["healthcheck"]["test"] == ["CMD", "pg_isready", "-h", "postgres", "-U", "admin", "-d", "storex_db"]
assert r["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]
assert p["volumes"][0]["type"] == "volume" and p["volumes"][0]["target"] == "/var/lib/postgresql/data"
assert config["volumes"][p["volumes"][0]["source"]]["name"] == VOLUME
emit("PASS: static Compose configuration assertions")
with socket.socket() as port:
    port.bind(("0.0.0.0", 8080))

events = []
event_process = subprocess.Popen(["docker", "events", "--since", str(int(time.time()) - 1),
    "--filter", "type=container", "--filter", "label=com.docker.compose.project=" + PROJECT,
    "--format", "{{json .}}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def record_events():
    with (args.output_dir / "docker-events.jsonl").open("w") as stream:
        for line in event_process.stdout:
            stream.write(line)
            stream.flush()
            events.append(json.loads(line))


thread = threading.Thread(target=record_events, daemon=True)
thread.start()
try:
    compose("up", "-d")
    before = wait_for_application()
    logs("before")
    marker = "SS04_BAI02_PERSISTENCE_TEST_" + uuid.uuid4().hex
    sql("CREATE TABLE IF NOT EXISTS ss04_bai02_persistence (marker text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT clock_timestamp());")
    sql(f"INSERT INTO ss04_bai02_persistence(marker) VALUES ('{marker}');")
    query = f"SELECT row_to_json(t) FROM (SELECT marker, created_at::text AS created_at FROM ss04_bai02_persistence WHERE marker='{marker}') t;"
    row_before = json.loads(sql(query))
    assert row_before["marker"] == marker
    volume_before = inspect("volume", VOLUME)
    emit("BEFORE container: " + before["ids"]["postgres"])
    emit("BEFORE marker row: " + json.dumps(row_before))
    compose("down")  # Intentionally never use -v.
    assert inspect("volume", VOLUME) == volume_before
    assert not subprocess.check_output(["docker", "ps", "-aq", "--filter",
        "label=com.docker.compose.project=" + PROJECT], text=True).strip()
    compose("up", "-d")
    after = wait_for_application()
    logs("after")
    row_after = json.loads(sql(query))  # No INSERT after recreation.
    assert row_after == row_before
    assert before["ids"]["postgres"] != after["ids"]["postgres"]
    assert inspect("volume", VOLUME) == volume_before
    emit("AFTER container: " + after["ids"]["postgres"])
    emit("AFTER marker row: " + json.dumps(row_after))
    time.sleep(1)  # Allow the event reader to drain before sequencing assertions.
    sequences = {}
    for phase, result in (("initial", before), ("recreated", after)):
        times = {}
        for service in ("postgres", "redis", "backend"):
            action = "start" if service == "backend" else "health_status: healthy"
            matches = [e for e in events if e["Actor"]["ID"] == result["ids"][service] and e["Action"] == action]
            assert matches, f"Missing {phase} {service} {action} event"
            nano = min(e["timeNano"] for e in matches)
            times[service] = {"action": action, "timeNano": nano,
                "utc": datetime.fromtimestamp(nano / 1e9, timezone.utc).isoformat()}
        assert times["postgres"]["timeNano"] < times["backend"]["timeNano"]
        assert times["redis"]["timeNano"] < times["backend"]["timeNano"]
        sequences[phase] = times
        emit("ORDERING " + phase + ": " + json.dumps(times))
    results = {"project": PROJECT, "marker_before": row_before, "marker_after": row_after,
               "before": before, "after": after, "volume": volume_before,
               "volume_preserved_after_down_and_up": True, "ordering": sequences}
    (args.output_dir / "results.json").write_text(json.dumps(results, indent=2))
    emit("PASS: real SQL, Redis PONG, startup health gates on both cycles, different PostgreSQL container, identical persisted row and named volume")
finally:
    event_process.terminate()
    event_process.wait(timeout=10)
    thread.join(timeout=5)
    transcript.close()
