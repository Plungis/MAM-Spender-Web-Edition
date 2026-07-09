# MAM Spender Web

This is the Web Edition of MAM Spender. It uses only the Python standard library, so there is no `pip install` step.

Current Web Edition version: `v1.3.1-beta.1`.

## Run

Double-click `Start MAM Spender Web.bat`.

The app opens at `http://127.0.0.1:8765` by default. Close the command window to stop it.

You can change the local server port in the Settings panel. Save the new port, close the command window, then start the app again. The new address will be `http://127.0.0.1:YOUR_PORT`.

## Run With Docker

Docker is optional. The normal Windows/Python launcher still works without Docker.

### Option A: Pull The Published Image

Create a folder anywhere, then create a `docker-compose.yml` file with:

```yaml
services:
  mam-spender-web:
    image: ghcr.io/plungis/mam-spender-web-edition:latest
    container_name: mam-spender-web
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
    environment:
      MAM_SPENDER_HOST: 0.0.0.0
      MAM_SPENDER_PORT: 8765
      MAM_SPENDER_OPEN_BROWSER: "0"
      MAM_SPENDER_FILE_DIALOGS: "0"
    restart: unless-stopped
```

Then run:

```powershell
docker compose up -d
```

To update an existing Docker install:

```powershell
docker compose pull
docker compose up -d --force-recreate
```

Open:

```text
http://127.0.0.1:8765
```

### Option B: Build Locally

From the project folder, run:

```powershell
docker compose up --build
```

Then open:

```text
http://127.0.0.1:8765
```

To stop it:

```powershell
docker compose down
```

The Docker setup stores settings and Session_ID files in the local `data` folder through a volume mount:

```text
./data:/app/data
```

Docker notes:

- The app listens on `0.0.0.0` inside Docker, but you still open it from your computer at `http://127.0.0.1:8765`.
- Desktop file picker/save dialogs are disabled in Docker. Paste the Mam Session_ID and save it as `/app/data/MAM.cookies`, or manually place a cookie file in the mounted `data` folder and enter its container path.
- If you change the Docker port, update both `ports` and `MAM_SPENDER_PORT` in `docker-compose.yml`.
- The published image is built automatically from the GitHub repo and published as `ghcr.io/plungis/mam-spender-web-edition:latest`.

## Behavior

- Checks your MAM account using your Mam Session_ID.
- Shows the current Web Edition version and checks GitHub releases for newer versions.
- Buys exactly 100 GiB upload credit for 50,000 points when your balance is high enough to keep your points buffer after purchase.
- Default scan interval is 15 minutes.
- Minimum allowed scan interval is 2 minutes.
- Points buffer is capped at 49,000 so it cannot exceed the 50,000-point purchase cost.
- Upload purchases require at least 51,000 points, or 50,000 plus your points buffer, whichever is higher.
- Local server port is customizable from 1024 to 65535. Port changes apply after restarting the app.
- Optional VIP renewal at 83 days remaining or less, enabled by default.
- Optional upload credit purchases, Freeleech-only mode, or alternating Freeleech Wedge and upload credit purchases.
- Tracks cumulative upload GiB, cumulative points spent, last scan points, and points per minute.
- Keeps a local History tab of past runs.
- Shows local time alongside MAM server time in UTC for timestamped activity.
- Shows a marquee under the main tabs with MAM UTC time, daily Vault reset, Lotto reset, and Lotto drawing countdowns.
- Loads optional MAM user data in the MAM Data tab from `/jsonLoad.php`, including account stats, client status, and notifications when available.
- Loads optional MAM bonus history from `/json/userBonusHistory.php`, keeps up to 500 returned entries, and paginates them locally.
- Plots recorded spending events in the Graph tab with pie, bar, and timeline chart modes.
- Tracks Freeleech Wedges bought with points and points spent on wedges.

## Mam Session_ID

Open MAM Security from the app, create a session, copy the long Session_ID value, paste it into the Mam Session_ID panel, and click `Save Session_ID`.

When saving a pasted Session_ID, the app asks whether you want to save it as a cookie file or store it locally in the app settings as plain text. A cookie file is recommended. Keep either option private.

No cookie file path is set by default. Once you enter one or save a new file, the app saves and reuses it.

You can also point the Mam Session_ID file path at an existing file. The app will try to extract the Session_ID from:

- A raw Session_ID value
- `mam_id=...` or a full `Cookie:` header
- Netscape/curl cookie export files
- JSON browser cookie exports with `name: "mam_id"` and `value: "..."`

Use `Check File` to confirm the path can be read before starting the schedule.

Use `Browse File` to open a native file picker and save the selected cookie/export path automatically.

## Modify

- Server and MAM purchase logic: `app.py`
- Page structure: `static/index.html`
- Styling: `static/styles.css`
- Browser behavior: `static/app.js`

Persistent settings live in `data/config.json`.

## Version Releases

The app reports its current version from `APP_VERSION` in `app.py` and checks the latest GitHub release at:

```text
https://github.com/Plungis/MAM-Spender-Web-Edition/releases
```

When publishing a new version:

- Update `APP_VERSION` and `APP_VERSION_LABEL` in `app.py`.
- Create a matching GitHub release tag, such as `v1.2.0`.
- The app will show an update notice when the latest release tag is newer than the running version.
