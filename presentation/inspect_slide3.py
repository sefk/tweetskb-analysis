"""Print all slides with all text, no truncation. Also check slide 17."""
from slides_helpers import get_services, PRESENTATION_ID

slides_svc, _ = get_services()
pres = slides_svc.presentations().get(presentationId=PRESENTATION_ID).execute()

print(f"Total slides: {len(pres['slides'])}\n")

for i, slide in enumerate(pres["slides"]):
    oid = slide["objectId"]
    all_texts = []
    for element in slide.get("pageElements", []):
        eid = element.get("objectId", "?")
        shape = element.get("shape", {})
        image = element.get("image", {})
        runs = shape.get("text", {}).get("textElements", [])
        text = "".join(r.get("textRun", {}).get("content", "") for r in runs)
        if text.strip():
            all_texts.append(f"  [{eid}] {repr(text)}")
        elif image:
            all_texts.append(f"  [{eid}] (IMAGE)")

    print(f"Slide {i+1} [{oid}]:")
    if all_texts:
        for t in all_texts:
            print(t)
    else:
        print("  (no text or image elements found)")
    print()
