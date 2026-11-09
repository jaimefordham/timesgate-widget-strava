# Strava Cycling Stats on a Divoom Times Gate

`strava_timesgate.py` gets your ride totals from the Strava API, renders them as a 128x128 image and sends them to **one Times Gate screen of your choice** (0-4, left to right). Select year-to-date totals (the default) or all-time totals with `--mode`.

The screen shows:

| Row | Value |
|---|---|
| Header | Bicycle icon, **"Year"** or **"All time"**, Strava logo |
| 1 | Distance (km or mi) |
| 2 | Number of rides |
| 3 | Moving time |
| 4 | Elevation gain (m or ft) |
| Footer | Last update time |

---

## 1. Requirements

- Python 3.9+
- `pip install requests pillow`
- A Times Gate on the same LAN, connected to Wi-Fi with internet access. The local API only comes up after the device has completed its cloud handshake.

## 2. Create a Strava API application

1. Go to <https://www.strava.com/settings/api>.
2. Create an app. Set **Authorization Callback Domain** to `localhost`.
3. Note the **Client ID** and **Client Secret**.

## 3. Configure

```bash
cp config.example.json config.json
```

| Key | Purpose |
|---|---|
| `strava_client_id` / `strava_client_secret` | From step 2 |
| `device_ip` | Times Gate IP address (set a DHCP reservation for it) |
| `device_endpoint` / `device_port` | `/post` on port `80` for most units. Some hardware revisions use `/divoom_api` on `9000` |
| `local_token` | Integer from the Divoom app. Only needed if the device returns `DeviceToken is err`. Otherwise leave `null` |
| `screen` | Screen to draw on, `0`-`4` (left to right). Can be overridden with `--screen` |
| `units` | `metric` or `imperial` |
| `logo_path` | PNG of the Strava logo (see below). If missing, an orange "STRAVA" wordmark is used |
| `bike_icon_path` | Optional PNG to replace the built-in line-drawn bicycle |
| `font_path` | Optional TTF. Arial Bold (macOS/Windows) or DejaVu Sans Bold (Linux) is found automatically |

### Strava logo

The script does not include Strava's logo because it's a trademark. Download the official asset from Strava's brand guidelines page (<https://developers.strava.com/guidelines/>), save a small PNG with transparency as `strava_logo.png` next to the script, and it will be scaled to fit the header (about 26x20 px). Using the logo is subject to Strava's brand guidelines.

## 4. Authorise Strava (one time)

```bash
python strava_timesgate.py --auth
```

1. A browser opens the Strava consent page. Click **Authorize**.
2. You are redirected to `http://localhost/exchange_token?...code=...`. The page fails to load. That's expected.
3. Copy the full URL from the address bar and paste it into the terminal.

Tokens are saved to `strava_tokens.json` (file mode 600). Strava access tokens last about 6 hours and refresh tokens rotate. The script refreshes automatically and saves the new refresh token every time, so leave this file in place.

## 5. Run

```bash
python strava_timesgate.py --demo --debug              # sample data, print everything, no Strava/device
python strava_timesgate.py --debug                     # real Strava data, printed, NOT pushed
python strava_timesgate.py --mode all-time --debug     # real all-time totals, printed, NOT pushed
python strava_timesgate.py --preview test.png          # real data, render to PNG only
python strava_timesgate.py                             # real data, push to configured screen
python strava_timesgate.py --mode all-time             # all-time totals, push to configured screen
python strava_timesgate.py --screen 4                  # push to a different screen
```

| Option | Effect |
|---|---|
| `--auth` | One-time OAuth setup |
| `--mode {ytd,all-time}` | Choose year-to-date or all-time ride totals; defaults to `ytd` |
| `--debug` | Fetch and render as normal, then print the data and the device payload instead of pushing |
| `--screen N` | Override the configured screen (0-4) |
| `--preview FILE` | Save a 4x-scaled PNG. Does not push to the device |
| `--no-push` | Fetch and render only, silently |
| `--demo` | Use sample stats instead of calling Strava |
| `--config FILE` | Use a different config file |

## 6. Debug mode

`--debug` runs the whole pipeline (token refresh, Strava call, image render, payload build) but **never contacts the Times Gate**. Instead it prints:

- **Progress lines** prefixed `[debug]`: config file used, token expiry and any refresh, each Strava request with its HTTP status, Strava rate-limit usage, athlete ID
- **Config**, with `strava_client_secret` and `local_token` masked
- **Raw totals** exactly as Strava returned them (metres and seconds); the selected field is `ytd_ride_totals` or `all_ride_totals`
- **As displayed**: the converted values that appear on the screen
- **Device request**: target URL, screen number and `LcdArray`
- **Payload**: the full JSON that would be sent, with `PicData` replaced by its size

It combines with other options. For example, `--debug --preview test.png` also saves the image, and `--debug --screen 4` shows the payload for screen 4. The access token and refresh token are never printed.

Example (`--demo --debug --screen 3`):

```text
------------------------------------------------------------
DEBUG MODE: nothing has been sent to the Times Gate
------------------------------------------------------------
...
As displayed:
  Heading                Year
  km                     3,457
  rides                  87
  time                   142h 19m
  m                      28,765

Would POST to:
  http://192.168.1.50/post
  Target screen: 3  (LcdArray [0, 0, 0, 1, 0])
...
```

## 7. Schedule it

Strava allows 100 requests per 15 minutes and 1,000 per day by default. Each run uses 1 call (plus 1 for a token refresh, and 1 the first time to look up your athlete ID). Every 30 minutes is plenty.

```cron
*/30 * * * * cd /path/to/strava_tg && /usr/bin/python3 strava_timesgate.py >> run.log 2>&1
```

On macOS, `launchd` is more reliable than cron if the Mac sleeps.

## How it works

1. **Token**: refreshes the access token via `POST /oauth/token` when it's within 5 minutes of expiry.
2. **Stats**: `GET /api/v3/athletes/{id}/stats` and reads either `ytd_ride_totals` or `all_ride_totals` (`count`, `distance` m, `moving_time` s, `elevation_gain` m), depending on `--mode`.
3. **Render**: Pillow draws a 128x128 image.
4. **Push**: encodes it as a JPEG, base64s it and sends `Draw/SendHttpGif` to `http://<ip>/post` with `LcdArray` set to the chosen screen (for example `[0,0,1,0,0]` for screen 2). `PicID` is a Unix timestamp because the device caches frames by ID.

## Notes and gotchas

- **Visibility**: Strava's stats endpoint only counts activities whose visibility is **Everyone**. Rides set to Followers or Only Me are left out, so the totals may be lower than in the app.
- **Ride types**: `ytd_ride_totals` and `all_ride_totals` are Strava's own roll-ups. To filter by type, page through `/athlete/activities` and sum the rides yourself.
- **Garbled screen**: the Times Gate needs a **128x128 JPEG**. Pixoo-style raw RGB or 64x64 payloads are accepted (`error_code: 0`) but display garbage.
- **Nothing changes on screen**: run with `--debug` to confirm the URL and screen, check the screen isn't on a different channel in the Divoom app, and try `Draw/ResetHttpGifId` if other tools have used large PicIDs.
- **Internet outage**: the local API depends on the device's cloud connection, so pushes may fail until that comes back.
- **Security**: keep `config.json` and `strava_tokens.json` out of Git (`.gitignore` is included).
