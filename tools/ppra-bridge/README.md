# PPRA Punjab capture bridge

`eproc.punjab.gov.pk` refuses connections from every datacenter network, so the
API — wherever it runs — can never read it directly. But the portal answers the
bid desk's own network, and it answers a real browser. This bridge closes the
gap: it opens the listing in this machine's installed Chrome, walks the pages,
and posts the raw HTML to the API's capture endpoint, where it runs through the
same parser, normalizer and scorer a live scan would use.

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
hours, from the bridge folder):

```bat
schtasks /create /tn "AHTE PPRA capture" /tr "\"C:\path\to\tools\ppra-bridge\.venv\Scripts\python.exe\"" "\"C:\path\to\tools\ppra-bridge\capture.py\"" /sc hourly /mo 4
```

Adjust the two paths to this folder's real location. Remove it any time with
`schtasks /delete /tn "AHTE PPRA capture"`.

## Notes

- The capture secret authenticates the machine, not a person — it can submit
  captured listings and nothing else. It is revocable: clear the value in the
  Vercel project settings and the door closes.
- The script only reads the public listing. It never signs in to the portal,
  and the supplier registration and captcha pages are left alone.
- The raw first page is stored as the source's latest snapshot, so the parse
  stays auditable like every other capture in the system.
