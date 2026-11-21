"""Entry point: `python3 -m lora_tunnel_zero` (installed as /usr/share/APPLaunch/bin/lora-tunnel)."""

import argparse
import os
import signal
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lora-tunnel", description="LORA Tunnel for M5Stack CardputerZero")
    parser.add_argument("--demo", action="store_true", help="use the synthetic receiver (no cap needed)")
    parser.add_argument("--png", metavar="FILE", help="draw frames to a PNG file instead of /dev/fb0")
    parser.add_argument("--no-splash", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)

    from . import config as configuration
    from .engine import Engine
    from .ui.app import App
    from .ui.keys import EvdevInput

    try:
        cfg = configuration.load()
    except configuration.ConfigError as exc:
        print("Configuration problem: %s. Using defaults for this run." % exc, file=sys.stderr)
        cfg = dict(configuration.DEFAULTS)
    if args.demo:
        cfg["backend"] = "demo"
        cfg["region"] = cfg.get("region") or "US"

    if args.png:
        from .ui.display import PNGDisplay
        display = PNGDisplay(args.png, scale=2)
    else:
        from .ui.display import FramebufferDisplay
        try:
            display = FramebufferDisplay()
        except OSError as exc:
            print("Cannot open the framebuffer (%s). Is this a CardputerZero?" % exc, file=sys.stderr)
            return 2

    keyboard = EvdevInput()
    engine = Engine(cfg)
    engine.start_gps()
    app = App(display, keyboard, engine, cfg, splash=not args.no_splash)

    def stop(*_):
        app.running = False
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        app.run()
    finally:
        keyboard.close()
        display.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
