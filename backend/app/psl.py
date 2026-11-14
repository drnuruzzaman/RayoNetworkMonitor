"""Works out which *site* an address belongs to ("registrable domain"), using the Public Suffix List.

    gw.api.westpac.com.au   -> westpac.com.au
    rr3---sn.googlevideo.com -> googlevideo.com
    iphone.nbn              -> None (local name, not a real internet site)

The list is downloaded on first use and refreshed monthly. Until it's available a small built-in
fallback covers the common endings.
"""
import logging
import re
import threading
import time

import httpx

from . import settings_store as S
from .config import DATA_DIR

log = logging.getLogger("homenet.psl")
PSL_FILE = DATA_DIR / "public_suffix_list.dat"
REFRESH_DAYS = 30

_lock = threading.Lock()
_rules: set[str] = set()
_wild: set[str] = set()
_exc: set[str] = set()
_tlds: set[str] = set()

# Fallback until the list is downloaded.
_FALLBACK_2LEVEL = {
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "asn.au", "id.au", "co.uk", "org.uk", "ac.uk", "gov.uk",
    "co.nz", "net.nz", "org.nz", "govt.nz", "co.jp", "ne.jp", "com.br", "com.cn", "com.hk", "co.in", "com.sg",
    "com.my", "co.za", "com.tr", "com.mx", "co.kr", "com.tw", "com.ar", "com.sa", "com.vn", "co.id", "com.ph",
}
LOCAL_TLDS = {"local", "lan", "home", "internal", "arpa", "localdomain", "localhost", "corp", "router", "nbn",
              "intranet", "private", "test", "invalid", "example", "onion"}
_VALID = re.compile(r"^[a-z0-9-]{1,40}$")  # longer labels are almost always generated/test names


def _load_text(text: str) -> int:
    rules, wild, exc, tlds = set(), set(), set(), set()
    for line in text.splitlines():
        line = line.strip().lower()
        # Only the official (ICANN) endings. The "private" section lists company sub-zones such as
        # github.io or claudeusercontent.com, which would split one company into many fake apps.
        if "===begin private domains===" in line:
            break
        if not line or line.startswith("//"):
            continue
        line = line.split()[0]
        try:
            line = line.encode("idna").decode() if not line.isascii() else line
        except Exception:
            continue
        if line.startswith("!"):
            exc.add(line[1:])
        elif line.startswith("*."):
            wild.add(line[2:])
        else:
            rules.add(line)
        tlds.add(line.lstrip("!*.").split(".")[-1])
    with _lock:
        _rules.clear(); _rules.update(rules)
        _wild.clear(); _wild.update(wild)
        _exc.clear(); _exc.update(exc)
        _tlds.clear(); _tlds.update(tlds)
    return len(rules) + len(wild) + len(exc)


def loaded() -> bool:
    return bool(_rules)


def load_from_disk() -> bool:
    if PSL_FILE.exists():
        try:
            n = _load_text(PSL_FILE.read_text(encoding="utf-8"))
            log.info("Loaded %s domain-ending rules", n)
            return n > 0
        except Exception as e:
            log.warning("Couldn't read %s: %s", PSL_FILE, e)
    return False


def needs_refresh() -> bool:
    return not PSL_FILE.exists() or time.time() - PSL_FILE.stat().st_mtime > REFRESH_DAYS * 86400


async def refresh() -> int:
    url = S.get("psl_url")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        text = r.text
    n = _load_text(text)
    if n < 1000:
        raise ValueError("The domain-ending list looks incomplete")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PSL_FILE.write_text(text, encoding="utf-8")
    S.set("psl_updated", time.time())
    return n


def registrable(domain: str) -> str | None:
    """The site an address belongs to, or None for local names / bare suffixes."""
    d = (domain or "").strip().lower().rstrip(".")
    if not d or d.replace(".", "").isdigit() or ":" in d:
        return None
    labels = d.split(".")
    if len(labels) < 2:
        return None
    if not all(_VALID.match(lb) for lb in labels[-3:]):
        return None
    tld = labels[-1]
    if tld in LOCAL_TLDS:
        return None
    n = len(labels)
    with _lock:
        if _rules:
            if tld not in _tlds:
                return None
            suffix_len = 1
            for i in range(n):
                cand = ".".join(labels[i:])
                if cand in _exc:
                    suffix_len = n - i - 1
                    break
                if cand in _rules or (i + 1 < n and ".".join(labels[i + 1:]) in _wild):
                    suffix_len = n - i
                    break
        else:
            if not tld.isalpha():
                return None
            suffix_len = 2 if ".".join(labels[-2:]) in _FALLBACK_2LEVEL else 1
    if n <= suffix_len:
        return None
    return ".".join(labels[n - suffix_len - 1:])
