#!/usr/bin/env python3
"""Export TweetsKB Analysis tab charts to Google Slides.

Usage:
  python export_slides.py
  python export_slides.py <presentation_id_or_url>

Run from the tweetskb-analysis project directory.

Prerequisites (install if needed):
  pip install kaleido google-api-python-client google-auth-oauthlib google-auth-httplib2

Auth credentials: ~/.config/tweetskb-slides/credentials.json
Cached token:     ~/.config/tweetskb-slides/token.json
"""

import os
import re
import sys
import tempfile
from pathlib import Path

import plotly.io as pio

from slides_helpers import (
    PRESENTATION_ID,
    SLIDE_W, SLIDE_H, TITLE_H, DESC_H, MARGIN,
    get_services, upload_image,
    _uid, _emu, _pt, _rgb, _DARK, _GREY,
)


# ── Slide definitions ─────────────────────────────────────────────────────────

_DESC_CRYPTO = (
    "NFT went from near-zero to 2.76 M posts in 2022, then fell ~52% on an "
    "annualized basis in 2023. Bitcoin and Ethereum grew "
    "steadily from 2013; Doge spiked in 2021 with the Elon Musk attention wave. "
    "Web3 and DeFi appeared only in 2021 and, unlike NFTs, were tracking higher "
    "in H1 2023 than in full-year 2022 — the NFT bubble burst, but broader "
    "crypto discourse did not."
)
_DESC_POP = (
    "Wordle peaked at ~100 K posts in early 2022 then lost 97.5% of its volume "
    "in 16 months — a textbook viral-game arc. "
    "BTS started with just 4 posts in Jan 2013, grew steadily, and peaked at "
    "~903 K posts in May 2017 as the group broke into the global mainstream, "
    "demonstrating sustained K-pop fandom amplification."
)
_DESC_COVID = (
    '"COVID 19" appeared in Feb 2020, exploded to 194 K posts in Apr 2020, then '
    "faded over 3 years as news fatigue set in. Net sentiment (positive − negative) "
    "was negative throughout, but steadily improved as volume declined — reaching its "
    "least-negative point (~−0.03) in late 2021 through early 2022, before drifting "
    "more negative again as variants and pandemic exhaustion dominated discourse."
)
_DESC_SENTIMENT = (
    "Among the top 200 entities by volume, Tigray (Ethiopian civil war) and ISIS "
    "score most negatively; 'laughing' scores negative because it often appears as "
    "'laughing stock'. On the growth side, crypto terms (NFT, web3, ethereum) "
    "dominate the fastest-growing entities from 2020–2023, while Wordle and COVID "
    "are the fastest-declining on a normalized, annualized basis."
)
_DESC_PARTY = (
    "Animated scatter in sentiment space (positive vs. negative sentiment). "
    "Bubble size = post volume. Use the date-slider and bool-filters above "
    "to narrow the scope."
)

SLIDES = [
    {"section": "Crypto & NFT Bubble",              "desc": _DESC_CRYPTO,    "attr": "_fig_crypto",    "w": 1600, "h": 780},
    {"section": "Pop Culture Moments",              "desc": _DESC_POP,       "attr": "_fig_wordle",    "w": 1400, "h": 700},
    {"section": "Pop Culture Moments",              "desc": _DESC_POP,       "attr": "_fig_bts",       "w": 1400, "h": 700},
    {"section": "COVID-19 Timeline",                "desc": _DESC_COVID,     "attr": "_fig_covid",     "w": 1600, "h": 800},
    {"section": "Entity Sentiment & Growth Trends", "desc": _DESC_SENTIMENT, "attr": "_fig_sentiment", "w": 1300, "h": 900},
    {"section": "Entity Sentiment & Growth Trends", "desc": _DESC_SENTIMENT, "attr": "_fig_growth",    "w": 1300, "h": 900},
    {"section": "Democrats vs. Republicans",        "desc": _DESC_PARTY,     "attr": "_dem_rep",       "w": 1500, "h": 900},
]


# ── Figure rendering ──────────────────────────────────────────────────────────

def _render_figures(tmpdir: Path) -> list[dict]:
    """Import dashboard.py, render all Analysis charts to PNG files."""
    sys.path.insert(0, os.getcwd())
    import dashboard  # loaded from the tweetskb-analysis directory

    # Generate the Democrats vs. Republicans scatter with full date range and
    # default filters (classified=True, redacted=excluded).
    dem_rep_fig = dashboard.update_compare_dem_rep(
        [0, len(dashboard.ALL_MONTHS) - 1],
        dashboard._BOOL_DEFAULTS,
    )

    specs = []
    for i, slide in enumerate(SLIDES):
        fig = dem_rep_fig if slide["attr"] == "_dem_rep" else getattr(dashboard, slide["attr"])
        path = tmpdir / f"slide_{i + 1:02d}.png"
        pio.write_image(fig, str(path), width=slide["w"], height=slide["h"], scale=2)
        print(f"  [{i + 1}/{len(SLIDES)}] Rendered {path.name}  —  {slide['section']}")
        specs.append({**slide, "fig": fig, "png_path": str(path)})

    return specs


