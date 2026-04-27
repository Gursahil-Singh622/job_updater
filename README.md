# Job Posting Monitor

Small Python monitor for checking career pages for keyword-matching job links and sending new matches to a Discord webhook.

## Setup

1. Copy the example config:

   ```bash
   cp config.example.json config.json
   ```

2. Edit `config.json`:

   - Put your Discord webhook URL in `discord_webhook_url`.
   - Add or remove keywords in `keywords`.
   - Add career pages in `sites`.

3. Run a one-time dry run:

   ```bash
   python3 job_monitor.py --once --dry-run
   ```

4. Run continuously:

   ```bash
   python3 job_monitor.py
   ```

## Config Notes

Keywords are treated as case-insensitive regular expressions. Simple words like `intern`, `analyst`, and `seasonal` work as expected. You can also use patterns like `data analyst` or `summer.*intern`.

Each site can optionally filter links:

- `include_url_patterns`: only keep links whose URLs match at least one pattern.
- `exclude_url_patterns`: ignore links whose URLs match any pattern.

The monitor stores already-notified posting URLs in `seen_jobs.json`, so it only sends Discord notifications for newly discovered matches.

## Example Site Entry

```json
{
  "name": "Company Careers",
  "url": "https://company.example/careers",
  "include_url_patterns": ["jobs", "careers", "positions"],
  "exclude_url_patterns": ["privacy", "terms"]
}
```

## Discord Webhook

In Discord, go to the target channel settings, then Integrations, then Webhooks. Create a webhook and paste its URL into `config.json`.

## Run With GitHub Actions

This repo includes a workflow at `.github/workflows/job-monitor.yml`.

1. In GitHub, open the repo settings.
2. Go to Secrets and variables, then Actions.
3. Create a repository secret named `DISCORD_WEBHOOK_URL`.
4. Paste your Discord webhook URL as the secret value.
5. Edit `config.github-actions.json` with the websites and keywords you want to monitor.

The workflow runs every 30 minutes by default:

```yaml
- cron: "*/30 * * * *"
```

To change the frequency, edit that cron value in `.github/workflows/job-monitor.yml`.

Examples:

- `*/10 * * * *` checks every 10 minutes.
- `0 * * * *` checks hourly.
- `0 13 * * *` checks once daily at 13:00 UTC.

GitHub Actions schedules use UTC time.
