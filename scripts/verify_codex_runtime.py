#!/usr/bin/env python3
"""Bounded Codex infrastructure probes without restarting shared dev.

The capacity-database probe creates a uniquely named disposable schema in the
engineering database, exercises real concurrent PostgreSQL transactions, then
removes only that schema. It uses the configured container authentication and
never prints credentials or application data. This is not live Docker isolation
proof; the Plan tracks those activation checks separately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

CONTAINER = "openmates-engineering-control-plane-api-1"
ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "backend.engineering_control_plane.coordination",
    "backend.engineering_control_plane.runtime_capacity",
    "backend.engineering_control_plane.coordination_repository",
)


def capacity_database_probe() -> int:
    sources = {
        name: (ROOT / (name.replace(".", "/") + ".py")).read_text() for name in MODULES
    }
    migration = (
        ROOT / "backend/engineering_control_plane/migrations/0005_runtime_capacity.sql"
    ).read_text()
    program = """import concurrent.futures, json, os, sys, types, uuid
import psycopg
from psycopg import sql
from backend.engineering_control_plane.config import Settings
payload=json.loads(sys.stdin.readline())
for name,source in payload['sources'].items():
    module=types.ModuleType(name);sys.modules[name]=module
    parent,attribute=name.rsplit('.',1)
    setattr(sys.modules[parent],attribute,module)
    exec(compile(source,name,'exec'),module.__dict__)
repository=sys.modules['backend.engineering_control_plane.coordination_repository']
url=Settings.from_environment().database_url
schema='codex_capacity_probe_'+uuid.uuid4().hex
created=False
try:
    with psycopg.connect(url) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    created=True
    def isolated_connect(database_url):
        connection=psycopg.connect(database_url)
        connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        return connection
    repository.connect=isolated_connect
    with isolated_connect(url) as connection:connection.execute(payload['migration'])
    store=repository.PostgresCoordinationRepository(url)
    gib=1024**3
    host=dict(memory_available=14*gib,memory_total=30*gib,disk_available={'root':68*gib},disk_total={'root':300*gib},memory_floor=4*gib,build_memory=4*gib,build_disk={'root':10*gib},max_environments=2,enforcement_verified=True)
    def request(key):
        return store.runtime_capacity_transition('test-host',action='request',owner=key,payload=dict(key=key,memory_limit=6*gib,disk_limits={'root':10*gib},source='a'*40,profile='basic'),host_observation=host)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(request,['a','b']))
    restarted=repository.PostgresCoordinationRepository(url)
    state=restarted.runtime_capacity_transition('test-host',action='status',owner='probe',payload={})
    assert sorted(r['state'] for r in state['requests'])==['admitted','queued'],state
    first=next(r for r in state['requests'] if r['state']=='admitted')['key']
    restarted.runtime_capacity_transition('test-host',action='observe',owner=first,payload=dict(key=first,memory_used=0,disk_used={'root':0},live=False))
    state=restarted.runtime_capacity_transition('test-host',action='release',owner=first,payload=dict(key=first,evidence_saved=True,removed=True),host_observation=host)
    assert sorted(r['state'] for r in state['requests'])==['admitted','released'],state
    request(first)
    state=restarted.runtime_capacity_transition('test-host',action='status',owner='probe',payload={})
    assert len(state['requests'])==2
    print(json.dumps({'status':'passed','concurrent_overcommit':False,'restart_preserved':True,'release_admitted_waiter':True,'retry_duplicated':False}))
finally:
    if created:
        with psycopg.connect(url) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        print(json.dumps({'disposable_schema_removed':True}))
"""
    # The script itself is supplied as argv; stdin carries source, never secrets.
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-c", program],
        input=json.dumps({"sources": sources, "migration": migration}) + "\n",
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode:
        # Remote traceback can contain connection strings; emit only the class.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_class": "capacity_database_probe_failed",
                    "exit_code": result.returncode,
                }
            )
        )
        return result.returncode
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            print(json.dumps(json.loads(line), sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity-database", action="store_true", required=True)
    parser.parse_args()
    return capacity_database_probe()


if __name__ == "__main__":
    raise SystemExit(main())
