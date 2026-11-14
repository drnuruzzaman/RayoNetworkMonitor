"""Automatic app detection.

Layer 1  AdGuard catalog sync: AdGuard Home ships a maintained list of popular services
         (TikTok, Roblox, Netflix…) with their domains. We import it and refresh it daily.
Layer 2  Auto-detect: any address no app covers is grouped by its site (Public Suffix List).
         Once a site has enough lookups it becomes an "auto" app, e.g. westpac.com.au → "Westpac".
Layer 3  Noise filter: trackers (blocked by AdGuard), cloud/CDN infrastructure, local names and
         relayed router traffic never become apps.
Layer 4  Review: auto apps start unreviewed; the UI lets the user keep, rename, recategorise,
         merge or mark them as background. User choices are never overwritten.
"""
import json
import logging
import re
import time

from . import adguard, db, psl
from . import settings_store as S

log = logging.getLogger("homenet.detect")

# ------------------------------------------------------------------ layer 3: infrastructure
INFRA_SITES = {
    "cloudfront.net", "akamaiedge.net", "akamai.net", "akamaihd.net", "akamaized.net", "edgekey.net", "edgesuite.net",
    "akadns.net", "akamaitechnologies.com", "fastly.net", "fastlylb.net", "fastly-edge.com", "cloudflare.net",
    "cloudflare-dns.com", "amazonaws.com", "awsglobalaccelerator.com", "elb.amazonaws.com", "azureedge.net",
    "azurewebsites.net", "azure.com", "windows.net", "trafficmanager.net", "cloudapp.net", "msedge.net",
    "azurefd.net", "1e100.net", "googleusercontent.com", "gvt1.com", "gvt2.com", "ggpht.com", "googlesyndication.com",
    "doubleclick.net", "googleadservices.com", "google-analytics.com", "googletagmanager.com", "app-measurement.com",
    "crashlytics.com", "firebaseio.com", "firebaseinstallations.googleapis.com", "apple-dns.net", "aaplimg.com",
    "cdn-apple.com", "mzstatic.com", "icloud-content.com", "edgecastcdn.net", "llnwd.net", "llnw.net", "cdn77.org",
    "b-cdn.net", "jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com", "digicert.com", "letsencrypt.org",
    "lencr.org", "sectigo.com", "globalsign.com", "pki.goog", "ocsp.apple.com", "msftncsi.com", "msftconnecttest.com",
    "nflxso.net", "ntp.org", "pool.ntp.org", "time.windows.com", "branch.io", "appsflyer.com", "adjust.com",
    "segment.io", "segment.com", "mixpanel.com", "amplitude.com", "sentry.io", "newrelic.com", "nr-data.net",
    "bugsnag.com", "datadoghq.com", "onesignal.com", "braze.com", "scorecardresearch.com", "adnxs.com",
    "criteo.com", "taboola.com", "outbrain.com", "rubiconproject.com", "pubmatic.com", "openx.net", "casalemedia.com",
    "moatads.com", "adsrvr.org", "demdex.net", "omtrdc.net", "everesttech.net", "hotjar.com", "clarity.ms",
    "bing.net", "live.net", "skype.net", "office.net", "office365.com", "microsoftonline.com", "msauth.net",
    "msftauth.net", "windowsupdate.com", "delivery.mp.microsoft.com", "dns.google", "quad9.net", "opendns.com",
    "adguard.org", "adguard-dns.com", "arpa",
    # IP-lookup, feature-flag and experiment services apps call in the background
    "ipify.org", "ipinfo.io", "ifconfig.me", "icanhazip.com", "ipapi.co", "ip-api.com", "myip.com",
    "launchdarkly.com", "statsig.com", "optimizely.com", "split.io", "growthbook.io", "rudderstack.com",
    "app-analytics-services.com", "firebaselogging-pa.googleapis.com", "appcenter.ms", "flurry.com",
    "gstatic.com", "googleapis.com", "fbcdn.net", "cdninstagram.com", "whatsapp.net",
}

