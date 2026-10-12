# Show the robot's firmware version in the console

The owner asked for the dog's firmware and whether the console prints it. It did not:
`control.py` named firmware only in the help of `--aes-key`.

**What the robot reports.** Read on 2026-10-12 over the LAN, without an AES key:

| What | Value | Where it comes from |
|---|---|---|
| Firmware (whole package) | 1.1.4 | `get_whole_packet_version.sh` through `rt/api/bashrunner/request`, api_id 1001 |
| Hardware version | 20 | `get_hardware_version.sh`, same request |
| BMS | 1.18 | `bms_state.version_high` and `version_low` of `rt/lf/lowstate` |
| LiDAR | firmware 1.2.3, software 1.0.0.39, SDK 1.0.9 | `rt/utlidar/lidar_state` |

None of the state topics the status panel subscribes to carries the package version, and
`unitree_webrtc_connect` 2.2.0 has no call for it, only the topic name `BASH_REQ`. The
script name is from z4rtc's request table:
[z4rtc.py](https://github.com/z4ziggy/z4rtc/blob/9c045a4/z4rtc.py)
([local](../../sources/github.com/z4rtc-bashrunner-scripts.md)). The Unitree app's string
table has the same name, `get_whole_packet_version`, for its "get software version" call.

On 1.1.4 the driver already signals through `con_notify` on port 9991, which its docstring
gives as "post-1.1.11".

**The change.** `KeyboardController.read_firmware()` sends that one request after the
connection is up, with a 5 s timeout, prints `💾 Firmware: 1.1.4` and keeps the value; the
menu's title line then reads `🤖 ROBOT COMPLETE CONTROL SYSTEM  firmware 1.1.4`, so it stays
on screen after the startup lines are cleared. A robot that does not answer gets a warning
line and the old title. Only the firmware is shown; the other three versions are not.

**Checked** against the robot with a script that connects, calls `read_firmware()` and
prints the title line, without the motion-mode switch and Balance Stand of a full start.
The full interactive start was not run, since it needs a terminal.
