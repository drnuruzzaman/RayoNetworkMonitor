"""In-memory runtime status shown on the System screen."""
STATUS: dict = {
    "started": None,
    "scan": {"last_run": None, "duration": None, "found": 0, "error": None, "running": False, "interface": None},
    "adguard": {"ok": None, "last_sync": None, "error": None, "version": None, "ingested": 0},
    "enforcer": {"last_run": None, "error": None, "blocked_ips": []},
}
