import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

APP_TITLE = "NGMDB MapView"
DEFAULT_LON = -86.438
DEFAULT_LAT = 36.195
DEFAULT_ZOOM = 14
DEFAULT_SCALE_BIN = "mvCache24K"


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def apply_scale_bin_js(scale_bin: str = DEFAULT_SCALE_BIN) -> str:
    return rf"""
    (() => {{
        const desiredId = {scale_bin!r};

        function clickIt(el) {{
            try {{
                el.scrollIntoView({{block: 'center', inline: 'center'}});
            }} catch (e) {{}}

            try {{ el.click(); }} catch (e) {{}}

            try {{
                el.dispatchEvent(new MouseEvent('click', {{
                    bubbles: true,
                    cancelable: true,
                    view: window
                }}));
            }} catch (e) {{}}
        }}

        function clickById(id) {{
            const el = document.querySelector(`div[data-id="${{id}}"]`);
            if (!el) return false;
            clickIt(el);
            return true;
        }}

        let attempts = 0;
        const maxAttempts = 60;

        const timer = setInterval(() => {{
            const active = document.querySelector("#scaleBins > .active");
            if (active && active.getAttribute("data-id") === desiredId) {{
                clearInterval(timer);
                return;
            }}

            clickById(desiredId);

            attempts += 1;
            if (attempts >= maxAttempts) {{
                clearInterval(timer);
            }}
        }}, 500);
    }})();
    """


def current_scale_bin_js() -> str:
    return """
    (() => {
        const active = document.querySelector("#scaleBins > .active");
        return active ? active.getAttribute("data-id") : null;
    })();
    """


