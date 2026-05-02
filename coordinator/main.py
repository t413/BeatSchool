from __future__ import annotations
import os, logging, argparse, flask

log = logging.getLogger(__name__)

WEBROOT = os.path.join(os.path.dirname(__file__), "webroot")

app = flask.Flask(__name__, static_folder=WEBROOT, static_url_path="")

@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")

def configure_all_module(module, app_arg, fn='configure', raises=True):
    """Import all submodules of module and call fn(a) if present."""
    import importlib, pkgutil
    modules = list(pkgutil.iter_modules(module.__path__))
    print(f"{module.__name__}.{fn}() importing {len(modules)} submodules:", end=' ')
    imported_mods = []
    for _, name, _ in modules:
        try:
            mod = importlib.import_module(f"{module.__name__}.{name}")
            imported_mods.append((name, mod))
            print(name, end=', ')
        except Exception as e:
            log.error(f"Error importing {module.__name__}.{name}: {e}")
            import traceback; traceback.print_exc()
            if raises: raise
    print(f"{module.__name__}.{fn}() now running {fn}() on submodules")
    for name, mod in imported_mods:
        try:
            func = getattr(mod, fn, None)
            if callable(func):
                print(f"* {name}")
                func(app_arg) if fn == 'configure' else func()
            else: print(f"{module.__name__}.{name} has no {fn}()")
        except Exception as e:
            print(f"Error calling {fn}() on {module.__name__}.{name}: {e}")
            import traceback; traceback.print_exc()
            if raises: raise
    print(f"{module.__name__}.{fn}() complete on {len(modules)} submodules.")

def main():
    parser = argparse.ArgumentParser(description="RhythmClass coordinator")
    parser.add_argument("--port",  help="Serial port of ESP-Now bridge")
    parser.add_argument("--baud",  type=int, default=115200)
    parser.add_argument("--host",  default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=5000)
    parser.add_argument("--song-dir",  help="Path to song directory for beat analysis and playback")
    parser.add_argument("--noupdate", default=False, action='store_true', help="Disable pip install on start")
    args = parser.parse_args()

    if not args.noupdate:
        import subprocess, sys
        req_file = 'requirements.txt'
        if os.path.exists(req_file):
            print("Installing requirements using python ", sys.executable)
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', req_file])
            print("Requirements installed.")

    import core.controller as ctrl #only import our deps after pip install

    if ctrl.reader or (os.environ.get("WERKZEUG_RUN_MAIN") != "true"):
        log.info("Reloader parent process detected, skipping serial init...")
    elif args.port:
        ctrl.init_reader(args.port, args.baud)
    else: log.warning("--no-serial: running without serial port (UI development mode)")

    for d in ['songs', '../songs']:
        if os.path.isdir(d):
            args.song_dir = d
            break
    if args.song_dir:
        log.info(f"Loading songs from {args.song_dir}")
        ctrl.media_player.load_songs(args.song_dir)

    import routes
    configure_all_module(routes, app)

    log.info(f"Starting Flask on {args.host}:{args.http_port}")
    app.run(host=args.host, port=args.http_port, threaded=True, use_reloader=True)

if __name__ == "__main__":
    main()
