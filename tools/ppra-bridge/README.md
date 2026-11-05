# Capture bridge — the portals the cloud cannot reach

`eproc.punjab.gov.pk` (PPRA Punjab) and `wapda.gov.pk` (WAPDA) refuse
connections from every datacenter network, so the API — wherever it runs —
can never read them directly. But the portals answer the bid desk's own
network, and they answer a real browser. This bridge closes the gap: it opens
each listing in this machine's installed Chrome, walks the pages, and posts
the raw HTML to the API's capture endpoint, where it runs through the same
parser, normalizer and scorer a live scan would use.

The portals it feeds are listed in `app/source_registry.py` as
`BRIDGE_FED_SOURCES`; the API refuses to scan them live, so a failed cloud
read can never stamp them as error behind the bridge's back.

## One-time setup

```bat
cd tools\ppra-bridge
python -m venv .venv
.venv\Scripts\pip install playwright httpx
copy config.example.json config.json
```

Put the capture secret into `config.json` — the same value the repository holds
as `BMS_CAPTURE_SECRET` (the deploy pipeline gives it to the API). Ask the
administrator for it, or set it with:

```
gh secret set BMS_CAPTURE_SECRET --body "$(openssl rand -hex 24)"
```

## Run

```bat
.venv\Scripts\python capture.py
```

The script prints what happened and the dashboard's source table shows the
result: health flips to **ok**, the last-scan cell names the mode as **bridge**,
and any new tenders flow into the inbox, scored as usual.

## Keep it fresh

Register a Windows scheduled task so the capture runs on its own (every four
hours). Use the registration script — **not** `schtasks /create`, whose
quoting mangles this folder's spaced path and leaves a task that fails with
0x80070002 on every run:

```bat
powershell -ExecutionPolicy Bypass -File tools\ppra-bridge\register-task.ps1
```

Remove it any time with `schtasks /delete /tn "AHTE-PPRA-capture"`. If the
dashboard shows the source stale or in error, first check the task's last run
(`schtasks /query /tn "AHTE-PPRA-capture" /v`), then run the capture by hand.

## Notes

- The capture secret authenticates the machine, not a person — it can submit
  captured listings and nothing else. It is revocable: clear the value in the
  Vercel project settings and the door closes.
- The script only reads the public listings. It never signs in to a portal,
  and supplier registration and captcha pages are left alone.
- The raw first page of each capture is stored as the source's latest
  snapshot, so the parse stays auditable like every other capture in the
  system.
