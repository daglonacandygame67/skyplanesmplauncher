"""Sky Plane SMP launcher - core logic (no GUI, no Minecraft library)."""
import json
import os
import sys
import time
import zipfile
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------------
# SETTINGS - edit these, then rebuild the .exe
# ----------------------------------------------------------------------------
APP_NAME = "Sky Plane SMP"
APP_VERSION = "1.0"
SERVER_HOST = "51.79.163.19"
SERVER_PORT = 25822
MC_VERSION = "1.21.1"

# Direct link to the zip that contains the all-in-one mod jar.
MODS_URL = "https://files.catbox.moe/s7guqw.zip"

# Optional: a link to a tiny JSON file like {"url": "https://.../new.zip"}.
# If set, the launcher reads it on every start, so you can push mod updates
# without rebuilding the .exe. Leave empty to always use MODS_URL.
MANIFEST_URL = ""

# Microsoft/Azure application ID used for the Microsoft login.
# This is PortableMC's own default ID. See README for using your own.
AZURE_APP_ID = "708e91b5-99f8-4a1d-80ec-e746cbb24771"

# ----------------------------------------------------------------------------
ROOT = Path(os.environ.get("APPDATA") or Path.home()) / "SkyPlaneSMP"
GAME_DIR = ROOT / "minecraft"
STATE_FILE = ROOT / "state.json"
LOG_FILE = ROOT / "launcher.log"
GAME_LOG = ROOT / "game.log"
ACCOUNTS_FILE = ROOT / "accounts.json"
USER_AGENT = "Mozilla/5.0 SkyPlaneSMP-Launcher"


def ensure_dirs():
    ROOT.mkdir(parents=True, exist_ok=True)
    GAME_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def http_open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def download_file(url, dest, progress=None, attempts=3):
    """Download url to dest, calling progress(done_bytes, total_bytes)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(attempts):
        try:
            with http_open(url, timeout=30) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            if total and done != total:
                raise IOError("Download was cut off (%d of %d bytes)" % (done, total))
            return
        except Exception as e:  # retry on any network problem
            last = e
            log("download attempt %d failed: %r" % (attempt + 1, e))
            time.sleep(2)
    raise last


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    ROOT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def resolve_mods_url():
    if MANIFEST_URL:
        try:
            with http_open(MANIFEST_URL, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("url"):
                return data["url"]
        except Exception as e:
            log("manifest fetch failed: %r" % (e,))
    return MODS_URL


def sync_mods(mods_dir, progress=None, status=None):
    """Make sure the pack jar is in mods_dir. Downloads only when needed."""
    mods_dir = Path(mods_dir)
    mods_dir.mkdir(parents=True, exist_ok=True)
    url = resolve_mods_url()
    state = load_state()
    files = state.get("files", [])
    if files and state.get("url") == url and all((mods_dir / n).exists() for n in files):
        log("mods up to date")
        if progress:
            progress(1, 1)
        return False

    if status:
        status("Downloading the Sky Plane mods...")
    tmp = ROOT / "download" / "mods.zip"
    download_file(url, tmp, progress)

    if status:
        status("Installing mods...")
    try:
        with zipfile.ZipFile(tmp) as z:
            jars = [i for i in z.infolist()
                    if not i.is_dir() and i.filename.lower().endswith(".jar")]
            if not jars:
                raise RuntimeError("The mod download did not contain any .jar file.")
            # remove what we installed last time, plus stale copies of the pack
            for name in files:
                try:
                    (mods_dir / name).unlink()
                except OSError:
                    pass
            for old in mods_dir.glob("TransitAviationPack*.jar"):
                try:
                    old.unlink()
                except OSError:
                    pass
            installed = []
            for info in jars:
                name = Path(info.filename).name
                target = mods_dir / name
                part = mods_dir / (name + ".part")
                with z.open(info) as src, open(part, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                os.replace(part, target)
                installed.append(name)
    except zipfile.BadZipFile:
        raise RuntimeError("The mod download is not a valid zip file. Check MODS_URL.")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    save_state({"url": url, "files": installed, "time": int(time.time())})
    log("installed mods: %s" % installed)
    return True


def total_ram_gb():
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        s = MS()
        s.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return s.ullTotalPhys / 2 ** 30
    except Exception:
        return 8.0


def pick_heap():
    gb = total_ram_gb()
    if gb >= 12:
        return "6G"
    if gb >= 8:
        return "4G"
    return "3G"


def friendly_error(e):
    name = type(e).__name__
    text = str(e)
    table = {
        "AuthDoesNotOwnGameError": "This Microsoft account does not own Minecraft: Java Edition.",
        "AuthDeclinedError": "The login was declined. Please try again.",
        "AuthTimedOutError": "The login took too long and timed out. Please try again.",
        "DownloadError": "Some game files failed to download. Check your internet and try again.",
        "JvmNotFoundError": "Could not get Java for the game. Check your internet and try again.",
    }
    if name in table:
        return table[name]
    if isinstance(e, (OSError, TimeoutError)) and "urlopen" in text.lower():
        return "Could not reach the internet. Check your connection and try again."
    if name in ("URLError", "HTTPError", "timeout", "gaierror"):
        return "Network problem: %s" % text
    return text or name
