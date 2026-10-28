"""Sky Plane SMP launcher - window + Microsoft login + game launch."""
import os
import queue
import subprocess
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

import core
from core import (APP_NAME, APP_VERSION, SERVER_HOST, SERVER_PORT, MC_VERSION,
                  AZURE_APP_ID, ROOT, GAME_DIR, log, resource_path)

# portablemc (the Minecraft library) is imported lazily-safe so we can show a
# readable error if something is wrong with the build.
try:
    import portablemc.base as pbase
    import portablemc.mojang as pmojang
    import portablemc.fabric as pfabric
    import portablemc.msa as pmsa
    PMC_ERROR = None
except Exception as _e:  # pragma: no cover
    PMC_ERROR = _e

W, H = 1024, 576
FONT = "Segoe UI"
NAVY = "#27325C"
NAVY_RGB = (39, 50, 92, 255)
YELLOW_RGB = (255, 216, 77, 255)
YELLOW_HOVER_RGB = (255, 232, 130, 255)
CREAM_RGB = (255, 248, 230, 238)
WHITE_RGB = (255, 255, 255, 255)


# ----------------------------------------------------------------------------
# image helpers
# ----------------------------------------------------------------------------
def rounded(w, h, radius, fill, outline=None, ow=3):
    s = 3
    im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s,
                        fill=fill, outline=outline, width=ow * s if outline else 0)
    return im.resize((w, h), Image.LANCZOS)


class HandlerBase(object):
    pass


if PMC_ERROR is None:
    HandlerBase = getattr(pfabric, "Handler", object)


class InstallHandler(HandlerBase):
    """Receives progress events from PortableMC while the game installs."""

    def __init__(self, status_cb, progress_cb):
        self._status = status_cb
        self._progress = progress_cb

    def load_jvm(self, major_version):
        self._status("Checking Java %s..." % major_version)

    def load_libraries(self):
        self._status("Checking game libraries...")

    def load_assets(self, id):
        self._status("Checking game assets...")

    def fetch_loader_version(self, game_version, loader_version):
        self._status("Getting Fabric...")

    def fetch_version(self, version):
        self._status("Getting Minecraft %s..." % version)

    def download_resources(self):
        self._status("Downloading game files... (first time only)")
        return False  # False = do not cancel

    def download_progress(self, count, total_count, size, total_size):
        if total_size:
            self._progress(min(1.0, size / float(total_size)))


