# go2-keyboard-control

Single-file keyboard teleop for the Unitree Go2 (Air/Pro/EDU) over WebRTC, built on
[legion1581/unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect)
(PyPI: `unitree_webrtc_connect`).

[![Unitree Go2 Keyboard Remote Control over WebRTC (Python, Open Source)](https://img.youtube.com/vi/Mid-MZnUZ7Y/maxresdefault.jpg)](https://youtu.be/Mid-MZnUZ7Y)

## Run

With [uv](https://docs.astral.sh/uv/) the dependencies come from the inline
script metadata, nothing to install:

```sh
uv run control.py                 # auto-discover the robot on the LAN (default)
uv run control.py --ip 192.168.1.152
uv run control.py --serial B42D2000XXXXXXXX   # when several robots answer
uv run control.py --ap            # robot's own Wi-Fi AP (192.168.12.1)
```

Or with plain pip: `pip install unitree_webrtc_connect && python control.py`.
The package pulls in `pyaudio`; on Linux install `portaudio19-dev` first
(`brew install portaudio` on macOS if the wheel doesn't cover your Python).

`ROBOT_IP`, `ROBOT_SERIAL` and `UNITREE_AES_KEY` env vars work in place of
the flags.

## Firmware ≥ 1.1.15

Newer Go2 firmware needs the per-device AES-128 key for the LAN handshake.
Fetch it once with the driver's CLI and pass it with `--aes-key`:

```sh
uvx --from unitree_webrtc_connect unitree-fetch-aes-key --email you@example.com --password '...' --device-type Go2
```

## Keys

The help menu is pinned to the top of the terminal and redraws automatically
on window resize; `Esc` exits. WASD move, Q/E and Z/C rotate, Space is an
emergency stop; tricks, dances and gaits are on the remaining keys.

## Status panel

Below the key menu, three lines refresh twice a second from the robot's
state topics (`rt/lf/lowstate`, `rt/lf/sportmodestate`, `rt/multiplestate`,
`rt/utlidar/lidar_state`):

```
🔋 74%  30.4 V  -1.7 A  -51 W  cells 23°C  BMS 26°C  body 39°C  2 cycles
✅ no errors  🌡️ motors max 32°C (FR calf)  📡 LiDAR 15 Hz, dirty 0%
🐕 Balance stand, trot  0.02 m/s  height 0.32 m  roll +1° pitch -1°  speed level 0  avoidance on  volume 5/10
```

Battery current is negative while discharging. Robot errors (fan jammed,
motor overheating, ...) are listed in the panel and logged when they appear
or clear. A line reads "no ... data" when its topic has been silent for 3 s.
Narrow terminals drop the trailing fields.