def js_true(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() == "true"
    if isinstance(value, (int, float)):
        return value == 1
    return False


def suppress_splash_js() -> str:
    return """
    (() => {
        const styleId = "ngmdb-hide-splash-style";
        if (!document.getElementById(styleId)) {
            const style = document.createElement("style");
            style.id = styleId;
            style.textContent =
                "#splash{display:none !important;visibility:hidden !important;opacity:0 !important;}";
            document.head.appendChild(style);
        }

        const splash = document.getElementById("splash");
        if (splash) {
            splash.style.display = "none";
            splash.style.visibility = "hidden";
            splash.style.opacity = "0";
        }

        return true;
    })();
    """


def hide_sidebar_js() -> str:
    return """
    (() => {
        let attempts = 0;
        const maxAttempts = 80;

        const timer = setInterval(() => {
            // The page has duplicate id="minimize" entries; use class/state selectors instead.
            const openToggle = document.querySelector("svg.minimize.active:not(.none)");
            if (!openToggle) {
                attempts += 1;
                if (attempts >= maxAttempts) {
                    clearInterval(timer);
                }
                return;
            }

            // Prefer the app's own toggle function; fallback to element click.
            try {
                if (typeof window.minimize === "function") {
                    window.minimize();
                } else {
                    openToggle.click();
                }
            } catch (e) {
                try {
                    openToggle.click();
                } catch (e2) {}
            }

            // Keep polling briefly in case app code re-opens it during startup.
            attempts += 1;
            if (attempts >= maxAttempts) {
                clearInterval(timer);
            }
        }, 250);

        return true;
    })();
    """


def search_move_js(lon: float, lat: float, zoom: int = DEFAULT_ZOOM) -> str:
    return rf"""
    (() => {{
        const lon = {lon!r};
        const lat = {lat!r};
        const zoom = {zoom!r};

        function setInputValue(input, value) {{
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                "value"
            )?.set;
            if (setter) {{
                setter.call(input, value);
            }} else {{
                input.value = value;
            }}
        }}

        function submitSearch(input, submitBtn) {{
            setInputValue(input, `${{lon}}, ${{lat}}`);
            input.dispatchEvent(new Event("input", {{ bubbles: true }}));
            input.dispatchEvent(new Event("change", {{ bubbles: true }}));

            const keyOpts = {{
                key: "Enter",
                code: "Enter",
                keyCode: 13,
                which: 13,
                bubbles: true,
                cancelable: true,
            }};
            try {{ input.dispatchEvent(new KeyboardEvent("keydown", keyOpts)); }} catch (e) {{}}
            try {{ input.dispatchEvent(new KeyboardEvent("keypress", keyOpts)); }} catch (e) {{}}
            try {{ input.dispatchEvent(new KeyboardEvent("keyup", keyOpts)); }} catch (e) {{}}

            try {{
                submitBtn.click();
            }} catch (e) {{}}

            try {{
                const url = new URL(window.location.href);
                url.searchParams.set("center", `${{lon}},${{lat}}`);
                url.searchParams.set("zoom", String(zoom));
                window.history.replaceState(null, "", url.toString());
            }} catch (e) {{}}
        }}

        let attempts = 0;
        const maxAttempts = 80;
        const timer = setInterval(() => {{
            const input = document.querySelector(".esri-search__input");
            const submitBtn = document.querySelector(".esri-search__submit-button");
            if (!input || !submitBtn) {{
                attempts += 1;
                if (attempts >= maxAttempts) {{
                    clearInterval(timer);
                }}
                return;
            }}

            submitSearch(input, submitBtn);
            clearInterval(timer);
        }}, 250);

        return true;
    }})();
    """


def move_map_js(lon: float, lat: float, zoom: int) -> str:
    return rf"""
    (() => {{
        const lon = {lon!r};
        const lat = {lat!r};
        const zoom = {zoom!r};

        function isMapView(candidate) {{
            if (!candidate || typeof candidate !== "object") {{
                return false;
            }}

            if (typeof candidate.goTo !== "function") {{
                return false;
            }}

            try {{
                if (candidate.type !== "2d") {{
                    return false;
                }}
                if (!("center" in candidate) || !("zoom" in candidate)) {{
                    return false;
                }}
                if (!("map" in candidate)) {{
                    return false;
                }}
            }} catch (e) {{
                return false;
            }}

            return true;
        }}

        function applyMove(view) {{
            view.goTo({{ center: [lon, lat], zoom }}, {{ animate: false }});
            try {{
                const url = new URL(window.location.href);
                url.searchParams.set("center", `${{lon}},${{lat}}`);
                url.searchParams.set("zoom", String(zoom));
                window.history.replaceState(null, "", url.toString());
            }} catch (e) {{}}
            return true;
        }}

        function fireSearch(input, text) {{
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                "value"
            )?.set;
            if (setter) {{
                setter.call(input, text);
            }} else {{
                input.value = text;
            }}

            input.dispatchEvent(new Event("input", {{ bubbles: true }}));
            input.dispatchEvent(new Event("change", {{ bubbles: true }}));

            const keyOpts = {{
                key: "Enter",
                code: "Enter",
                keyCode: 13,
                which: 13,
                bubbles: true,
                cancelable: true,
            }};
            input.dispatchEvent(new KeyboardEvent("keydown", keyOpts));
            input.dispatchEvent(new KeyboardEvent("keypress", keyOpts));
            input.dispatchEvent(new KeyboardEvent("keyup", keyOpts));
        }}

        function moveViaSearchWidget() {{
            const input = document.querySelector(".esri-search__input");
            if (!input) {{
                return false;
            }}

            try {{
                input.focus();
            }} catch (e) {{}}

            fireSearch(input, `${{lon}}, ${{lat}}`);

            try {{
                const submit = document.querySelector(".esri-search__submit-button");
                if (submit) {{
                    submit.click();
                }}
            }} catch (e) {{}}

            try {{
                const url = new URL(window.location.href);
                url.searchParams.set("center", `${{lon}},${{lat}}`);
                url.searchParams.set("zoom", String(zoom));
                window.history.replaceState(null, "", url.toString());
            }} catch (e) {{}}

            return true;
        }}

        const preferredKeys = ["view", "mapView", "mvView", "mainView", "_view"];
        for (const key of preferredKeys) {{
            try {{
                const candidate = window[key];
                if (isMapView(candidate)) {{
                    return applyMove(candidate);
                }}
            }} catch (e) {{}}
        }}

        for (const key of Object.keys(window)) {{
            let candidate = null;
            try {{
                candidate = window[key];
            }} catch (e) {{
                continue;
            }}

            if (!isMapView(candidate)) {{
                continue;
            }}

            try {{
                return applyMove(candidate);
            }} catch (e) {{}}
        }}

        if (moveViaSearchWidget()) {{
            return true;
        }}

        return false;
    }})();
    """


def browser_backend(window, command_file: str, scale_bin: str) -> None:
    stop_event = threading.Event()

    def on_closed():
        stop_event.set()

    window.events.closed += on_closed

    initial_command = read_json(Path(command_file)) or {}
    last_seq = initial_command.get("seq")

    while not stop_event.is_set():
        command = read_json(Path(command_file))
        if command:
            seq = command.get("seq")
            if seq != last_seq:
                try:
                    lon = float(command["lon"])
                    lat = float(command["lat"])
                    zoom = int(command.get("zoom", DEFAULT_ZOOM))
                except (KeyError, TypeError, ValueError):
                    lon = lat = None

                if lon is not None and lat is not None:
                    try:
                        move_result = window.evaluate_js(move_map_js(lon, lat, zoom))
                        moved_without_reload = js_true(move_result)
                    except Exception:
                        moved_without_reload = False

                    try:
                        if moved_without_reload:
                            window.evaluate_js(suppress_splash_js())
                            active_scale = window.evaluate_js(current_scale_bin_js())
                            if active_scale != scale_bin:
                                window.evaluate_js(apply_scale_bin_js(scale_bin))
                    except Exception:
                        stop_event.set()
                        break

                    if moved_without_reload:
                        last_seq = seq

        time.sleep(0.5)


def run_browser(command_file: str, scale_bin: str) -> None:
    import webview

    command = read_json(Path(command_file)) or {}
    try:
        lon = float(command.get("lon", DEFAULT_LON))
        lat = float(command.get("lat", DEFAULT_LAT))
        zoom = int(command.get("zoom", DEFAULT_ZOOM))
    except (TypeError, ValueError):
        lon, lat, zoom = DEFAULT_LON, DEFAULT_LAT, DEFAULT_ZOOM

    window = webview.create_window(
        APP_TITLE,
        url="https://ngmdb.usgs.gov/mapview/",
        width=1400,
        height=900,
    )

    def on_loaded():
        try:
            window.evaluate_js(suppress_splash_js())
            window.evaluate_js(hide_sidebar_js())
            window.evaluate_js(search_move_js(lon, lat, zoom))
            window.evaluate_js(apply_scale_bin_js(scale_bin))
        except Exception:
            pass

    window.events.loaded += on_loaded
    webview.start(
        browser_backend,
        args=(window, command_file, scale_bin),
        gui="edgechromium",
    )


class LauncherApp:
    def __init__(self, root: tk.Tk, command_file: Path):
        self.root = root
        self.command_file = command_file
        self.browser_process: subprocess.Popen | None = None
        self.command_seq = 0

        self.root.title(APP_TITLE)
        self.root.geometry("380x185")
        self.root.resizable(False, False)

        self.lon_var = tk.StringVar(value=str(DEFAULT_LON))
        self.lat_var = tk.StringVar(value=str(DEFAULT_LAT))
        self.status_var = tk.StringVar(
            value="Enter lon/lat and click Go to open or refresh the browser window."
        )

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Longitude").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(outer, textvariable=self.lon_var, width=24).grid(row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(outer, text="Latitude").grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(outer, textvariable=self.lat_var, width=24).grid(row=1, column=1, sticky="ew", pady=(0, 6))

        btn_frame = ttk.Frame(outer)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 8))

        ttk.Button(btn_frame, text="Go", command=self.go).pack(side="left")

        status = ttk.Label(outer, textvariable=self.status_var, wraplength=340, justify="left")
        status.grid(row=3, column=0, columnspan=2, sticky="w")

        outer.columnconfigure(1, weight=1)
        self.root.bind("<Return>", lambda event: self.go())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def validate_inputs(self) -> tuple[float, float]:
        try:
            lon = float(self.lon_var.get().strip())
            lat = float(self.lat_var.get().strip())
        except ValueError as exc:
            raise ValueError("Latitude and longitude must be valid numbers.") from exc

        if not (-180 <= lon <= 180):
            raise ValueError("Longitude must be between -180 and 180.")
        if not (-90 <= lat <= 90):
            raise ValueError("Latitude must be between -90 and 90.")

        return lon, lat

    def browser_is_running(self) -> bool:
        return self.browser_process is not None and self.browser_process.poll() is None

    def ensure_pywebview_available(self) -> bool:
        return importlib.util.find_spec("webview") is not None

    def start_browser_if_needed(self) -> None:
        if self.browser_is_running():
            return

        if not self.ensure_pywebview_available():
            messagebox.showerror(
                APP_TITLE,
                "pywebview is not installed.\n\nInstall it with:\n\npip install pywebview"
            )
            return

        self.browser_process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--browser",
                "--command-file",
                str(self.command_file),
                "--scale-bin",
                DEFAULT_SCALE_BIN,
            ]
        )

    def send_command(self, lon: float, lat: float, zoom: int = DEFAULT_ZOOM) -> None:
        self.command_seq += 1
        atomic_write_json(
            self.command_file,
            {"seq": self.command_seq, "lon": lon, "lat": lat, "zoom": zoom},
        )

    def go(self) -> None:
        try:
            lon, lat = self.validate_inputs()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self.send_command(lon, lat, DEFAULT_ZOOM)
        self.start_browser_if_needed()

        if self.browser_is_running():
            self.status_var.set(
                f"Browser updated to lon={lon:.6f}, lat={lat:.6f}. "
                "The page should center there and re-apply the 24K filter."
            )
        else:
            self.status_var.set(
                "Tried to start the browser. If nothing opened, check that pywebview and "
                "the Edge WebView2 runtime are installed."
            )

    def on_close(self) -> None:
        if self.browser_is_running():
            try:
                self.browser_process.terminate()
            except Exception:
                pass
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="Run the browser window process.")
    parser.add_argument(
        "--command-file",
        default=str(Path(tempfile.gettempdir()) / "ngmdb_mapview_tester.json"),
    )
    parser.add_argument("--scale-bin", default=DEFAULT_SCALE_BIN)
    args = parser.parse_args()

    if args.browser:
        run_browser(args.command_file, args.scale_bin)
    else:
        root = tk.Tk()
        LauncherApp(root, Path(args.command_file))
        root.mainloop()


if __name__ == "__main__":
    main()
