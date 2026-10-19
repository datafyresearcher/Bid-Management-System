import re

from app.models import Lead
from app.services import audit, notifications
from app.services.utils import parse_amount


def _parse_file(path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    data = {}
    body_lines = []
    current = None
    for line in lines:
        m = re.match(r"^(Subject|From|Buyer|Window|Expected Window|Value|Estimated Value|Category|Area|Confidence|Body)\s*:\s*(.*)$", line, re.I)
        if m:
            current = m.group(1).lower()
            data[current] = m.group(2).strip()
        elif current:
            body_lines.append(line)
    if body_lines:
        data["body"] = "\n".join(body_lines).strip()
    if not data.get("subject"):
        return None
    return data


def import_leads(db, source) -> int:
    if not source:
        return 0
    from app.config import fixtures_dir

    folder = fixtures_dir() / source.code
    if not folder.exists():
        return 0
    created = 0
    for path in sorted(folder.glob("*.txt")):
        parsed = _parse_file(path)
        if not parsed:
            continue
        title = parsed["subject"]
        exists = db.execute(Lead.__table__.select().where(Lead.title == title)).first()
        if exists:
            continue
        db.add(
            Lead(
                source_code=source.code,
                source_label=source.name,
                buyer=parsed.get("buyer") or parsed.get("from", ""),
                title=title,
                description=parsed.get("body", ""),
                category_internal=parsed.get("category", "General") or "General",
                area=parsed.get("area", source.area or ""),
                expected_window=parsed.get("window") or parsed.get("expected window", ""),
                estimated_value=parse_amount(parsed.get("value") or parsed.get("estimated value")),
                currency="PKR",
                confidence_tier=(parsed.get("confidence") or "Medium").capitalize(),
                confidence_note=f"Ingested from {path.name}",
                status="Signal",
                evidence={"file": path.name},
            )
        )
        created += 1
    db.commit()
    if created:
        audit.record(db, "leads.email_import", detail={"source": source.code, "created": created})
        notifications.notify(db, "lead", f"{created} lead(s) imported from {source.name}", "", severity="info")
    return created
