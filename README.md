# go2-keyboard-control

Single-file keyboard teleop for the Unitree Go2 over WebRTC, built on
[legion1581/unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect)
(PyPI: `unitree_webrtc_connect`). Ported from the `control.py` example in the
phospho `go2_webrtc_connect` fork.

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
