"""Are the running workers older than the code on disk?

Frappe's gunicorn runs with --preload, so a worker holds the modules it imported at
boot. Editing a .py file changes nothing until `bench restart`, and the failure is not
a quiet one: a module imported lazily at request time gets loaded fresh, then asks the
stale, already-imported module for a name that only exists on disk. The result is an
ImportError for a function that is plainly right there in the file.

    ImportError: cannot import name 'natural_key' from '...api'

Tests never catch this, because a test runs in its own process and reads the disk.

    cd ~/frappe-bench && python apps/isoft_warehouse_location_management/tools/stale_workers.py
"""
import os
import subprocess
import sys
import time

BENCH = os.path.expanduser("~/frappe-bench")
APPS = os.path.join(BENCH, "apps")


def worker_started():
    """Oldest gunicorn start time, as epoch seconds."""
    try:
        out = subprocess.check_output(
            ["ps", "-o", "lstart=", "-C", "gunicorn"], stderr=subprocess.DEVNULL
        ).decode().strip().splitlines()
    except Exception:
        return None
    stamps = []
    for line in out:
        try:
            stamps.append(time.mktime(time.strptime(line.strip())))
        except ValueError:
            pass
    return min(stamps) if stamps else None


def newest_python(app):
    newest, where = 0, None
    for root, dirs, files in os.walk(os.path.join(APPS, app)):
        # tools/ and tests are never imported by a worker, so their mtime means nothing
        dirs[:] = [d for d in dirs
                   if d not in (".git", "node_modules", "__pycache__", "tools", "tests")]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            m = os.path.getmtime(path)
            if m > newest:
                newest, where = m, path
    return newest, where


def main():
    started = worker_started()
    if not started:
        print("  no gunicorn running — nothing to check")
        return 0
    apps = sys.argv[1:] or [d for d in os.listdir(APPS)
                            if os.path.isdir(os.path.join(APPS, d, ".git"))]
    stale = []
    for app in sorted(apps):
        newest, where = newest_python(app)
        if newest > started:
            stale.append((app, newest, where))
    fmt = lambda t: time.strftime("%H:%M:%S", time.localtime(t))
    print("  workers started   %s" % fmt(started))
    if not stale:
        print("  every app's Python is older than that — nothing to restart")
        return 0
    for app, newest, where in stale:
        print("  %-42s edited %s  <-- STALE" % (app, fmt(newest)))
        print("      %s" % os.path.relpath(where, APPS))
    print("\n  Run: bench restart")
    return 1


if __name__ == "__main__":
    sys.exit(main())
