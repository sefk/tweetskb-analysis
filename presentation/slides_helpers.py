"""Helpers for adding slides to the TweetsKB presentation.

Presentation:
  https://docs.google.com/presentation/d/1foF5n95BJadZ3fQEziQO697c3KwIVdSr7Vd2XcmAElg/edit

Public API
----------
add_chart_slide(fig, title, description="", ...)
    Render a Plotly figure as a PNG and add it as a new slide.

add_text_slide(title, body, ...)
    Add a title + bulleted-text slide (newlines → bullet points).

add_table_slide(title, df, description="", ...)
    Add a table slide from a pandas DataFrame.

All three default to PRESENTATION_ID and append at the end of the deck.
Pass position=N (0-based) to insert at a specific index instead.
"""

import tempfile
import uuid
from pathlib import Path

import plotly.io as pio

# ── Target presentation ────────────────────────────────────────────────────────

PRESENTATION_ID = "1foF5n95BJadZ3fQEziQO697c3KwIVdSr7Vd2XcmAElg"

# ── Auth ───────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
]

_CREDS_DIR  = Path.home() / ".config" / "tweetskb-slides"
_CREDS_FILE = _CREDS_DIR / "credentials.json"
_TOKEN_FILE = _CREDS_DIR / "token.json"


def get_services():
    """Return an authenticated (slides_service, drive_service) tuple."""
    import sys
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                sys.exit(
                    f"\nERROR: Credentials file not found: {_CREDS_FILE}\n\n"
                    "Setup:\n"
                    "  1. Google Cloud Console → select or create a project\n"
                    "  2. APIs & Services → enable Google Slides API + Google Drive API\n"
                    "  3. Credentials → Create OAuth 2.0 Client ID (type: Desktop app)\n"
                    f"  4. Download JSON → save as {_CREDS_FILE}\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        _CREDS_DIR.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json())

    return build("slides", "v1", credentials=creds), build("drive", "v3", credentials=creds)


# ── Drive ──────────────────────────────────────────────────────────────────────

def upload_image(drive_svc, path: str) -> str:
    """Upload a PNG to Drive (public-read) and return a fetchable URL."""
    from googleapiclient.http import MediaFileUpload

    fid = drive_svc.files().create(
        body={"name": Path(path).name},
        media_body=MediaFileUpload(path, mimetype="image/png", resumable=False),
        fields="id",
    ).execute()["id"]
    drive_svc.permissions().create(
        fileId=fid, body={"type": "anyone", "role": "reader"}
    ).execute()
    return f"https://drive.google.com/uc?id={fid}"


# ── Layout constants ───────────────────────────────────────────────────────────

# 16:9 at 914400 EMU/inch — 10 × 5.625 inches
SLIDE_W = 9144000
SLIDE_H = 5143500
TITLE_H = 550000   # ~0.6 inch bold title bar
DESC_H  = 500000   # ~0.55 inch description block
MARGIN  = 100000

_DARK = {"red": 0.13, "green": 0.13, "blue": 0.13}
_GREY = {"red": 0.33, "green": 0.33, "blue": 0.33}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _uid(prefix="obj"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _emu(n):
    return {"magnitude": n, "unit": "EMU"}


def _pt(n):
    return {"magnitude": n, "unit": "PT"}


def _rgb(d):
    return {"opaqueColor": {"rgbColor": d}}


def _create_blank_slide(slides_svc, presentation_id, position=None):
    slide_id = _uid("slide")
    req = {
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": "BLANK"},
        }
    }
    if position is not None:
        req["createSlide"]["insertionIndex"] = position
    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": [req]}
    ).execute()
    return slide_id


def _title_requests(slide_id, title):
    tid = _uid("title")
    return [
        {
            "createShape": {
                "objectId": tid,
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
            }
        },
        {"insertText": {"objectId": tid, "text": title}},
        {
            "updateTextStyle": {
                "objectId": tid,
                "style": {"fontSize": _pt(28), "bold": True, "foregroundColor": _rgb(_DARK)},
                "fields": "fontSize,bold,foregroundColor",
                "textRange": {"type": "ALL"},
            }
        },
    ]


def _desc_requests(slide_id, description, top):
    did = _uid("desc")
    return [
        {
            "createShape": {
                "objectId": did,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": _emu(SLIDE_W - 2 * MARGIN), "height": _emu(DESC_H)},
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": MARGIN, "translateY": top,
                        "unit": "EMU",
                    },
                },
            }
        },
        {"insertText": {"objectId": did, "text": description}},
        {
            "updateTextStyle": {
                "objectId": did,
                "style": {"fontSize": _pt(13), "foregroundColor": _rgb(_GREY)},
                "fields": "fontSize,foregroundColor",
                "textRange": {"type": "ALL"},
            }
        },
    ]


def _present_url(presentation_id):
    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


# ── Public API ─────────────────────────────────────────────────────────────────

