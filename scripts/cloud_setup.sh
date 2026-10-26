#!/usr/bin/env bash
# Claude Code on the web (a Linux cloud machine): get it ready to run the backend tests.
#   bash scripts/cloud_setup.sh
# Use it as the environment's setup script, or run it once at the start of a session. Safe to run
# again. It installs PostgreSQL + pgvector, creates the "sora" role and the sora_test database the
# tests use, installs the backend into .venv, and writes a local .env (git-ignored) pointing at it.
# Not for the owner's Windows PC (that one uses PostgreSQL in WSL; see README.md).
set -euo pipefail
cd "$(dirname "$0")/.."

SUDO=""
AS_POSTGRES="runuser -u postgres --"
if [ "$(id -u)" != "0" ]; then SUDO="sudo"; AS_POSTGRES="sudo -u postgres"; fi

if ! command -v psql >/dev/null 2>&1; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq postgresql postgresql-contrib >/dev/null
fi
PG_VERSION="$(ls /usr/lib/postgresql | sort -n | tail -1)"
if [ ! -f "/usr/share/postgresql/${PG_VERSION}/extension/vector.control" ]; then
  # A machine that came with PostgreSQL may have stale package lists, so refresh them first.
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq "postgresql-${PG_VERSION}-pgvector" >/dev/null
fi

$SUDO service postgresql start >/dev/null || $SUDO pg_ctlcluster "${PG_VERSION}" main start
for _ in $(seq 1 30); do
  if $AS_POSTGRES psql -qtAc "select 1" >/dev/null 2>&1; then break; fi
  sleep 1
done

as_postgres() { $AS_POSTGRES psql -v ON_ERROR_STOP=1 -qtA "$@"; }
if [ "$(as_postgres -c "select 1 from pg_roles where rolname = 'sora'")" != "1" ]; then
  as_postgres -c "create role sora login superuser password 'sora'"
fi
for db in sora sora_test; do
  if [ "$(as_postgres -c "select 1 from pg_database where datname = '${db}'")" != "1" ]; then
    as_postgres -c "create database ${db} owner sora"
  fi
  as_postgres -d "${db}" -c "create extension if not exists vector"
done

if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e "backend[dev]"

# The tests read DATABASE_URL from the repo's .env (and switch to the sora_test database); the
# token encryption tests need a key — a throwaway one, made here, for this machine only.
if [ ! -f .env ]; then
  key="$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  printf 'DATABASE_URL=postgresql://sora:sora@127.0.0.1:5432/sora\nENCRYPTION_KEY=%s\n' "$key" > .env
fi

echo "Ready: cd backend && ../.venv/bin/python -m pytest -q"