# ── Slide population ──────────────────────────────────────────────────────────

def _slide_requests(slide_id: str, title_id: str, desc_id: str, image_id: str,
                    section: str, description: str, image_url: str) -> list[dict]:
    desc_top = MARGIN // 2 + TITLE_H
    img_top  = desc_top + DESC_H + MARGIN
    img_h    = SLIDE_H - img_top - MARGIN
    return [
        # ── Title ──────────────────────────────────────────────────────────────
        {
            "createShape": {
                "objectId": title_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": _emu(SLIDE_W - 2 * MARGIN), "height": _emu(TITLE_H)},
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": MARGIN, "translateY": MARGIN // 2,
                        "unit": "EMU",
                    },
                },
            },
        },
        {"insertText": {"objectId": title_id, "text": section}},
        {
            "updateTextStyle": {
                "objectId": title_id,
                "style": {"fontSize": _pt(28), "bold": True, "foregroundColor": _rgb(_DARK)},
                "fields": "fontSize,bold,foregroundColor",
                "textRange": {"type": "ALL"},
            },
        },
        # ── Description ────────────────────────────────────────────────────────
        {
            "createShape": {
                "objectId": desc_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": _emu(SLIDE_W - 2 * MARGIN), "height": _emu(DESC_H)},
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": MARGIN, "translateY": desc_top,
                        "unit": "EMU",
                    },
                },
            },
        },
        {"insertText": {"objectId": desc_id, "text": description}},
        {
            "updateTextStyle": {
                "objectId": desc_id,
                "style": {"fontSize": _pt(13), "foregroundColor": _rgb(_GREY)},
                "fields": "fontSize,foregroundColor",
                "textRange": {"type": "ALL"},
            },
        },
        # ── Chart image ────────────────────────────────────────────────────────
        {
            "createImage": {
                "objectId": image_id,
                "url": image_url,
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": _emu(SLIDE_W), "height": _emu(img_h)},
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": 0, "translateY": img_top,
                        "unit": "EMU",
                    },
                },
            },
        },
    ]


# ── Main upload ───────────────────────────────────────────────────────────────

def _push_to_slides(specs: list[dict], presentation_id: str | None) -> str:
    slides_svc, drive_svc = get_services()

    # Create or open the presentation
    if presentation_id:
        pres    = slides_svc.presentations().get(presentationId=presentation_id).execute()
        old_ids = [s["objectId"] for s in pres.get("slides", [])]
        print(f"  Updating existing presentation ({len(old_ids)} slide(s) will be replaced)")
    else:
        pres = slides_svc.presentations().create(body={
            "title": "TweetsKB Analysis",
            "pageSize": {
                "width":  {"magnitude": SLIDE_W, "unit": "EMU"},
                "height": {"magnitude": SLIDE_H, "unit": "EMU"},
            },
        }).execute()
        presentation_id = pres["presentationId"]
        old_ids = [s["objectId"] for s in pres.get("slides", [])]  # one blank slide on creation
        print(f"  Created new presentation: {presentation_id}")

    # Add new slides
    for i, spec in enumerate(specs):
        slide_id = _uid("slide")
        title_id = _uid("title")
        desc_id  = _uid("desc")
        image_id = _uid("img")

        print(f"  [{i + 1}/{len(specs)}] Uploading image…")
        image_url = upload_image(drive_svc, spec["png_path"])

        slides_svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [
                {"createSlide": {
                    "objectId": slide_id,
                    "slideLayoutReference": {"predefinedLayout": "BLANK"},
                }},
            ]},
        ).execute()

        slides_svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": _slide_requests(slide_id, title_id, desc_id, image_id,
                                              spec["section"], spec["desc"], image_url)},
        ).execute()

    # Delete old slides (after new ones exist, so the deck is never empty)
    if old_ids:
        slides_svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"deleteObject": {"objectId": oid}} for oid in old_ids]},
        ).execute()

    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    presentation_id = None
    if arg:
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", arg)
        presentation_id = m.group(1) if m else arg

    if not Path("dashboard.py").exists():
        sys.exit("ERROR: dashboard.py not found. Run this from the tweetskb-analysis directory.")

    tmpdir = Path(tempfile.mkdtemp(prefix="tweetskb_slides_"))
    print(f"\nRendering figures → {tmpdir}")
    specs = _render_figures(tmpdir)

    print(f"\nPushing {len(specs)} slides to Google Slides…")
    url = _push_to_slides(specs, presentation_id)

    print(f"\nDone!\n{url}\n")


if __name__ == "__main__":
    main()
