DIGOS TEST portable clone

Source machine path:
/Users/a507/Desktop/DIGOS_test

This package intentionally excludes:
- .git history
- local runtime state
- ~/.digos
- Telegram token / provider keys
- vault.enc / master.key
- logs / cache files

On the target computer:
1. Unzip this folder.
2. Install requirements if needed: python3 -m pip install -r requirements.txt
3. Configure credentials locally on that computer only.
4. Do not run two DIGOS processes against the same Telegram bot token at once.
