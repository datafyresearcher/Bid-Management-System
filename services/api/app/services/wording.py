"""The words the bid team reads, in one place.

The workflow's own vocabulary — GATE1, SCREENED_OUT, APPROVED — is the
machinery's word for things, and it reaches the bid team in more places than
the web pages: the daily email brief, the notification titles, the replies a
stale request returns. Wherever a state, a stage or a decision is written
where a person will read it, it goes through this module first, so the same
tender is not "GATE1" in one place and "Stage 1 — Go / No-Go" in another.

The same mapping lives in the web app (`apps/web/lib/api.js`); the two are
kept in step by the tests in `tests/test_feedback_items.py`.
"""

import re

STATE_LABELS = {
    "NEW": "New",
    "NORMALIZED": "Waiting to be reviewed",
    "SCORED": "Scored",
    "SCREENED_OUT": "Screened out",
    "AUTO_ARCHIVED": "Archived automatically",
    "GATE1": "Stage 1 — Go / No-Go",
    "GATE2": "Stage 2 — Eligibility check",
    "GATE3": "Stage 3 — Draft review",
    "GATE4": "Stage 4 — Final approval",
    "GATE5": "Stage 5 — Submission",
    "DOCS_FETCHED": "Fetching the tender documents",
    "ANALYZED": "Document analysis complete",
    "DRAFTING": "Drafting the proposal",
    "ASSEMBLY": "Assembling the submission pack",
    "READY_TO_SUBMIT": "Ready to submit",
    "SUBMITTED": "Submitted",
    "EVALUATION": "Under evaluation",
    "WON": "Won",
    "LOST": "Lost",
    "REJECTED": "Rejected",
    "ABANDONED": "Abandoned",
}

# What a stage's own status means to the reader.
GATE_STATUS_LABELS = {
    "PENDING": "Waiting for a decision",
    "OVERDUE": "Overdue — past its review time",
    "APPROVED": "Approved",
    "REJECTED": "Returned",
    "CANCELLED": "Cancelled",
}

# What a notification's type means to the reader.
NOTIFICATION_TYPE_LABELS = {
    "gate": "Decision needed",
    "screen_out": "Screening",
    "sla": "Review overdue",
    "deadline": "Closing soon",
    "outcome": "Outcome",
    "submission": "Submission",
    "abandoned": "Abandoned",
    "scan": "New tenders",
    "lead": "Lead",
}


def state_label(state: str) -> str:
    """The readable name of a workflow state."""
    if not state:
        return "—"
    return STATE_LABELS.get(state, state)


def gate_status_label(status: str) -> str:
    """The readable name of a stage status."""
    if not status:
        return "—"
    return GATE_STATUS_LABELS.get(status, status)


def notification_type_label(ntype: str) -> str:
    """The readable name of a notification's type."""
    if not ntype:
        return "Notice"
    return NOTIFICATION_TYPE_LABELS.get(ntype, ntype.replace("_", " ").capitalize())


# -- rewriting what is already stored ------------------------------------------
#
# Notifications are rows on file, and the ones written before the stage
# wording reached them keep saying "Gate 1 pending" long after the screens
# stopped. The patterns below are what the old calls emitted; each rewrite
# says the same thing in the words the bid team reads.

_GATE_PENDING_TITLE_RE = re.compile(r"^Gate (\d+) pending: (.*)$", re.S)
_GATE_REOPENED_TITLE_RE = re.compile(r"^Gate (\d+) reopened: (.*)$", re.S)
_SLA_TITLE = "SLA overdue: "
_GATE_OVERDUE_BODY_RE = re.compile(r"\bGate (\d+) overdue since\b")
_GATE5_CLOSED = "Gate 5 closed without submission confirmation"
_STAGE5_CLOSED = "Stage 5 closed without submission confirmation"
_STATE_BODY_RE = re.compile(r" — state ([A-Z][A-Z_0-9]*)")


def reword_notification(title: str, body: str) -> tuple:
    """Rewrite one stored notification in the bid team's words.

    Returns (title, body, changed). Anything that already speaks plainly is
    returned exactly as it came in.
    """
    new_title = title or ""
    new_body = body or ""
    changed = False

    match = _GATE_PENDING_TITLE_RE.match(new_title)
    if match:
        new_title = f"Stage {match.group(1)} — a decision is needed: {match.group(2)}"
        changed = True
    match = _GATE_REOPENED_TITLE_RE.match(new_title)
    if match:
        new_title = f"Stage {match.group(1)} reopened: {match.group(2)}"
        changed = True
    if new_title.startswith(_SLA_TITLE):
        new_title = "Review time overdue: " + new_title[len(_SLA_TITLE):]
        changed = True
    if _GATE_OVERDUE_BODY_RE.search(new_body):
        new_body = _GATE_OVERDUE_BODY_RE.sub(r"Stage \1 overdue since", new_body)
        changed = True
    if _GATE5_CLOSED in new_body:
        new_body = new_body.replace(_GATE5_CLOSED, _STAGE5_CLOSED)
        changed = True
    if _STATE_BODY_RE.search(new_body):
        new_body = _STATE_BODY_RE.sub(lambda m: f" — {state_label(m.group(1))}", new_body)
        changed = True

    return new_title, new_body, changed
