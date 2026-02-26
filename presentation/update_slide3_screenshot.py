"""Replace the dashboard screenshot image on slide 3 with a fresh one (3-tab layout)."""

import base64
import json
import subprocess
import sys
import time
import uuid

import requests

from slides_helpers import get_services, upload_image, PRESENTATION_ID, SLIDE_W, SLIDE_H

DASHBOARD_URL = "http://localhost:8050/"
SCREENSHOT_PATH = "/tmp/dashboard_slide3.png"
SLIDE_INDEX = 2          # 0-based → slide 3
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT = 9224        # avoid clashing with other browsers


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

    print("Navigating to dashboard …")
    cdp("Page.navigate", {"url": DASHBOARD_URL})

    # Wait for Dash to finish rendering
    print("Waiting 8 s for Dash to render …")
    time.sleep(8)

    print("Taking screenshot …")
    result = cdp("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    with open(SCREENSHOT_PATH, "wb") as f:
        f.write(base64.b64decode(result["data"]))
    print(f"Screenshot saved → {SCREENSHOT_PATH}")

    ws.close()
finally:
    chrome.terminate()
    chrome.wait()


# ── 2. Find and replace the image on slide 3 ──────────────────────────────────

print("Authenticating with Google …")
slides_svc, drive_svc = get_services()

pres = slides_svc.presentations().get(presentationId=PRESENTATION_ID).execute()
slide = pres["slides"][SLIDE_INDEX]
slide_id = slide["objectId"]

# Find image elements on slide 3
image_elements = [
    e for e in slide.get("pageElements", [])
    if "image" in e
]
print(f"Slide 3 id={slide_id!r}, image elements: {[e['objectId'] for e in image_elements]}")

if not image_elements:
    sys.exit("No image elements found on slide 3 — nothing to replace.")

# Delete existing image(s)
slides_svc.presentations().batchUpdate(
    presentationId=PRESENTATION_ID,
    body={"requests": [
        {"deleteObject": {"objectId": e["objectId"]}} for e in image_elements
    ]},
).execute()
print(f"Deleted {len(image_elements)} image element(s)")

# Use the same size/position as the first image that was there
first_img = image_elements[0]
size = first_img["size"]
transform = first_img["transform"]

# Upload new screenshot and place it at the same position/size
print("Uploading new screenshot to Drive …")
image_url = upload_image(drive_svc, SCREENSHOT_PATH)

slides_svc.presentations().batchUpdate(
    presentationId=PRESENTATION_ID,
    body={"requests": [{
        "createImage": {
            "objectId": f"img_{uuid.uuid4().hex[:12]}",
            "url": image_url,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": size,
                "transform": transform,
            },
        }
    }]},
).execute()

print(
    "Done! https://docs.google.com/presentation/d/"
    f"{PRESENTATION_ID}/edit#slide=id.{slide_id}"
)
