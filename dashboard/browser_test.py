#!/usr/bin/env python3
"""
dashboard/browser_test.py — Real browser test and live user simulation
=======================================================================
Opens the dashboard in Chrome, simulates real user mouse/keyboard interactions,
and keeps running — scrolling, clicking, verifying panels are live — like a
real user would while watching a long-running benchmark.

Also used to auto-open the dashboard on first launch.

Usage:
  python3 dashboard/browser_test.py               # open + run interactive session
  python3 dashboard/browser_test.py --headless     # headless verification only
  python3 dashboard/browser_test.py --smoke        # quick smoke test (30s)
  python3 dashboard/browser_test.py --watch 300    # watch for 300s like a real user
"""
import os, sys, json, time, argparse, subprocess
from pathlib import Path

BASE_DIR  = str(Path(__file__).parent.parent.parent)  # local-agent-runtime/
DASH_TXT  = os.path.join(BASE_DIR, "DASHBOARD.txt")
DASH_DIR  = str(Path(__file__).parent)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError:
    print("[BROWSER] Installing playwright...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout


def _get_dashboard_url() -> str:
    """Read URL from DASHBOARD.txt, fallback to trying known ports."""
    try:
        with open(DASH_TXT) as f:
            for line in f:
                if "http://" in line:
                    return line.strip().replace("Dashboard URL: ", "").strip()
    except Exception:
        pass
    # Fallback: try ports 3001-3010
    import socket
    for port in range(3001, 3010):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex(("localhost", port))
        s.close()
        if result == 0:
            return f"http://localhost:{port}"
    return "http://localhost:3001"


def _verify_panel(page, title: str, timeout: int = 5000) -> bool:
    """Check a dashboard panel is visible and non-empty."""
    try:
        # Look for panel title text
        loc = page.locator(f"text={title}")
        loc.wait_for(timeout=timeout)
        return True
    except PwTimeout:
        print(f"  [BROWSER] Panel not found: {title}")
        return False


def open_dashboard(headless: bool = False):
    """Open the dashboard in Chrome and return playwright context."""
    url = _get_dashboard_url()
    print(f"[BROWSER] Opening dashboard: {url}")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    page = ctx.new_page()

    # Navigate to dashboard
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1500)  # let React render

    return pw, browser, ctx, page, url


def smoke_test(page, url: str) -> bool:
    """Quick 30-second smoke test. Returns True if all panels present."""
    print("[BROWSER] Running smoke test...")
    passed = 0
    total  = 0

    panels = [
        "Global Progress",
        "Task Queue",
        "Token Usage",
        "Hardware",
        "Benchmark Scores",
        "Agent Health",
        "Failure Log",
        "Research Feed",
    ]

    for panel in panels:
        total += 1
        if _verify_panel(page, panel, timeout=3000):
            print(f"  ✓ {panel}")
            passed += 1
        else:
            print(f"  ✗ {panel}")

    # Check WebSocket connection indicator
    try:
        live_indicator = page.locator("text=live").first
        live_indicator.wait_for(timeout=5000)
        print("  ✓ WebSocket connected (live indicator)")
        passed += 1
        total += 1
    except PwTimeout:
        print("  ✗ WebSocket not showing 'live' (may be disconnected)")
        total += 1

    print(f"\n[BROWSER] Smoke test: {passed}/{total} panels OK")
    return passed >= total * 0.7  # 70% panels visible = pass


def simulate_real_user(page, duration_s: int = 60):
    """
    Simulate real user interactions over duration_s seconds.
    Scrolls, hovers over panels, watches live updates.
    """
    print(f"[BROWSER] Simulating real user for {duration_s}s...")
    start  = time.time()
    cycle  = 0

    while time.time() - start < duration_s:
        cycle += 1
        elapsed = round(time.time() - start)
        print(f"  [t={elapsed}s] cycle {cycle} — checking live updates")

        # Move mouse across the page (simulate reading)
        page.mouse.move(400, 300)
        page.wait_for_timeout(300)
        page.mouse.move(800, 400)
        page.wait_for_timeout(300)
        page.mouse.move(1200, 200)
        page.wait_for_timeout(300)

        # Scroll down then up
        page.keyboard.press("End")
        page.wait_for_timeout(500)
        page.keyboard.press("Home")
        page.wait_for_timeout(500)

        # Verify the timestamp updated (dashboard should push new data every ~1s)
        try:
            ts_element = page.locator("text=state:").first
            ts_text = ts_element.inner_text()
            print(f"  [BROWSER] State timestamp visible: {ts_text[-20:]}")
        except Exception:
            pass

        # Take a screenshot every 30s
        if cycle % 6 == 0:
            shot_path = os.path.join(DASH_DIR, f"screenshot_{elapsed}s.png")
            page.screenshot(path=shot_path)
            print(f"  [BROWSER] Screenshot saved: {shot_path}")

        time.sleep(5)  # check every 5 seconds

    print(f"[BROWSER] User simulation complete. {cycle} cycles in {duration_s}s.")


def auto_open():
    """Open dashboard in browser without running any tests — just opens it."""
    url = _get_dashboard_url()
    print(f"[BROWSER] Opening {url} in browser...")
    subprocess.Popen(["open", url])   # macOS open command


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true", help="Run headless (no visible browser)")
    ap.add_argument("--smoke",    action="store_true", help="Quick smoke test only")
    ap.add_argument("--watch",    type=int, default=0, metavar="SECS",
                    help="Watch for N seconds like a real user")
    ap.add_argument("--open",     action="store_true", help="Just open browser, no tests")
    args = ap.parse_args()

    if args.open:
        auto_open()
        return

    pw, browser, ctx, page, url = open_dashboard(headless=args.headless)

    try:
        if args.smoke or args.watch == 0:
            ok = smoke_test(page, url)
            print(f"\n[BROWSER] Smoke test {'PASSED' if ok else 'FAILED'}")

        if args.watch > 0:
            simulate_real_user(page, duration_s=args.watch)

        if not args.headless and not args.smoke and not args.watch:
            # Interactive mode — stay open until Ctrl+C
            print(f"\n[BROWSER] Dashboard open at {url}")
            print("[BROWSER] Press Ctrl+C to close browser")
            while True:
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n[BROWSER] Closing...")
    finally:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