def add_chart_slide(fig, title, description="",
                    presentation_id=PRESENTATION_ID, position=None,
                    img_width=1600, img_height=900):
    """Render a Plotly figure and add it as a new slide.

    Args:
        fig:             Plotly or Matplotlib Figure object.
        title:           Slide title (bold, large).
        description:     Optional body text shown below the title.
        presentation_id: Target presentation ID (defaults to the TweetsKB deck).
        position:        0-based insertion index; None = append at end.
        img_width/height: PNG render size in pixels (scale=2 for retina).

    Returns:
        URL of the presentation.
    """
    slides_svc, drive_svc = get_services()

    tmp = Path(tempfile.mkdtemp(prefix="slide_chart_")) / "chart.png"
    try:
        import matplotlib.figure as _mpl
        if isinstance(fig, _mpl.Figure):
            fig.savefig(str(tmp), dpi=150, bbox_inches='tight', facecolor='white')
        else:
            pio.write_image(fig, str(tmp), width=img_width, height=img_height, scale=2)
    except ImportError:
        pio.write_image(fig, str(tmp), width=img_width, height=img_height, scale=2)
    image_url = upload_image(drive_svc, str(tmp))

    slide_id = _create_blank_slide(slides_svc, presentation_id, position)

    desc_top = MARGIN // 2 + TITLE_H
    img_top  = (desc_top + DESC_H + MARGIN) if description else (desc_top + MARGIN)
    img_h    = SLIDE_H - img_top - MARGIN

    requests = _title_requests(slide_id, title)
    if description:
        requests += _desc_requests(slide_id, description, desc_top)
    requests += [{
        "createImage": {
            "objectId": _uid("img"),
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
        }
    }]

    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": requests}
    ).execute()
    print(f"Added chart slide: {title!r}")
    return _present_url(presentation_id)


def add_text_slide(title, body, presentation_id=PRESENTATION_ID, position=None):
    """Add a title + body text slide. Newline-separated lines become bullet points.

    Args:
        title:           Slide title (bold, large).
        body:            Body text; each newline-separated item becomes a bullet.
        presentation_id: Target presentation ID (defaults to the TweetsKB deck).
        position:        0-based insertion index; None = append at end.

    Returns:
        URL of the presentation.
    """
    slides_svc, _ = get_services()
    slide_id = _create_blank_slide(slides_svc, presentation_id, position)

    body_top = MARGIN // 2 + TITLE_H + MARGIN
    body_h   = SLIDE_H - body_top - MARGIN
    bid = _uid("body")

    requests = _title_requests(slide_id, title)
    requests += [
        {
            "createShape": {
                "objectId": bid,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": _emu(SLIDE_W - 2 * MARGIN), "height": _emu(body_h)},
                    "transform": {
                        "scaleX": 1, "scaleY": 1,
                        "translateX": MARGIN, "translateY": body_top,
                        "unit": "EMU",
                    },
                },
            }
        },
        {"insertText": {"objectId": bid, "text": body}},
        {
            "updateTextStyle": {
                "objectId": bid,
                "style": {"fontSize": _pt(18), "foregroundColor": _rgb(_DARK)},
                "fields": "fontSize,foregroundColor",
                "textRange": {"type": "ALL"},
            }
        },
        {
            "createParagraphBullets": {
                "objectId": bid,
                "textRange": {"type": "ALL"},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }
        },
    ]

    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": requests}
    ).execute()
    print(f"Added text slide: {title!r}")
    return _present_url(presentation_id)


def add_table_slide(title, df, description="",
                    presentation_id=PRESENTATION_ID, position=None):
    """Add a table slide from a pandas DataFrame.

    Args:
        title:           Slide title (bold, large).
        df:              DataFrame to display; pre-filter rows and columns.
        description:     Optional text shown between the title and the table.
        presentation_id: Target presentation ID (defaults to the TweetsKB deck).
        position:        0-based insertion index; None = append at end.

    Returns:
        URL of the presentation.
    """
    slides_svc, _ = get_services()
    slide_id = _create_blank_slide(slides_svc, presentation_id, position)

    desc_top  = MARGIN // 2 + TITLE_H
    table_top = (desc_top + DESC_H + MARGIN * 2) if description else (desc_top + MARGIN)
    table_h   = SLIDE_H - table_top - MARGIN
    nrows, ncols = len(df) + 1, len(df.columns)  # +1 for header
    tid = _uid("table")

    requests = _title_requests(slide_id, title)
    if description:
        requests += _desc_requests(slide_id, description, desc_top)
    requests += [{
        "createTable": {
            "objectId": tid,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": {"width": _emu(SLIDE_W - 2 * MARGIN), "height": _emu(table_h)},
                "transform": {
                    "scaleX": 1, "scaleY": 1,
                    "translateX": MARGIN, "translateY": table_top,
                    "unit": "EMU",
                },
            },
            "rows": nrows,
            "columns": ncols,
        }
    }]

    # createTable must be its own batchUpdate before cells can be filled
    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": requests}
    ).execute()

    header = [str(c) for c in df.columns]
    data_rows = [[str(v) for v in row] for row in df.itertuples(index=False)]
    cell_requests = []
    for ri, row_vals in enumerate([header] + data_rows):
        for ci, text in enumerate(row_vals):
            cell_requests += [
                {
                    "insertText": {
                        "objectId": tid,
                        "cellLocation": {"rowIndex": ri, "columnIndex": ci},
                        "text": text,
                        "insertionIndex": 0,
                    }
                },
                {
                    "updateTextStyle": {
                        "objectId": tid,
                        "cellLocation": {"rowIndex": ri, "columnIndex": ci},
                        "style": {"bold": ri == 0, "fontSize": _pt(11)},
                        "fields": "bold,fontSize",
                        "textRange": {"type": "ALL"},
                    }
                },
            ]

    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": cell_requests}
    ).execute()
    print(f"Added table slide: {title!r}  ({nrows - 1} rows × {ncols} cols)")
    return _present_url(presentation_id)
