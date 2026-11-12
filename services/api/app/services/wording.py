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
