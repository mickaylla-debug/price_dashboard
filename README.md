# Wishlist Price Dashboard

Checks the price + photo on every URL in `urls.txt` once a day, keeps a
90-day price history for each, emails you when something drops, and
shows it all on a visual dashboard (`index.html`) — image, current
price, and a trend chart per item, toggleable between 30/60/90 days.

Runs for free on GitHub's servers (checking + emailing), and the
dashboard is hosted for free too, so none of it depends on your
computer being on.

## How it decides the price
- Shopify stores (Unique Vintage, Hell Bunny, Vampirefreaks, Foxblood,
  Midnight Hour, La Femme en Noir, Lively Ghosts, My Violet, Forest Ink) —
  reads the store's own product JSON directly, including the image. If
  your link has `?variant=...`, it tracks that specific color/size.
- Everything else (Torrid, Hot Topic, restyle.pl, etc.) — reads the
  page's structured product data (and image), falling back to scanning
  the page for a price if that's missing.
- If a URL can't be parsed that day, it's skipped (not counted as a
  drop) and flagged in `prices.json` under `last_error` / shown with a
  small warning on its dashboard card.

## About "upcoming promotions"
There's no reliable way to predict when a specific small/independent
brand will run a sale — no site publishes that in advance, so this
isn't something the dashboard can honestly claim to detect. What it
does instead:
- Shows each item's own price history, so you can see whether *that*
  brand tends to discount and by how much.
- Includes a reference panel of the known big shared shopping dates
  (Black Friday, Cyber Monday, etc.) as a "watch closely" calendar.

## One-time setup (about 15 minutes)

### 1. Create the new Gmail account (for email alerts)
1. Go to [accounts.google.com/signup](https://accounts.google.com/signup) and create a new address just for this bot.
2. Turn on 2-Step Verification: Google Account → Security → 2-Step Verification.
3. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), create an app password (name it "price tracker"), and copy the 16-character code — Google only shows it once.

### 2. Create the GitHub repo
1. On GitHub, click **New repository**. Name it something like `price-dashboard`.
2. **Keep it Public.** (GitHub's free Pages hosting requires a public repo. Nothing sensitive lives in these files — your email login stays in encrypted repo Secrets, never in a file, so nothing private is exposed by this.)
3. Upload every file from this folder, preserving the folder structure — `check_prices.py`, `urls.txt`, `requirements.txt`, `index.html`, `prices.json`, `README.md`, and `.github/workflows/price-check.yml`. GitHub's web uploader may not preserve a hidden `.github` folder; use Git locally or create the workflow file in GitHub's editor at that exact path.
4. In **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** so the daily job can commit updated `prices.json`.

### 3. Add your secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `GMAIL_ADDRESS` | the new Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-character app password |
| `NOTIFY_EMAIL` | the email address you actually want alerts sent to (can be your regular email) |

### 4. Turn on the dashboard (GitHub Pages)
1. Repo → **Settings → Pages**.
2. Under "Build and deployment," set **Source** to "Deploy from a branch," branch `main`, folder `/ (root)`. Save.
3. GitHub will give you a URL like `https://yourusername.github.io/price-dashboard/` — bookmark it, that's your dashboard.

### 5. Turn on Actions and run it once
1. Repo → **Actions** tab → enable workflows if prompted.
2. Click **Daily Price Check** → **Run workflow** → **Run workflow** to test it immediately instead of waiting for the schedule.
3. This first run populates `prices.json` with day-one prices and images — no emails yet since there's nothing to compare against. Visit your dashboard URL afterward (give Pages a minute or two to publish) and you should see items whose prices could be read. Failed checks are listed in the Actions log and in `prices.json`.
4. From the next day's run onward, the chart starts to build and drop emails will start firing when applicable.

It'll now run automatically every day (13:00 UTC / 7am Central Daylight Time or 8am Central Standard Time — change the `cron` line in `.github/workflows/price-check.yml`
for a different time), and the dashboard updates itself each time
since it reads `prices.json` fresh on every page load.

## Adding or removing items later
Edit `urls.txt` in the GitHub repo (pencil/edit icon on the file page)
— one URL per line. New items appear on the dashboard after the next
daily run.

Removing a line from `urls.txt` stops that item from being *checked*
going forward, but its last-known data stays in `prices.json` and will
keep showing on the dashboard. To make a removed item disappear from
the dashboard right away, also delete its entry from `prices.json`
(same edit-icon approach, or via git).

## If something isn't working
- **Actions** tab → click the latest run → expand steps to see the log, including which URLs failed to parse.
- `prices.json` in the repo shows the last price/image/error per URL.
- Dashboard blank or stuck on "Could not load prices.json yet"? Make sure Pages is enabled (step 4) and that at least one workflow run has completed successfully (step 5).
- Some stores block automated requests, change their markup, or show prices only after JavaScript runs. Those URLs may need store-specific handling. The dashboard currently formats every price as US dollars, including `restyle.pl`; verify any non-USD listing before relying on it.