# ------------------------------------------------------------------ category guess
_CATEGORY_HINTS = [
    ("Government", [r"\.gov(\.[a-z]{2})?$", r"\.govt\.nz$"]),
    ("Education", [r"\.edu(\.[a-z]{2})?$", r"\.ac\.[a-z]{2}$", r"school", r"learn", r"academ", r"study", r"tutor",
                   r"math", r"quiz", r"universit", r"college", r"homework", r"reading"]),
    ("Kids", [r"kids", r"\bkid", r"junior", r"\bjr\b", r"cartoon"]),
    ("Gambling", [r"casino", r"\bbet", r"bet365", r"poker", r"lotto", r"lottery", r"sportsbet", r"tab\.com\.au"]),
    ("Finance", [r"bank", r"\bpay", r"wallet", r"financ", r"invest", r"trade", r"trading", r"crypto", r"coin",
                 r"insur", r"loan", r"credit", r"super(annuation)?", r"broker", r"money"]),
    ("Gaming", [r"game", r"gaming", r"play", r"arcade", r"esport", r"\bclash", r"minecraft", r"roblox", r"steam"]),
    ("Video", [r"\btv\b", r"tv\.", r"video", r"stream", r"movie", r"film", r"anime", r"watch", r"cinema", r"\.tv$"]),
    ("Music", [r"music", r"radio", r"\bfm\b", r"podcast", r"audio", r"sound", r"songs?"]),
    ("Messaging", [r"chat", r"messag", r"mail", r"\bsms\b", r"voip", r"call"]),
    ("Social", [r"social", r"forum", r"community", r"dating", r"meet"]),
    ("Shopping", [r"shop", r"store", r"\bbuy", r"deal", r"mart\b", r"cart", r"market", r"outlet", r"fashion"]),
    ("News", [r"news", r"times", r"herald", r"\bpost\b", r"daily", r"journal", r"abc\.net\.au", r"sbs\.com\.au"]),
    ("AI", [r"\.ai$", r"\bgpt", r"llm", r"copilot"]),
]


def guess_category(site: str) -> str:
    s = site.lower()
    for cat, pats in _CATEGORY_HINTS:
        if any(re.search(p, s) for p in pats):
            return cat
    return "Other"


def pretty_name(site: str) -> str:
    """westpac.com.au → 'Westpac', some-new-game.io → 'Some New Game', bbc.co.uk → 'BBC'."""
    label = site.split(".")[0]
    words = re.split(r"[-_]+", label)
    if len(words) == 1 and len(label) <= 3:
        return label.upper()
    return " ".join(w.capitalize() for w in words if w) or site


def is_infrastructure(site: str) -> bool:
    return site in INFRA_SITES or any(site.endswith("." + s) for s in INFRA_SITES)


# ------------------------------------------------------------------ layer 1: AdGuard catalog
ADGUARD_GROUPS = {
    "social_network": "Social", "messenger": "Messaging", "streaming": "Video", "gaming": "Gaming",
    "shopping": "Shopping", "ai": "AI", "dating": "Social", "gambling": "Gambling", "privacy": "Privacy",
    "software": "Productivity", "cdn": "System", "hosting": "System", "music": "Music",
}
_RULE_RE = re.compile(r"^\|\|([a-z0-9.\-*]+)\^(\$[a-z,=]*)?$")


def _rule_domains(rules: list[str]) -> list[str]:
    out = []
    for r in rules or []:
        m = _RULE_RE.match((r or "").strip().lower())
        if not m:
            continue
        d = m.group(1).lstrip("*.")
        if d and "*" not in d and "." in d and d not in out:
            out.append(d)
    return out


async def sync_adguard_catalog(force: bool = False) -> dict:
    """Import AdGuard's blocked-services list as apps. Returns counts."""
    if not force and time.time() - (S.get("adguard_catalog_synced") or 0) < 86400:
        return {"skipped": True}
    data = await adguard.request("GET", "/blocked_services/all")
    services = data.get("blocked_services", []) if isinstance(data, dict) else []
    if not services:
        return {"added": 0, "updated": 0}
    added = updated = 0
    changed_ids = []
    now = time.time()
    for svc in services:
        ag_id, name = svc.get("id"), (svc.get("name") or "").strip()
        domains = _rule_domains(svc.get("rules"))
        if not ag_id or not name or not domains:
            continue
        cat = ADGUARD_GROUPS.get(svc.get("group_id") or "", "Other")
        track = 0 if cat == "System" else 1
        row = (db.q1("SELECT * FROM services WHERE adguard_id=?", (ag_id,))
               or db.q1("SELECT * FROM services WHERE lower(name)=lower(?)", (name,)))
        if row:
            have = db.jload(row["domains"], [])
            merged = have + [d for d in domains if d not in have]
            if merged != have or row["adguard_id"] != ag_id:
                db.ex("UPDATE services SET domains=?, adguard_id=? WHERE id=?", (json.dumps(merged), ag_id, row["id"]))
                updated += 1
                changed_ids.append(row["id"])
        else:
            cur = db.ex("INSERT INTO services(name, category, domains, track_time, source, reviewed, created, adguard_id) "
                        "VALUES(?,?,?,?, 'adguard', 1, ?, ?)", (name, cat, json.dumps(domains), track, now, ag_id))
            added += 1
            changed_ids.append(cur.lastrowid)
    S.set("adguard_catalog_synced", now)
    return {"added": added, "updated": updated, "changed_ids": changed_ids}


