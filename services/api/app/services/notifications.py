from app.models import NotificationEvent


def notify(db, ntype: str, title: str, body: str = "", severity: str = "info", opportunity_id=None):
    event = NotificationEvent(
        type=ntype,
        title=title,
        body=body,
        severity=severity,
        opportunity_id=opportunity_id,
    )
    db.add(event)
    db.commit()
    return event
