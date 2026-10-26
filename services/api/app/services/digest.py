"""The ranked executive brief, and its delivery by email.

This is the step that turns a captured pipeline into a decision: the few
tenders worth attention, each with its score, its deadline and the gap that
closed screening — delivered as one message a bid manager reads before
breakfast, rather than an alert list they have to work through.

The digest is built from live database state every time it runs, so it is
idempotent: building it twice gives the same brief. Sending it records a
notification event, which is both the audit trail and the marker of the
last send — the "what is new" section counts from there.
"""

import logging
from datetime import timedelta

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import GateTask, NotificationEvent, Opportunity, User
from app.services import emailer
from app.services.utils import utcnow

logger = logging.getLogger("bms.digest")

# The states a tender can be in while a decision about it is still open.
# Screened-out and archived tenders are exactly the ones the digest exists
# to keep out of the reader's morning. Kept in step with the workflow's own
# set of active states.
DIGEST_STATES = (
    "SCORED", "GATE1", "DOCS_FETCHED", "ANALYZED", "GATE2",
    "DRAFTING", "GATE3", "ASSEMBLY", "GATE4", "READY_TO_SUBMIT", "GATE5",
)

WAITING_STATES = ("NORMALIZED", "SCORED")


def build_digest(db) -> dict:
    """Assemble the ranked brief from the current database state."""
    now = utcnow()
    soon = now + timedelta(hours=72)

    ranked = (
        db.execute(
            select(Opportunity)
            .where(Opportunity.state.in_(DIGEST_STATES), Opportunity.score_total != None)  # noqa: E711
            .order_by(Opportunity.score_total.desc())
            .limit(settings.digest_max_items)
        )
        .scalars()
        .all()
    )

    waiting = (
        db.execute(
            select(func.count())
            .select_from(Opportunity)
            .where(Opportunity.state.in_(WAITING_STATES))
        ).scalar()
        or 0
    )

    overdue_gates = (
        db.execute(
            select(func.count())
            .select_from(GateTask)
            .where(GateTask.status.in_(("PENDING", "OVERDUE")), GateTask.due_at < now)
        ).scalar()
        or 0
    )

    pending_gates = (
        db.execute(
            select(func.count()).select_from(GateTask).where(GateTask.status == "PENDING")
        ).scalar()
        or 0
    )

    closing = (
        db.execute(
            select(Opportunity)
            .where(
                Opportunity.state.in_(DIGEST_STATES),
                Opportunity.submission_deadline != None,  # noqa: E711
                Opportunity.submission_deadline >= now,
                Opportunity.submission_deadline <= soon,
            )
            .order_by(Opportunity.submission_deadline)
            .limit(5)
        )
        .scalars()
        .all()
    )

    last_sent = (
        db.execute(
            select(NotificationEvent.created_at)
            .where(NotificationEvent.type == "digest")
            .order_by(NotificationEvent.created_at.desc())
            .limit(1)
        ).scalar()
    )
    new_since = 0
    if last_sent:
        new_since = (
            db.execute(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.created_at >= last_sent)
            ).scalar()
            or 0
        )

    return {
        "built_at": now,
        "ranked": list(ranked),
        "closing": list(closing),
        "waiting": waiting,
        "overdue_gates": overdue_gates,
        "pending_gates": pending_gates,
        "new_since_last": new_since,
        "last_sent_at": last_sent,
    }


def render_text(digest: dict) -> str:
    """The plain-text form of the brief. Email clients render it everywhere."""
    lines = []
    lines.append("AHTE BMS — Executive Tender Digest")
    lines.append(f"Built {digest['built_at'].strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    if digest["ranked"]:
        lines.append(f"TOP TENDERS WORTH ATTENTION ({len(digest['ranked'])})")
        for o in digest["ranked"]:
            score = f"{o.score_total:.0f}/100" if o.score_total is not None else "unscored"
            deadline = o.submission_deadline.strftime("%Y-%m-%d") if o.submission_deadline else "—"
            lines.append(f"  [{score}] {o.title[:100]}")
            lines.append(f"          {o.buyer_name} · deadline {deadline} · state {o.state}")
            if o.estimated_value:
                lines.append(f"          value {o.currency} {o.estimated_value:,.0f}")
        lines.append("")
    else:
        lines.append("No tenders are waiting on a decision today.")
        lines.append("")

    if digest["closing"]:
        lines.append("CLOSING WITHIN 72 HOURS")
        for o in digest["closing"]:
            deadline = o.submission_deadline.strftime("%Y-%m-%d %H:%M") if o.submission_deadline else "?"
            lines.append(f"  {deadline} UTC — {o.title[:90]}")
        lines.append("")

    counts = []
    if digest["overdue_gates"]:
        counts.append(f"{digest['overdue_gates']} gate(s) past their SLA")
    if digest["pending_gates"]:
        counts.append(f"{digest['pending_gates']} gate(s) open")
    if digest["waiting"]:
        counts.append(f"{digest['waiting']} tender(s) awaiting triage")
    if counts:
        lines.append("PIPELINE: " + "; ".join(counts))
        lines.append("")

    lines.append("Open the dashboard for the full bid rooms and review queue.")
    return "\n".join(lines)


def recipients(db) -> list[str]:
    """Who the brief goes to.

    The digest is a management product. It goes to the configured list when
    one is set, and otherwise to the people whose roles own the decision —
    admin, bid managers and management. Whether anything is actually sent
    is decided by the sender, not here: the recipient list is the same
    regardless of whether this deployment has an SMTP account yet.
    """
    configured_list = (settings.digest_recipients or "").strip()
    if configured_list:
        return [addr for addr in (a.strip() for a in configured_list.split(",")) if addr]
    roles = ("admin", "bid_manager", "management")
    rows = db.execute(select(User.email).where(User.active == True, User.role.in_(roles))).all()  # noqa: E712
    return [r[0] for r in rows]


def send_digest(db=None) -> dict:
    """Build the brief and email it. Returns what happened, for the caller.

    Without an SMTP account this still records that a digest was due, so the
    dashboard history shows the digests were produced even when they could
    only be read in the app.
    """
    own = db is None
    if own:
        db = SessionLocal()
    try:
        digest = build_digest(db)
        text = render_text(digest)
        sent = False
        to = recipients(db)
        if settings.digest_enabled and to:
            sent = emailer.send_email(to, "AHTE BMS — daily tender digest", text)
        db.add(
            NotificationEvent(
                type="digest",
                title=f"Digest: {len(digest['ranked'])} tender(s) ranked, sent={sent}",
                body=text[:4000],
                severity="info",
            )
        )
        db.commit()
        logger.info("Digest built: %s ranked, sent=%s", len(digest["ranked"]), sent)
        return {"ranked": len(digest["ranked"]), "recipients": len(to), "sent": sent}
    finally:
        if own:
            db.close()