# ------------------------------------------------------------------ layer 2: auto-detect
def note_unknown(rows: list[tuple]) -> None:
    """rows: (ts, domain, device_id, blocked, is_gateway). Counts lookups per unknown site."""
    counts: dict[str, list] = {}
    for ts, domain, _dev, blocked, from_gateway in rows:
        if blocked or from_gateway:
            continue  # trackers and router-relayed lookups never become apps
        site = psl.registrable(domain)
        if not site or is_infrastructure(site):
            continue
        local_domain = (S.get("dhcp_domain") or "").strip().lower()
        if local_domain and (site == local_domain or site.endswith("." + local_domain)):
            continue
        c = counts.setdefault(site, [0, ts, ts, domain])
        c[0] += 1
        c[1], c[2] = min(c[1], ts), max(c[2], ts)
    if not counts:
        return
    with db.transaction() as conn:
        for site, (n, first, last, sample) in counts.items():
            conn.execute("""INSERT INTO unknown_sites(registrable, lookups, first_seen, last_seen, sample) VALUES(?,?,?,?,?)
                            ON CONFLICT(registrable) DO UPDATE SET lookups=lookups+excluded.lookups,
                            last_seen=MAX(last_seen, excluded.last_seen), first_seen=MIN(first_seen, excluded.first_seen)""",
                         (site, n, first, last, sample))


def promote_ready() -> list[int]:
    """Turn unknown sites with enough lookups into auto apps. Returns new service ids."""
    if not S.get("auto_detect_apps"):
        return []
    threshold = S.get("auto_min_lookups")
    ready = db.q("SELECT * FROM unknown_sites WHERE lookups>=? ORDER BY lookups DESC LIMIT 200", (threshold,))
    new_ids = []
    now = time.time()
    for r in ready:
        site = r["registrable"]
        # Already covered (e.g. AdGuard sync added it since)? Just drop the counter.
        if db.q1("SELECT 1 FROM services WHERE registrable=?", (site,)) or _covered(site):
            db.ex("DELETE FROM unknown_sites WHERE registrable=?", (site,))
            continue
        name = pretty_name(site)
        if db.q1("SELECT 1 FROM services WHERE lower(name)=lower(?)", (name,)):
            name = site
        cur = db.ex("INSERT INTO services(name, category, domains, track_time, source, reviewed, created, registrable) "
                    "VALUES(?,?,?,1,'auto',0,?,?)", (name, guess_category(site), json.dumps([site]), r["first_seen"] or now, site))
        db.ex("DELETE FROM unknown_sites WHERE registrable=?", (site,))
        new_ids.append(cur.lastrowid)
    if new_ids:
        log.info("Auto-detected %s new apps", len(new_ids))
    return new_ids


def _covered(site: str) -> bool:
    from .usage import match_service
    return match_service(site) is not None


def backfill_unknown(days: int = 7) -> int:
    """One-off: count unmapped lookups already stored, so existing sites can be detected straight away."""
    since = time.time() - days * 86400
    gw = {r["id"] for r in db.q("SELECT id FROM devices WHERE is_gateway=1")}
    rows = db.q("SELECT ts, domain, device_id, blocked FROM dns_queries WHERE service_id IS NULL AND ts>?", (since,))
    note_unknown([(r["ts"], r["domain"], r["device_id"], r["blocked"], r["device_id"] in gw) for r in rows])
    return len(rows)


DETECT_REVISION = 3  # bump when detection rules improve, to redo unreviewed suggestions


def redo_if_rules_changed() -> bool:
    """If detection rules improved since the last run, drop *unreviewed* auto apps so they're re-detected.
    Anything the user has kept, renamed or merged is left alone."""
    if (S.get("auto_detect_revision") or 1) >= DETECT_REVISION:
        return False
    ids = [r["id"] for r in db.q("SELECT id FROM services WHERE source='auto' AND reviewed=0")]
    with db.transaction() as c:
        for sid in ids:
            c.execute("UPDATE dns_queries SET service_id=NULL WHERE service_id=?", (sid,))
            c.execute("DELETE FROM usage_sessions WHERE service_id=?", (sid,))
            c.execute("DELETE FROM services WHERE id=?", (sid,))
        c.execute("DELETE FROM unknown_sites")
    S.set("auto_detect_backfilled", False)
    S.set("auto_detect_revision", DETECT_REVISION)
    log.info("Detection rules updated: re-detecting %s unreviewed apps", len(ids))
    return True


# ------------------------------------------------------------------ layer 4: review helpers
def merge(src_id: int, into_id: int) -> None:
    """Move one app's addresses and history into another, then delete it."""
    src = db.q1("SELECT * FROM services WHERE id=?", (src_id,))
    dst = db.q1("SELECT * FROM services WHERE id=?", (into_id,))
    if not src or not dst or src_id == into_id:
        raise ValueError("Choose two different apps")
    domains = db.jload(dst["domains"], [])
    domains += [d for d in db.jload(src["domains"], []) if d not in domains]
    with db.transaction() as c:
        c.execute("UPDATE services SET domains=? WHERE id=?", (json.dumps(domains), into_id))
        c.execute("UPDATE dns_queries SET service_id=? WHERE service_id=?", (into_id, src_id))
        c.execute("DELETE FROM usage_sessions WHERE service_id=?", (src_id,))
        c.execute("DELETE FROM services WHERE id=?", (src_id,))
