"""
telestep_update.py - the optional "is there a newer version?" check.

This is the ONLY place Telestep talks to the internet, and only when the person switches it on (Settings > Options) or
presses "Check for updates" on the About page.  It sends one plain HTTPS GET to the project's GitLab release list; no
identifier, no recording data, nothing about the PC.  It never downloads or installs anything: if a newer version
exists it just offers to open the download page.
"""
import json
import re
import urllib.error
import urllib.request

PROJECT = "ac-pcr1%2Ftelestep"
API = f"https://gitlab.com/api/v4/projects/{PROJECT}"
PAGE = "https://gitlab.com/ac-pcr1/telestep/-/releases"


def parse_version(text):
    """'v1.2.3-beta' -> (1, 2, 3).  Unparseable -> ()."""
    m = re.search(r"(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def fetch_json(url, timeout=6):
    from telestep_core import VERSION
    req = urllib.request.Request(url, headers={"User-Agent": f"Telestep/{VERSION} (update check)",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read(200_000).decode("utf-8", "replace"))


def latest_release(fetch=None, timeout=6):
    """{'version', 'url', 'notes'} for the newest release (or tag), or None if there is none."""
    fetch = fetch or fetch_json
    rel = fetch(f"{API}/releases?per_page=1", timeout)
    if isinstance(rel, list) and rel:
        r = rel[0]
        tag = r.get("tag_name") or r.get("name") or ""
        link = (r.get("_links") or {}).get("self") or PAGE
        return {"version": tag, "url": link, "notes": (r.get("description") or "").strip()[:400]}
    tags = fetch(f"{API}/repository/tags?per_page=1", timeout)
    if isinstance(tags, list) and tags:
        return {"version": tags[0].get("name", ""), "url": PAGE, "notes": ""}
    return None


def check(current, fetch=None, timeout=6):
    """Run the check.  Returns {'status': 'newer'|'current'|'unknown'|'error', 'version', 'url', 'notes', 'error'}."""
    try:
        rel = latest_release(fetch, timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return {"status": "error", "error": getattr(e, "reason", None) or str(e), "version": "", "url": PAGE, "notes": ""}
    if not rel or not parse_version(rel["version"]):
        return {"status": "unknown", "version": "", "url": PAGE, "notes": "", "error": ""}
    rel["status"] = "newer" if is_newer(rel["version"], current) else "current"
    rel["error"] = ""
    return rel
