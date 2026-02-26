"""One-off: replace slide 4 with a live screenshot of the dashboard."""

import base64
import json
import subprocess
import sys
import time
import uuid

import requests

from slides_helpers import get_services, upload_image, PRESENTATION_ID, SLIDE_W, SLIDE_H

DASHBOARD_URL = (
    "http://localhost:8050/"
    "?tab=entity&entities=red+sox%2Castros"
)
SCREENSHOT_PATH = "/tmp/dashboard_redsox.png"
SLIDE_INDEX = 3          # 0-based → slide 4
CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
DEBUG_PORT = 9223        # use 9223 to avoid clashing with any open browser


# ── 1. Capture dashboard screenshot via CDP ────────────────────────────────────

print("Launching headless Chrome …")
chrome = subprocess.Popen(
    [
        CHROME,
        "--headless=new",
        f"--remote-debugging-port={DEBUG_PORT}",
        "--window-size=1600,900",
        "--hide-scrollbars",
        "--disable-gpu",
        "--remote-allow-origins=*",
        "about:blank",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

try:
    # Give Chrome a moment to start its debugger
    for _ in range(10):
        time.sleep(1)
        try:
            targets = requests.get(
                f"http://localhost:{DEBUG_PORT}/json", timeout=2
            ).json()
            break
        except Exception:
            pass
    else:
        sys.exit("Chrome debugger didn't start in time")

    ws_url = next(
        t["webSocketDebuggerUrl"]
        for t in targets
        if t.get("type") == "page"
    )

    import websocket

    ws = websocket.WebSocket()
    ws.connect(ws_url)
    ws.settimeout(60)

    _mid = [0]

    def cdp(method, params=None):
        _mid[0] += 1
        cur = _mid[0]
        ws.send(json.dumps({"id": cur, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == cur:
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error']}")
                return msg.get("result", {})

    print(f"Navigating to dashboard …")
    cdp("Page.navigate", {"url": DASHBOARD_URL})

    # Dash callbacks run over WebSocket, so network-idle won't catch them.
    # Poll window.location.search until sync_url has written the Red Sox URL
    # back to the address bar (confirms entity-select finished initialising).
    EXPECTED = "red"    # "red+sox" or "red%20sox" – either encoding works
    JS_CHECK = "window.location.search"
    print(f"Polling window.location.search for '{EXPECTED}' (up to 40 s) …")
    ws.settimeout(2.0)
    deadline = time.time() + 40
    found = False
    while time.time() < deadline:
        # Drain any pending CDP events so the call-id counter stays in sync
        try:
            while True:
                json.loads(ws.recv())
        except Exception:
            pass
        ws.settimeout(60)
        result = cdp("Runtime.evaluate", {"expression": JS_CHECK, "returnByValue": True})
        search_text = result.get("result", {}).get("value", "")
        print(f"  location.search: {search_text[:120]}")
        if EXPECTED in search_text.lower():
            found = True
            break
        ws.settimeout(2.0)
        time.sleep(2)

    if not found:
        print("WARNING: timed out waiting for Red Sox entities; screenshot may show defaults")

    ws.settimeout(60)
    time.sleep(3)    # extra buffer for Plotly to finish painting the charts

    print("Taking screenshot …")
    result = cdp("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    with open(SCREENSHOT_PATH, "wb") as f:
        f.write(base64.b64decode(result["data"]))
    print(f"Screenshot saved → {SCREENSHOT_PATH}")

    ws.close()
finally:
    chrome.terminate()
    chrome.wait()


# ── 2. Replace slide 4 in the presentation ────────────────────────────────────

print("Authenticating with Google …")
slides_svc, drive_svc = get_services()

pres = slides_svc.presentations().get(presentationId=PRESENTATION_ID).execute()
slides = pres["slides"]
if len(slides) <= SLIDE_INDEX:
    sys.exit(f"Presentation only has {len(slides)} slide(s); slide 4 doesn't exist")

slide = slides[SLIDE_INDEX]
slide_id = slide["objectId"]
elements = slide.get("pageElements", [])
print(f"Slide 4 id={slide_id!r}, existing elements: {[e['objectId'] for e in elements]}")

# Delete every existing element on slide 4
if elements:
    slides_svc.presentations().batchUpdate(
        presentationId=PRESENTATION_ID,
        body={"requests": [
            {"deleteObject": {"objectId": e["objectId"]}} for e in elements
        ]},
    ).execute()
    print(f"Deleted {len(elements)} element(s)")

# Upload screenshot and place it full-bleed on the slide
print("Uploading screenshot to Drive …")
image_url = upload_image(drive_svc, SCREENSHOT_PATH)

slides_svc.presentations().batchUpdate(
    presentationId=PRESENTATION_ID,
    body={"requests": [{
        "createImage": {
            "objectId": f"img_{uuid.uuid4().hex[:12]}",
            "url": image_url,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": {
                    "width":  {"magnitude": SLIDE_W, "unit": "EMU"},
                    "height": {"magnitude": SLIDE_H, "unit": "EMU"},
                },
                "transform": {
                    "scaleX": 1, "scaleY": 1,
                    "translateX": 0, "translateY": 0,
                    "unit": "EMU",
                },
            },
        }
    }]},
).execute()

print(
    "Done! https://docs.google.com/presentation/d/"
    f"{PRESENTATION_ID}/edit#slide=id.{slide_id}"
)
