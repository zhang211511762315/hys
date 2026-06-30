# Current site backup - 2026-06-30

This directory stores a base64-split Git bundle created from the server checkout before optimization.

Local backup commit: `3b2ebb5b38b8187b09a0cc318a388c148314ac01`
Base commit required: `29e3fd3873eb13b5770f4926250b2ffab59d60c3`
Original branch name: `backup/current-site-20260630`

Restore from the split files:

```bash
cat current-site-20260630.bundle.b64.part* > current-site-20260630.bundle.b64
base64 -d current-site-20260630.bundle.b64 > current-site-20260630.bundle
git bundle verify current-site-20260630.bundle
git fetch current-site-20260630.bundle backup/current-site-20260630:backup/current-site-20260630
```

The runtime `.env` file and `wewe-rss/data/wewe-rss.db` were intentionally excluded from the backup.