# ----------------------------------------------------------------------------
# the app
# ----------------------------------------------------------------------------
class App:
    def __init__(self):
        core.ensure_dirs()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry("%dx%d+%d+%d" % (W, H, (sw - W) // 2, (sh - H) // 2))
        try:
            self.root.iconbitmap(resource_path("assets/icon.ico"))
        except Exception:
            pass

        self.canvas = tk.Canvas(self.root, width=W, height=H, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.bg = ImageTk.PhotoImage(Image.open(resource_path("assets/bg.png")))
        self.canvas.create_image(0, 0, image=self.bg, anchor="nw")

        logo = Image.open(resource_path("assets/logo.png")).convert("RGBA").resize((120, 120), Image.LANCZOS)
        mask = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 119, 119), radius=26, fill=255)
        logo.putalpha(mask)
        frame = rounded(126, 126, 28, (0, 0, 0, 0), NAVY_RGB, 3)
        frame.alpha_composite(logo, (3, 3))
        self.logo_img = ImageTk.PhotoImage(frame)

        self.keep = []          # image references of the current screen
        self.shadows = {}
        self.tasks = queue.Queue()
        self.screen = None
        self.login_gen = 0
        self.account = None
        self.db = None
        self.target = 0.0
        self.shown = 0.0
        self.bar_items = None
        self.status_item = None
        self.dots_item = None
        self.bar_cache = {}
        self.proc = None

        self.root.after(40, self.tick)
        if PMC_ERROR is not None:
            self.show_error("The launcher is missing a part: %s" % PMC_ERROR, retry=None)
        else:
            self.start()

    # ---- thread -> UI plumbing ------------------------------------------
    def post(self, fn, *args):
        self.tasks.put((fn, args))

    def tick(self):
        try:
            while True:
                fn, args = self.tasks.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log(traceback.format_exc())
        except queue.Empty:
            pass
        if self.screen == "loading":
            self.shown += (self.target - self.shown) * 0.18
            self.draw_bar(self.shown)
            if self.dots_item is not None:
                n = int(time.time() * 2) % 4
                self.set_text(self.dots_item, "Loading" + "." * n)
        self.root.after(40, self.tick)

    # ---- drawing helpers --------------------------------------------------
    def clear(self, screen):
        self.canvas.delete("ui")
        self.keep = []
        self.shadows = {}
        self.screen = screen
        self.bar_items = None
        self.status_item = None
        self.dots_item = None

    def text(self, x, y, s, size=14, bold=True, fill=NAVY, shadow=None, anchor="center", width=None):
        font = (FONT, size, "bold" if bold else "normal")
        kw = {"font": font, "anchor": anchor, "tags": ("ui",)}
        if width:
            kw["width"] = width
        sh = None
        if shadow:
            sh = self.canvas.create_text(x + 2, y + 2, text=s, fill=shadow, **kw)
        item = self.canvas.create_text(x, y, text=s, fill=fill, **kw)
        if sh is not None:
            self.shadows[item] = sh
        return item

    def set_text(self, item, s):
        self.canvas.itemconfig(item, text=s)
        sh = self.shadows.get(item)
        if sh is not None:
            self.canvas.itemconfig(sh, text=s)

    def panel(self, cx, cy, w, h):
        img = ImageTk.PhotoImage(rounded(w, h, 30, CREAM_RGB, NAVY_RGB, 4))
        self.keep.append(img)
        self.canvas.create_image(cx, cy, image=img, tags=("ui",))

    def button(self, cx, cy, w, h, label, command, size=16):
        normal = ImageTk.PhotoImage(rounded(w, h, h // 2, YELLOW_RGB, NAVY_RGB, 3))
        hover = ImageTk.PhotoImage(rounded(w, h, h // 2, YELLOW_HOVER_RGB, NAVY_RGB, 3))
        self.keep += [normal, hover]
        img = self.canvas.create_image(cx, cy, image=normal, tags=("ui",))
        txt = self.canvas.create_text(cx, cy, text=label, font=(FONT, size, "bold"), fill=NAVY, tags=("ui",))
        for item in (img, txt):
            self.canvas.tag_bind(item, "<Enter>", lambda e: (self.canvas.itemconfig(img, image=hover),
                                                              self.canvas.config(cursor="hand2")))
            self.canvas.tag_bind(item, "<Leave>", lambda e: (self.canvas.itemconfig(img, image=normal),
                                                              self.canvas.config(cursor="")))
            self.canvas.tag_bind(item, "<Button-1>", lambda e: command())

    def link(self, cx, cy, label, command):
        item = self.text(cx, cy, label, size=11, bold=False, fill="#4A5A93")
        self.canvas.tag_bind(item, "<Enter>", lambda e: (self.canvas.itemconfig(item, font=(FONT, 11, "underline")),
                                                          self.canvas.config(cursor="hand2")))
        self.canvas.tag_bind(item, "<Leave>", lambda e: (self.canvas.itemconfig(item, font=(FONT, 11)),
                                                          self.canvas.config(cursor="")))
        self.canvas.tag_bind(item, "<Button-1>", lambda e: command())

    def footer(self):
        self.text(14, H - 12, "%s launcher v%s" % (APP_NAME, APP_VERSION), size=9, bold=False,
                  fill="#FFFFFF", shadow=NAVY, anchor="w")

    def logo(self, cx, cy):
        self.canvas.create_image(cx, cy, image=self.logo_img, tags=("ui",))

    # ---- screens -----------------------------------------------------------
    def show_login(self):
        self.clear("login")
        self.panel(470, 330, 440, 340)
        self.logo(470, 232)
        self.text(470, 318, "Welcome aboard!", size=21)
        self.text(470, 352, "Log in with your Microsoft account\nto join %s" % APP_NAME,
                  size=11, bold=False, fill="#3B4A80")
        self.button(470, 410, 300, 52, "Log in with Microsoft", self.on_login_click)
        self.text(470, 462, "You need to own Minecraft: Java Edition", size=9, bold=False, fill="#5A6AA0")
        self.footer()

    def show_home(self, account):
        self.clear("home")
        self.panel(470, 330, 440, 340)
        self.logo(470, 232)
        self.text(470, 322, "Welcome back,", size=12, bold=False, fill="#3B4A80")
        self.text(470, 350, account.username, size=22)
        self.button(470, 410, 260, 56, "PLAY", lambda: self.begin_play(account), size=20)
        self.link(470, 462, "Not you? Switch account", self.on_switch_account)
        self.footer()

    def show_code(self, code, uri):
        self.clear("code")
        self.panel(470, 310, 500, 340)
        self.text(470, 190, "Almost there!", size=20)
        self.text(470, 226, "A web page opened. Type this code there and sign in:",
                  size=11, bold=False, fill="#3B4A80")
        box = ImageTk.PhotoImage(rounded(300, 70, 20, (255, 255, 255, 255), NAVY_RGB, 3))
        self.keep.append(box)
        self.canvas.create_image(470, 290, image=box, tags=("ui",))
        self.text(470, 290, code, size=30)
        self.text(470, 340, "(the code was copied to your clipboard)", size=9, bold=False, fill="#5A6AA0")
        self.text(470, 362, uri, size=10, bold=False, fill="#3B4A80")
        self.button(470, 410, 240, 46, "Open the page again", lambda: webbrowser.open(uri), size=13)
        self.link(470, 455, "Cancel", self.on_cancel_login)
        self.footer()

    def show_loading(self, status="Starting..."):
        self.clear("loading")
        self.dots_item = self.text(W // 2, 446, "Loading", size=22, fill="white", shadow=NAVY)
        track = ImageTk.PhotoImage(rounded(480, 34, 17, (255, 255, 255, 70), WHITE_RGB, 3))
        self.keep.append(track)
        self.canvas.create_image(W // 2, 494, image=track, tags=("ui",))
        self.bar_items = self.canvas.create_image(W // 2 - 236, 494, anchor="w", tags=("ui",))
        self.status_item = self.text(W // 2, 540, status, size=12, bold=False, fill="white", shadow=NAVY)
        self.target = 0.0
        self.shown = 0.0
        self.draw_bar(0.0)

    def draw_bar(self, frac):
        if self.bar_items is None:
            return
        w = max(26, int(472 * max(0.0, min(1.0, frac))))
        key = w // 3
        img = self.bar_cache.get(key)
        if img is None:
            img = ImageTk.PhotoImage(rounded(max(26, key * 3), 26, 13, YELLOW_RGB, (255, 241, 170, 255), 2))
            self.bar_cache[key] = img
        self.canvas.itemconfig(self.bar_items, image=img)

    def show_error(self, message, retry="home"):
        self.clear("error")
        self.panel(470, 300, 560, 360)
        self.text(470, 170, "Oops!", size=22)
        self.text(470, 255, message, size=12, bold=False, fill="#3B4A80", width=480)
        if retry is not None:
            self.button(470, 360, 220, 48, "Try again", self.on_retry, size=14)
        self.link(470, 412, "Open the log folder", lambda: os.startfile(str(ROOT)) if hasattr(os, "startfile") else None)
        self.footer()

    # ---- status/progress callbacks (safe to call from threads) ----------------
    def set_status(self, s):
        def apply():
            if self.status_item is not None:
                self.set_text(self.status_item, s)
        self.post(apply)

    def set_progress(self, base, span, frac):
        def apply():
            self.target = max(self.target, base + span * frac)
        self.post(apply)

    # ---- flows -----------------------------------------------------------------
    def start(self):
        self.show_loading("Checking your account...")

        def work():
            try:
                self.db = pmsa.Database(core.ACCOUNTS_FILE)
                acct = self.load_saved_account()
            except Exception:
                log(traceback.format_exc())
                acct = None
            if acct:
                self.account = acct
                self.post(self.show_home, acct)
            else:
                self.post(self.show_login)
        threading.Thread(target=work, daemon=True).start()

    def load_saved_account(self):
        try:
            accounts = list(self.db.load_iter())
        except Exception:
            log(traceback.format_exc())
            return None
        for acct in accounts:
            try:
                try:
                    acct.request_profile()
                except Exception as e:
                    if type(e).__name__ == "AuthOutdatedTokenError":
                        acct.request_refresh()
                        acct.request_profile()
                    else:
                        raise
                self.db.store(acct)
                return acct
            except Exception:
                log("saved account unusable: " + traceback.format_exc())
        return None

    def on_login_click(self):
        self.login_gen += 1
        gen = self.login_gen
        self.show_loading("Contacting Microsoft...")

        def work():
            try:
                auth = pmsa.Auth(AZURE_APP_ID)
                flow = auth.request_device_code()
                code, uri = flow.user_code, flow.verification_uri
                self.post(self.on_code_ready, gen, code, uri)
                acct = flow.wait()
                if gen != self.login_gen:
                    return
                try:
                    acct.request_profile()
                except Exception as e:
                    if type(e).__name__ == "AuthOutdatedTokenError":
                        acct.request_refresh()
                        acct.request_profile()
                    else:
                        raise
                self.db.store(acct)
                self.account = acct
                self.post(self.begin_play, acct)
            except Exception as e:
                log(traceback.format_exc())
                if gen == self.login_gen:
                    self.post(self.show_error, core.friendly_error(e), "login")
        threading.Thread(target=work, daemon=True).start()

    def on_code_ready(self, gen, code, uri):
        if gen != self.login_gen:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.root.update()
        except Exception:
            pass
        webbrowser.open(uri)
        self.show_code(code, uri)

    def on_cancel_login(self):
        self.login_gen += 1
        self.show_login()

    def on_switch_account(self):
        try:
            if self.account is not None:
                self.db.remove_from_uuid(self.account.uuid)
        except Exception:
            log(traceback.format_exc())
        self.account = None
        self.show_login()

    def on_retry(self):
        if self.account is not None:
            self.show_home(self.account)
        else:
            self.show_login()

    def begin_play(self, account):
        self.show_loading("Getting ready...")
        threading.Thread(target=self.run_play, args=(account,), daemon=True).start()

    def run_play(self, account):
        try:
            inst = pfabric.Installer(pfabric.Loader.Fabric, MC_VERSION)
            inst.set_main_dir(GAME_DIR)
            try:
                inst.jvm_policy = pbase.JvmPolicy.MojangThenSystem
            except Exception:
                log("could not set jvm policy: " + traceback.format_exc())
            try:
                inst.launcher_name = "SkyPlaneSMP"
                inst.launcher_version = APP_VERSION
            except Exception:
                pass
            inst.set_auth_msa(account)
            inst.quick_play = pmojang.QuickPlay.Multiplayer(SERVER_HOST, SERVER_PORT)

            mods_dir = Path(inst.mc_dir) / "mods"
            self.set_status("Checking the Sky Plane mods...")
            core.sync_mods(
                mods_dir,
                progress=lambda d, t: self.set_progress(0.0, 0.40, (d / t) if t else 0.0),
                status=self.set_status,
            )
            self.set_progress(0.0, 0.40, 1.0)

            self.set_status("Preparing Minecraft %s with Fabric..." % MC_VERSION)
            handler = InstallHandler(self.set_status, lambda f: self.set_progress(0.40, 0.60, f))
            game = inst.install(handler)
            self.set_progress(0.40, 0.60, 1.0)

            game.jvm_args = list(game.jvm_args) + ["-Xmx" + core.pick_heap()]
            self.set_status("Starting the game...")
            log("launching: %s" % [str(a) for a in game.args()][:3])
            logf = open(core.GAME_LOG, "wb")
            flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
            proc = game.command()(stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
            self.post(self.on_launched, proc)
        except Exception as e:
            log(traceback.format_exc())
            self.post(self.show_error, core.friendly_error(e), "home")

    def on_launched(self, proc):
        self.proc = proc
        self.target = 1.0
        if self.status_item is not None:
            self.set_text(self.status_item, "Game is starting - have fun!")
        threading.Thread(target=self.watch, args=(proc,), daemon=True).start()
        self.root.after(4000, self.root.withdraw)

    def watch(self, proc):
        code = proc.wait()
        self.post(self.on_game_exit, code)

    def on_game_exit(self, code):
        if code == 0:
            self.root.destroy()
            return
        self.root.deiconify()
        self.show_error("The game closed unexpectedly (code %s).\nThe log folder has game.log with details." % code, "home")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        App().run()
    except Exception:
        log(traceback.format_exc())
        raise
