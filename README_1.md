# Parkrun Alphabet 4 Challenge Dashboard

Real-time tracker for Lisa and Beth's 4th parkrun alphabet challenge. Automatically finds closest unvisited parkruns and provides smart travel recommendations.

## Features

- **Alphabet Progress** — Tracks completion of 4 consecutive alphabets (A-Z)
- **Remaining Letters** — Shows which letters still need to be collected
- **Smart Travel Routing** — Recommends car (from Cheltenham) or public transport (from London)
- **Distance Ranking** — Ranks unvisited parkruns by crow-flies distance
- **Individual vs Joint Needs** — Shows who needs which letters
- **Auto-Updates** — Fetches latest data every Sunday 8 AM UTC
- **Interactive Map** — Visualizes distances from home locations

## Setup

### 1. Create GitHub Repository

Create a new public repository named `parkrun-alphabet-4` on your GitHub account (5502woodcres).

### 2. Add Files to Repository

Copy all files from this folder to your new repository:
- `fetch-parkrun-data.py` — Data scraper
- `index.html` — Dashboard
- `package.json` — NPM config
- `requirements.txt` — Python dependencies
- `.netlify.toml` — Netlify deployment config
- `.github/workflows/update-data.yml` — GitHub Actions automation
- `.gitignore` — Git ignore rules

### 3. Deploy to Netlify

1. Go to [netlify.com](https://netlify.com)
2. Click **Add new site** → **Import an existing project**
3. Select your GitHub repository (`5502woodcres/parkrun-alphabet-4`)
4. Build settings:
   - Build command: (leave empty)
   - Publish directory: `.`
5. Click **Deploy site**

Your site will be live at `https://your-site.netlify.app`

### 4. Initial Data Fetch

Once deployed, fetch the initial parkrun data locally:

```bash
pip3 install -r requirements.txt
python3 fetch-parkrun-data.py
git add parkrun-data.json
git commit -m "Initial parkrun data"
git push origin main
```

Netlify will auto-redeploy and your dashboard will show live data.

## Data Model

### Alphabets

The dashboard tracks 4 consecutive alphabets. Each alphabet requires visiting 26 unique parkruns (one for each letter A-Z):

- **Alphabet 1**: First parkrun for each letter (earliest date per letter)
- **Alphabet 2**: Second unique parkrun for each letter
- **Alphabet 3**: Third unique parkrun for each letter  
- **Alphabet 4**: Fourth unique parkrun for each letter (in progress)

### Locations

- **Lisa**: Chepstow, Wales (NP16 5AE)
- **Beth**: Cheltenham, Gloucestershire (GL51 7AZ) + London, W12 (W12 7GR)

### Travel Logic

- If closest parkrun is ≤ Cheltenham distance: **car from Cheltenham**
- If closest parkrun is > Cheltenham distance: **public transport from London**

## Architecture

```
GitHub Repository
    ↓
.github/workflows/update-data.yml (runs Sunday 8 AM UTC)
    ↓
fetch-parkrun-data.py (scrapes parkrun.org.uk)
    ↓
parkrun-data.json (updated with run history)
    ↓
Netlify auto-redeploys
    ↓
index.html displays live data
```

## Automation

The GitHub Actions workflow (`.github/workflows/update-data.yml`) runs every Sunday at 8 AM UTC to:

1. Fetch latest parkrun athlete profiles
2. Extract run history and calculate alphabets
3. Commit and push updated `parkrun-data.json`
4. Netlify automatically redeploys

To manually trigger an update:
- Go to **Actions** tab on GitHub
- Select **Update Parkrun Data**
- Click **Run workflow**

## Local Development

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Run Scraper

```bash
python3 fetch-parkrun-data.py
```

This fetches data from parkrun.org.uk and saves to `parkrun-data.json`.

### 3. Serve Locally

```bash
npm run serve
```

Open http://localhost:8080 to view the dashboard.

## Athlete IDs

- **Lisa**: a3934942
- **Beth**: a2475659

## Files

- `index.html` — Main dashboard (pure HTML/CSS/JS)
- `fetch-parkrun-data.py` — Python scraper for parkrun.org.uk
- `parkrun-data.json` — Generated athlete data and alphabet progress
- `.netlify.toml` — Netlify deployment config
- `.github/workflows/update-data.yml` — GitHub Actions workflow
- `package.json` — NPM scripts
- `requirements.txt` — Python dependencies

## Troubleshooting

**Dashboard shows no data:**
- Check that `parkrun-data.json` exists and is valid JSON
- Check browser console for errors (F12)
- Verify GitHub Actions ran successfully (check Actions tab)

**Data not updating automatically:**
- Check GitHub Actions workflow runs (Actions tab)
- Ensure `.github/workflows/update-data.yml` exists
- Check workflow logs for errors
- Manually trigger: Actions → Update Parkrun Data → Run workflow

**Netlify deployment failed:**
- Check Netlify deploy logs
- Ensure all files are committed to GitHub
- Verify repository is connected to Netlify

## License

MIT
