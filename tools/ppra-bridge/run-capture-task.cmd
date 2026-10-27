@echo off
rem The scheduled task runs this, so the task's command line stays short
rem and free of the spaces that make schtasks argument parsing brittle.
"C:\Users\PC\Projects\BID Management System\tools\ppra-bridge\.venv\Scripts\python.exe" "C:\Users\PC\Projects\BID Management System\tools\ppra-bridge\capture.py"
