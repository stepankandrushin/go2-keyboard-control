# z4rtc: the bashrunner scripts of the Unitree Go2

Source: https://github.com/z4ziggy/z4rtc/blob/9c045a4/z4rtc.py (MIT, commit 9c045a4 of
2026-09-26), fetched 2026-10-12 with `gh api`. The file is 1850 lines and its sha256 is
`1a8da151a771d05a6c69ce0d71a2c6db5c19a42da4377a1177fdb085c2c37173`; only the rows this
repo relies on are kept here. The same table is in
https://github.com/mattbernot/UnitreeVault/blob/main/Go2%20API%20id.md.

z4rtc is a WebRTC controller for the G1 and Go2 with one table of every request it knows.
Each row is `(message type, topic, api_id, params, help)`. For the bashrunner service the
params are `"script:<name>"`, which it sends as the request parameter `{"script": "<name>"}`:

```python
"run_get_hw_version":      ("req", "rt/api/bashrunner/request",          1001, "script:get_hardware_version.sh",           "Get hardware version"),
"run_get_pkg_version":     ("req", "rt/api/bashrunner/request",          1001, "script:get_whole_packet_version.sh",       "Get full packet version"),
```

The same service runs scripts that change the robot (`stop_sport_mode.sh`, the
`demarcate_*.sh` joint and IMU calibrations, `set_remote_id.sh`), so nothing but the two
`get_*_version.sh` scripts was sent.

## What a Go2 answered

Asked on 2026-10-12 over the LAN with `unitree_webrtc_connect` 2.2.0
(`publish_request_new(RTC_TOPIC["BASH_REQ"], {"api_id": 1001, "parameter": {"script": …}})`),
both replies had status code 0 and came back at once:

| Script | `data` of the reply |
|---|---|
| `get_whole_packet_version.sh` | `{"type": "content acquisition", "info": "1.1.4"}` |
| `get_hardware_version.sh` | `{"type": "content acquisition", "info": "20"}` |
