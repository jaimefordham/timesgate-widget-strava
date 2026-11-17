# Firmware Update: Port 9000 & LocalToken Support

## What Changed

Your `strava_timesgate.py` script has been updated to support both **legacy firmware (port 80)** and **new firmware (port 9000)** that requires a `localToken`.

## Configuration

### For New Firmware (Port 9000)

Update `config.json`:
```json
{
  "device_ip": "192.168.1.50",
  "device_port": 9000,
  "device_endpoint": "/divoom_api",
  "local_token": 12345678,
  ... other settings
}
```

**To find your `local_token`:**
1. Open the Divoom app
2. Go to device settings
3. Look for "Local Token" (a 32-bit integer)
4. Copy it to your `config.json`

### For Legacy Firmware (Port 80)

Keep your existing configuration or update to:
```json
{
  "device_ip": "192.168.1.50",
  "device_port": 80,
  "device_endpoint": "/post",
  "local_token": null,
  ... other settings
}
```

## Changes Made

| Function | Change | Benefit |
|----------|--------|---------|
| `build_payload()` | Added validation for port 9000 | Fails early with helpful error if `local_token` is missing |
| `push_to_times_gate()` | Accepts both `error_code` and `ReturnCode` | Works with both firmware versions |
| `DEFAULTS` | Port changed to 9000, local_token docs updated | Better defaults for new hardware |

## Testing

The script validates configuration automatically:

```bash
# This will fail with a helpful error
python strava_timesgate.py --demo --debug
# ValueError: Port 9000 requires 'local_token'...

# This will succeed
python strava_timesgate.py --demo --debug --screen 0
# (after updating config.json with localToken)
```

## Backwards Compatibility

✅ **Fully compatible** with legacy firmware (port 80)  
✅ **Supports both** old and new hardware with one script  
✅ **Graceful errors** if configuration is wrong  

## Troubleshooting

| Error | Solution |
|-------|----------|
| "Port 9000 requires 'local_token'" | Add `local_token` to `config.json` from Divoom app |
| "Could not connect to 192.168.1.50:9000" | Check IP address, verify device is on network |
| "Times Gate command failed" | Check `local_token` is correct; try restarting device |

