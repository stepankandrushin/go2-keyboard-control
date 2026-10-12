# Show the hardware, BMS and LiDAR versions beside the firmware

The entry before this one put only the firmware version on screen, in the menu's title
line. The owner asked for the other versions that had been read: hardware, BMS, LiDAR.

**The change.** The versions moved from the title line to a fourth line of the status
panel, because two of them arrive on the state topics after the menu is drawn, and only the
panel is redrawn twice a second:

```
💾 firmware 1.1.4  hardware 20  BMS 1.18  LiDAR firmware 1.2.3  LiDAR software 1.0.0.39  LiDAR SDK 1.0.9
```

- `read_versions()` replaces `read_firmware()`: on connect it runs `get_whole_packet_version.sh`
  and `get_hardware_version.sh` through `rt/api/bashrunner/request` (api_id 1001), 3 s each,
  and prints `💾 Firmware: 1.1.4` and `💾 Hardware: 20`. Source of the script names:
  [z4rtc.py](https://github.com/z4ziggy/z4rtc/blob/9c045a4/z4rtc.py)
  ([local](../../sources/github.com/z4rtc-bashrunner-scripts.md)).
- `versions_status()` adds the BMS version from `bms_state` of `rt/lf/lowstate` and the
  LiDAR's three from `rt/utlidar/lidar_state`, and keeps each once seen, so the line does
  not empty when a topic goes silent.
- `STATUS_LINES` is 4. A narrow terminal drops the trailing versions like the trailing
  fields of the other lines: at 80 columns the line ends with the LiDAR firmware.

**Checked** against the robot with a script that connects, subscribes, calls
`read_versions()` and prints the panel at 200, 100, 80 and 40 columns, and once more after
the telemetry had gone stale. No motion command was sent; the full interactive start was
not run, since it needs a terminal.
