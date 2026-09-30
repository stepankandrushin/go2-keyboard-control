#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["unitree_webrtc_connect"]
# ///
"""Keyboard control for the Unitree Go2 over WebRTC.

By default the robot is found on the LAN by multicast discovery; pass --ip
to connect to a known address instead.
"""
import argparse
import asyncio
import logging
import json
import math
import os
import sys
import termios
import tty
import select
import unicodedata
import shutil
import signal
import time
from collections import deque
import cv2
import numpy as np
from unitree_webrtc_connect import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
    RTC_TOPIC,
    SPORT_CMD,
    discover_ip_sn,
    webrtc_datachannel,
)
from unitree_webrtc_connect.msgs.error_handler import (
    get_error_code_text,
    get_error_source_text,
    integer_to_hex_string,
)

# Enable logging for debugging
logging.basicConfig(level=logging.FATAL)

# State topics feeding the status panel (lowstate and multiplestate come at
# 1 Hz, sportmodestate at 20 Hz)
TELEMETRY_TOPICS = ("LOW_STATE", "LF_SPORT_MOD_STATE", "MULTIPLE_STATE", "ULIDAR_STATE")
STATUS_LINES = 3
STALE_AFTER = 3  # seconds without a sample before a topic counts as missing
VIDEO_WINDOW = "Go2 camera"
LIDAR_WINDOW = "Go2 LiDAR"
LIDAR_SIZE = 640     # LiDAR view side in pixels
LIDAR_SCALE = 100    # pixels per metre: the robot's 6.4 m voxel map fills the view
LIDAR_TOP = 1.5      # metres above the floor that get the hottest colour
FLOOR_BAND = 0.1     # points this close to the floor are drawn as ground

# LiDAR view colour per height code: 0 empty, 1 ground, 2..255 low to high
LIDAR_COLORS = cv2.applyColorMap(np.arange(256, dtype=np.uint8), cv2.COLORMAP_TURBO).reshape(256, 1, 3)
LIDAR_COLORS[2:] = LIDAR_COLORS[np.linspace(40, 255, 254).astype(int)]  # skip turbo's near-black end
LIDAR_COLORS[0] = (30, 30, 30)
LIDAR_COLORS[1] = (85, 85, 85)

# lowstate motor_state order; entries past the 12th are unused on the Go2
MOTOR_NAMES = [f"{leg} {joint}" for leg in ("FR", "FL", "RR", "RL")
               for joint in ("hip", "thigh", "calf")]

# sportmodestate mode and gait_type values
SPORT_MODES = {
    0: "Idle", 1: "Balance stand", 2: "Pose", 3: "Locomotion", 5: "Lying down",
    6: "Joint lock", 7: "Damping", 8: "Recovery stand", 10: "Sitting",
    11: "Front flip", 12: "Front jump", 13: "Front pounce",
}
GAITS = {0: "idle", 1: "trot", 2: "run", 3: "stairs up", 4: "stairs down", 9: "adjust"}

class KeyboardController:
    def __init__(self):
        self.running = True
        self.conn = None
        self.telemetry = {}      # topic -> (monotonic time, latest data)
        self.errors = {}         # active robot errors: (source, code) -> text
        self.status_row = None   # terminal row of the status panel, if pinned
        self.windows = {}        # OpenCV window name -> (image getter, on-close callback)
        self.video_frame = None  # newest camera frame not shown yet
        self.lidar_map = None    # newest voxel map not shown yet: (points, resolution)
        self.window_keys = deque()  # keys typed while a window has focus
        
        # Movement settings
        self.movement_speed = 0.5     # Default movement speed
        self.small_rotation = 0.5     # Default small rotation degrees
        self.large_rotation = 90      # Default large rotation degrees
        
        # Centralized key mappings and actions
        self.key_actions = {
            # Movement controls
            'w': {
                'params': {'x': self.movement_speed, 'y': 0, 'z': 0},
                'message': '🏃↑ Moving Forward...'
            },
            's': {
                'params': {'x': -self.movement_speed, 'y': 0, 'z': 0},
                'message': '🏃↓ Moving Backward...'
            },
            'a': {
                'params': {'x': 0, 'y': self.movement_speed, 'z': 0},
                'message': '🏃← Moving Left...'
            },
            'd': {
                'params': {'x': 0, 'y': -self.movement_speed, 'z': 0},
                'message': '🏃→ Moving Right...'
            },
            'q': {
                'params': {'x': 0, 'y': 0, 'z': self.small_rotation},
                'message': f'🔄 ← Rotating {self.small_rotation}° counter-clockwise....'
            },
            'e': {
                'params': {'x': 0, 'y': 0, 'z': -self.small_rotation},
                'message': f'🔄 → Rotating {self.small_rotation}° clockwise....'
            },
            'z': {
                'params': {'x': 0, 'y': 0, 'z': self.large_rotation},
                'message': f'🔄 ← Rotating {self.large_rotation}° counter-clockwise....'
            },
            'c': {
                'params': {'x': 0, 'y': 0, 'z': -self.large_rotation},
                'message': f'🔄 → Rotating {self.large_rotation}° clockwise...'
            },
            
            # Basic actions
            'p': {
                'command': 'StandUp',
                'message': '🏃 Standing Up...'
            },
            'l': {
                'command': 'StandDown',
                'message': '🛏️ Lying Down... (then P to stand)'
            },
            'x': {
                'command': 'Sit',
                'message': '🪑 Sitting Down... (then R to move)'
            },
            'y': {
                'command': 'BalanceStand',
                'message': '⚖️ Balance Stand...'
            },
            'u': {
                'command': 'StopMove',
                'message': '🛑 Stop Move...'
            },
            'i': {
                'command': 'RecoveryStand',
                'message': '🩹 Recovery Stand...'
            },
            'o': {
                'command': 'Damp',
                'message': '🔇 Damp... (then P, R)'
            },
            'r': {
                'command': 'RiseSit',
                'message': '🔄 Rise/Sit Toggle...'
            },
            
            # Tricks and flips
            'f': {
                'command': 'FrontFlip',
                'message': '🤸 Front Flip...'
            },
            'g': {
                'command': 'BackFlip',
                'message': '🤸 Back Flip...'
            },
            'j': {
                'command': 'RightFlip',
                'message': '🤸 Right Flip...'
            },
            'k': {
                'command': 'FrontJump',
                'message': '🦘 Front Jump...'
            },
            'h': {
                'command': 'FrontPounce',
                'message': '🦁 Front Pounce...'
            },
            
            # Dances and gestures
            'v': {
                'command': 'Dance1',
                'message': '💃 Dance 1...'
            },
            'b': {
                'command': 'Dance2',
                'message': '💃 Dance 2...'
            },
            'n': {
                'command': 'Hello',
                'message': '👋 Hello/Wave...'
            },
            'm': {
                'command': 'Stretch',
                'message': '🧘 Stretch...'
            },

            # Numbered commands (1-8)
            '1': {
                'command': 'FingerHeart',
                'message': '💖 Finger Heart...'
            },
            '2': {
                'command': 'WiggleHips',
                'message': '🕺 Wiggle Hips...'
            },
            '4': {
                'command': 'CrossStep',
                'message': '❌ Cross Step...'
            },
            '5': {
                'command': 'MoonWalk',
                'message': '🌙 Moon Walk...'
            },
            '6': {
                'command': 'LeftFlip',
                'message': '🤸 Left Flip...'
            },
            '7': {
                'command': 'Handstand',
                'message': '🤸 Handstand...'
            },
            '8': {
                'command': 'Bound',
                'message': '🦘 Bound...'
            },
            
            # System controls
            'space': {
                'command': 'StopMove',
                'message': '🚨 EMERGENCY STOP!'
            },
            'esc': {
                'message': '👋 Disconnecting and exiting...'
            }
        }
        
    def get_valid_keys(self):
        """Get list of all valid keys"""
        return list(self.key_actions.keys())
        
    def get_key(self):
        """Next key from a window or the terminal, without blocking"""
        if self.window_keys:
            key = chr(self.window_keys.popleft()).lower()
        elif select.select([sys.stdin], [], [], 0)[0]:
            key = sys.stdin.read(1).lower()
        else:
            return None
        if key in ('\x1b', '\x03'):  # ESC, or Ctrl+C (no SIGINT in raw mode)
            return 'esc'
        elif key == ' ':  # Space
            return 'space'
        elif key in self.get_valid_keys():
            return key
        return None
    
    def print_action(self, message, end='\n'):
        """Print action message with proper formatting for raw terminal mode"""
        print(f"\r{message}{end}", end='', flush=True)

    def print_result(self, message):
        """Finish the pending action line with the command's outcome"""
        print(f" {message}\n", end='', flush=True)

    def print_response(self, command_name, response):
        """Print the robot's reply to a command"""
        try:
            status = response["data"]["header"]["status"]
        except (KeyError, TypeError):
            self.print_result(f"❔ {command_name} reply: {response}")
            return
        mark = "✅" if status.get("code") == 0 else "⚠️"
        self.print_result(f"{mark} {command_name} reply: {status} {response['data'].get('data', '')}".rstrip())
    
    async def move_robot(self, x=0, y=0, z=0):
        """Send movement command to robot"""
        if self.conn:
            try:
                response = await self.conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {"api_id": SPORT_CMD["Move"], "parameter": {"x": x, "y": y, "z": z}},
                )
                self.print_response("Move", response)
            except Exception as e:
                self.print_result(f"❌ Error sending movement command: {e}")
    
    @staticmethod
    def display_width(text):
        """Terminal column width of text (emoji take two columns)"""
        width = 0
        for ch in text:
            if ch == '\ufe0f':
                # Emoji presentation selector widens the preceding symbol
                width += 1
                continue
            if unicodedata.combining(ch) or ch == '\u200d':
                continue
            width += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        return width

    def pad(self, text, width):
        """Pad text with spaces to the given display width"""
        return text + " " * max(0, width - self.display_width(text))

    def help_lines(self, width):
        """Build the help menu as compact columns that fit the terminal width"""
        entries = []
        for key, action in self.key_actions.items():
            entries.append(f"  {key.title():<6}: {action['message'].replace('...', '')}")

        col_width = max(self.display_width(e) for e in entries) + 2
        num_cols = max(1, width // col_width)
        num_rows = -(-len(entries) // num_cols)

        lines = ["=" * width, "🤖 ROBOT COMPLETE CONTROL SYSTEM", "=" * width]
        for r in range(num_rows):
            row = [self.pad(entries[c * num_rows + r], col_width)
                   for c in range(num_cols) if c * num_rows + r < len(entries)]
            lines.append("".join(row).rstrip())
        lines.append("=" * width)
        lines += self.status_lines(width)
        lines.append("=" * width)
        return lines

    def print_help(self):
        """Draw the help menu pinned to the top; actions scroll below it"""
        width, height = shutil.get_terminal_size()
        lines = self.help_lines(width)
        # Reset scroll region, clear screen, draw the menu at the top
        out = "\x1b[r\x1b[2J\x1b[H" + "\r\n".join(lines) + "\r\n"
        self.status_row = None
        if len(lines) < height - 1:
            # Restrict scrolling to the area below the menu
            top = len(lines) + 1
            out += f"\x1b[{top};{height}r\x1b[{top};1H"
            self.status_row = len(lines) - STATUS_LINES
        sys.stdout.write(out)
        sys.stdout.flush()

    def store_telemetry(self, topic):
        """Subscription callback keeping the newest sample of a topic"""
        def callback(message):
            self.telemetry[topic] = (time.monotonic(), message["data"])
        return callback

    def start_telemetry(self):
        """Subscribe to the state topics feeding the status panel"""
        for topic in TELEMETRY_TOPICS:
            self.conn.datachannel.pub_sub.subscribe(RTC_TOPIC[topic], self.store_telemetry(topic))

    def latest(self, topic):
        """Newest sample of a telemetry topic, or None if missing or stale"""
        stamp, data = self.telemetry.get(topic, (0, None))
        return data if time.monotonic() - stamp < STALE_AFTER else None

    def on_robot_errors(self, message):
        """Track the robot's active errors (replaces the driver's printer)"""
        data = message.get("data") or []
        if data and not isinstance(data[0], (list, tuple)):
            data = [data]
        entries = {}
        for _timestamp, source, code in data:
            code_text = get_error_code_text(source, integer_to_hex_string(code))
            entries[(source, code)] = f"{get_error_source_text(source)}: {code_text}"
        if message.get("type") == "rm_error":
            for key, text in entries.items():
                if self.errors.pop(key, None):
                    self.print_action(f"✅ Robot error cleared: {text}")
            return
        for key, text in entries.items():
            if key not in self.errors:
                self.print_action(f"🚨 Robot error: {text}")
        # "errors" is a full snapshot, "add_error" a single new one
        self.errors = entries if message.get("type") == "errors" else {**self.errors, **entries}

    @staticmethod
    def peak(value):
        """Highest reading of a sensor that may report one value or several"""
        return max(value) if isinstance(value, list) else value

    def power_status(self):
        """Battery and board temperatures from lowstate"""
        low = self.latest("LOW_STATE")
        if low is None:
            return ["🔋 no battery data"]
        bms = low["bms_state"]
        amps = bms["current"] / 1000  # negative while discharging
        return [
            f"🔋 {bms['soc']}%",
            f"{low['power_v']:.1f} V",
            f"{amps:+.1f} A",
            f"{low['power_v'] * amps:+.0f} W",
            f"cells {self.peak(bms['bq_ntc'])}°C",
            f"BMS {self.peak(bms['mcu_ntc'])}°C",
            f"body {low['temperature_ntc1']}°C",
            f"{bms['cycle']} cycles",
        ]

    def health_status(self):
        """Active errors, hottest motor and LiDAR health"""
        if self.errors:
            pieces = [f"🚨 {len(self.errors)} error(s): " + "; ".join(self.errors.values())]
        else:
            pieces = ["✅ no errors"]
        low = self.latest("LOW_STATE")
        if low:
            temps = [motor["temperature"] for motor in low["motor_state"][:len(MOTOR_NAMES)]]
            hottest = max(range(len(temps)), key=temps.__getitem__)
            pieces.append(f"🌡️ motors max {temps[hottest]}°C ({MOTOR_NAMES[hottest]})")
        lidar = self.latest("ULIDAR_STATE")
        if lidar:
            lidar_text = f"📡 LiDAR {lidar['cloud_frequency']:.0f} Hz, dirty {lidar['dirty_percentage']}%"
            if lidar["error_state"]:
                lidar_text += f", error {lidar['error_state']}"
            pieces.append(lidar_text)
        return pieces

    def motion_status(self):
        """Sport mode state and the app-level settings"""
        pieces = []
        sport = self.latest("LF_SPORT_MOD_STATE")
        if sport:
            mode = SPORT_MODES.get(sport["mode"], f"mode {sport['mode']}")
            gait = GAITS.get(sport["gait_type"], f"gait {sport['gait_type']}")
            vx, vy = sport["velocity"][:2]
            roll, pitch = (math.degrees(angle) for angle in sport["imu_state"]["rpy"][:2])
            pieces += [
                f"🐕 {mode}, {gait}",
                f"{math.hypot(vx, vy):.2f} m/s",
                f"height {sport['body_height']:.2f} m",
                f"roll {roll:+.0f}° pitch {pitch:+.0f}°",
            ]
            if sport["error_code"]:
                pieces.insert(1, f"⚠️ sport error {sport['error_code']}")
        multi = self.latest("MULTIPLE_STATE")
        if multi:
            settings = json.loads(multi)
            pieces += [
                f"speed level {settings['speedLevel']}",
                f"avoidance {'on' if settings['obstaclesAvoidSwitch'] else 'off'}",
                f"volume {settings['volume']}/10",
            ]
        return pieces or ["🐕 no motion data"]

    def fit(self, pieces, width):
        """Join status pieces into one line, dropping those that don't fit"""
        line = ""
        for piece in pieces:
            candidate = f"{line}  {piece}"
            if self.display_width(candidate) > width:
                break
            line = candidate
        if not line:
            # Even the first piece is too wide: cut it at the edge
            line = f"  {pieces[0]}"
            while self.display_width(line) > width:
                line = line[:-1]
        return line

    def status_lines(self, width):
        """The status panel, one line per group"""
        return [self.fit(pieces, width) for pieces in
                (self.power_status(), self.health_status(), self.motion_status())]

    def draw_status(self):
        """Refresh the status panel in place, keeping the cursor where it was"""
        if self.status_row is None:
            return
        width = shutil.get_terminal_size().columns
        out = "\x1b7"
        for i, line in enumerate(self.status_lines(width)):
            out += f"\x1b[{self.status_row + i};1H\x1b[2K{line}"
        sys.stdout.write(out + "\x1b8")
        sys.stdout.flush()

    async def status_updater(self):
        """Redraw the status panel twice a second"""
        while self.running:
            self.draw_status()
            await asyncio.sleep(0.5)

    def start_video(self):
        """Stream the front camera into a window"""
        # The video track's frames only start flowing once switched on
        self.conn.video.add_track_callback(self.on_video_track)
        self.conn.video.switchVideoChannel(True)
        self.windows[VIDEO_WINDOW] = (self.camera_image, self.stop_video)

    async def on_video_track(self, track):
        """Keep the newest camera frame; the viewer decodes only what it shows"""
        while self.running:
            self.video_frame = await track.recv()

    def camera_image(self):
        """The newest camera frame if not shown yet, else None"""
        frame, self.video_frame = self.video_frame, None
        return None if frame is None else frame.to_ndarray(format="bgr24")

    def stop_video(self):
        """Turn the camera stream off once its window is closed"""
        self.print_action("📷 Video window closed")
        self.conn.video.switchVideoChannel(False)

    async def start_lidar(self):
        """Stream the LiDAR voxel map, and the pose it is drawn around, into a window"""
        datachannel = self.conn.datachannel
        await datachannel.disableTrafficSaving(True)  # needed for the voxel map stream
        datachannel.set_decoder("native")  # plain points instead of the libvoxel mesh
        datachannel.pub_sub.publish_without_callback(RTC_TOPIC["ULIDAR_SWITCH"], "on")
        datachannel.pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], self.on_lidar_map)
        datachannel.pub_sub.subscribe(RTC_TOPIC["ROBOTODOM"], self.store_telemetry("ROBOTODOM"))
        self.windows[LIDAR_WINDOW] = (self.lidar_image, self.stop_lidar)

    def on_lidar_map(self, message):
        """Keep the newest voxel map (world-frame points around the robot)"""
        data = message["data"]
        self.lidar_map = (data["data"]["points"], data["resolution"])

    def lidar_image(self):
        """Top-down view of the newest voxel map, robot in the centre facing up.

        Colour is height above the floor; None until a new map and a pose are in.
        """
        pose = self.latest("ROBOTODOM")
        if self.lidar_map is None or pose is None:
            return None
        (points, resolution), self.lidar_map = self.lidar_map, None
        position, q = pose["pose"]["position"], pose["pose"]["orientation"]
        yaw = math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]), 1 - 2 * (q["y"] ** 2 + q["z"] ** 2))
        sport = self.latest("LF_SPORT_MOD_STATE")
        floor = position["z"] - (sport["body_height"] if sport else 0.32)

        # Into the robot frame (x forward, y left), then forward is up on screen
        dx, dy = points[:, 0] - position["x"], points[:, 1] - position["y"]
        cos, sin = math.cos(yaw), math.sin(yaw)
        forward, left = cos * dx + sin * dy, cos * dy - sin * dx
        center = LIDAR_SIZE // 2
        rows = np.round(center - forward * LIDAR_SCALE).astype(int)
        cols = np.round(center - left * LIDAR_SCALE).astype(int)
        height = points[:, 2] - floor
        codes = np.where(height < FLOOR_BAND, 1,
                         2 + np.clip(height / LIDAR_TOP, 0, 1) * 253).astype(np.uint8)
        inside = (rows >= 0) & (rows < LIDAR_SIZE) & (cols >= 0) & (cols < LIDAR_SIZE)
        grid = np.zeros((LIDAR_SIZE, LIDAR_SIZE), np.uint8)
        np.maximum.at(grid, (rows[inside], cols[inside]), codes[inside])
        # Grow points to voxel size (a bit over, so the rotated grid has no
        # gaps); as seen from above, the tallest one wins
        voxel = round(resolution * LIDAR_SCALE) + 2
        grid = cv2.dilate(grid, np.ones((voxel, voxel), np.uint8))
        image = cv2.LUT(cv2.merge([grid] * 3), LIDAR_COLORS)

        # Range rings every metre, and the robot as an arrow
        for metres in range(1, LIDAR_SIZE // (2 * LIDAR_SCALE) + 1):
            radius = metres * LIDAR_SCALE
            cv2.circle(image, (center, center), radius, (70, 70, 70), 1, cv2.LINE_AA)
            cv2.putText(image, f"{metres} m", (center + 4, center - radius + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (140, 140, 140), 1, cv2.LINE_AA)
        arrow = np.array([(0, -22), (-11, 12), (0, 5), (11, 12)]) + center
        cv2.fillPoly(image, [arrow], (255, 255, 255), cv2.LINE_AA)
        cv2.putText(image, f"height 0-{LIDAR_TOP} m: blue to red, grey = floor",
                    (8, LIDAR_SIZE - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        return image

    def stop_lidar(self):
        """Stop streaming the map; the LiDAR itself stays on for obstacle avoidance"""
        self.print_action("📡 LiDAR window closed")
        for topic in ("ULIDAR_ARRAY", "ROBOTODOM"):
            self.conn.datachannel.pub_sub.unsubscribe(RTC_TOPIC[topic])

    async def window_pump(self):
        """Show camera and LiDAR images; keys typed in their windows control the robot too.

        OpenCV windows must live on the main thread (macOS), so this runs as a
        task on the event loop and pumps the windows with short waitKey calls.
        """
        shown = set()
        while self.running and self.windows:
            for name, (get_image, _) in self.windows.items():
                image = get_image()
                if image is not None:
                    cv2.imshow(name, image)
                    shown.add(name)
            if shown:
                # waitKeyEx: plain waitKey folds arrow keys into letters on Linux
                key = cv2.waitKeyEx(1)
                if 0 <= key < 128:
                    self.window_keys.append(key)
            for name in list(shown):
                try:
                    closed = cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1
                except cv2.error:
                    closed = True
                if closed:
                    shown.discard(name)
                    _, on_close = self.windows.pop(name)
                    on_close()
            await asyncio.sleep(0.01)

    def close_windows(self):
        """Close the OpenCV windows (they only go away once events are pumped)"""
        cv2.destroyAllWindows()
        cv2.waitKey(1)

    def reset_screen(self):
        """Release the scroll region and put the cursor at the bottom"""
        height = shutil.get_terminal_size().lines
        sys.stdout.write(f"\x1b[r\x1b[{height};1H\r\n")
        sys.stdout.flush()

    async def execute_sport_command(self, command_name, parameter=None):
        """Execute a sport command"""
        if self.conn:
            try:
                if parameter is None:
                    parameter = {"data": True}
                response = await self.conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {"api_id": SPORT_CMD[command_name], "parameter": parameter},
                )
                self.print_response(command_name, response)
            except Exception as e:
                self.print_result(f"❌ Error sending {command_name} command: {e}")
    
    async def handle_key_action(self, key):
        """Handle a key press based on the key_actions configuration"""
        if key not in self.key_actions:
            return
            
        action = self.key_actions[key]
        
        # Print the action message; commands append their reply on the same line
        sends = 'params' in action or 'command' in action
        self.print_action(action['message'], end='' if sends else '\n')
        
        # Execute the appropriate action
        if 'params' in action:
            # Movement action
            await self.move_robot(**action['params'])
        elif 'command' in action:
            # Sport command action
            await self.execute_sport_command(action['command'])
        elif key == 'esc':
            # Exit action
            self.running = False
    
    async def keyboard_listener(self):
        """Listen for keyboard input and control robot"""
        # Setup terminal for non-blocking input
        old_settings = termios.tcgetattr(sys.stdin)

        # Set terminal to raw mode for immediate key capture
        tty.setraw(sys.stdin.fileno())

        # Pin the help menu to the top; redraw it when the window is resized
        self.print_help()
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGWINCH, self.print_help)
        status_task = asyncio.create_task(self.status_updater())
        window_task = asyncio.create_task(self.window_pump()) if self.windows else None
        self.print_action("🤖 Robot Control Started! Press 'ESC' to exit.")
        
        try:
            while self.running:
                key = self.get_key()
                
                if key is None:
                    await asyncio.sleep(0.02)
                    continue

                # Handle all other actions
                await self.handle_key_action(key)
                
                # Break if exit was requested
                if not self.running:
                    break
                
                await asyncio.sleep(0.1)  # Small delay to prevent overwhelming the robot
                
        finally:
            # Restore terminal settings
            status_task.cancel()
            if window_task:
                window_task.cancel()
                self.close_windows()
            loop.remove_signal_handler(signal.SIGWINCH)
            self.reset_screen()
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

def parse_args():
    parser = argparse.ArgumentParser(description="Keyboard control for the Unitree Go2")
    parser.add_argument("--ip", default=os.environ.get("ROBOT_IP"),
                        help="connect to this IP instead of auto-discovering (env ROBOT_IP)")
    parser.add_argument("--serial", default=os.environ.get("ROBOT_SERIAL"),
                        help="pick this robot when discovery finds several (env ROBOT_SERIAL)")
    parser.add_argument("--ap", action="store_true",
                        help="connect over the robot's own Wi-Fi access point (192.168.12.1)")
    parser.add_argument("--aes-key", default=os.environ.get("UNITREE_AES_KEY"),
                        help="per-device AES-128 key, needed on Go2 firmware >= 1.1.15 (env UNITREE_AES_KEY)")
    parser.add_argument("--timeout", type=float, default=3,
                        help="seconds to wait for discovery replies (default 3)")
    parser.add_argument("--video", action="store_true",
                        help="show the front camera in a window (keys work there too)")
    parser.add_argument("--lidar", action="store_true",
                        help="show a top-down LiDAR map in a window (keys work there too)")
    return parser.parse_args()


def discover_robot(serial, timeout):
    """Find the robot's IP by multicast; return None if it can't be chosen"""
    found = discover_ip_sn(timeout=timeout, sn=serial)
    if serial:
        if serial in found:
            return found[serial]
        print(f"❌ Robot {serial} not found on the network")
        return None
    if not found:
        print("❌ No robots found on the network. Use --ip to connect directly.")
        return None
    if len(found) > 1:
        print("❌ Several robots found, pick one with --serial or --ip:")
        for sn, ip in found.items():
            print(f"   {sn}  {ip}")
        return None
    return next(iter(found.values()))


def create_connection(args):
    """Build the connection: AP mode, a given IP, or an auto-discovered IP"""
    if args.ap:
        print("📡 Using the robot's access point")
        return UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalAP, aes_128_key=args.aes_key)
    ip = args.ip
    if not ip:
        print("🔍 Discovering robot...")
        ip = discover_robot(args.serial, args.timeout)
        if not ip:
            return None
    print(f"🌐 Using IP: {ip}")
    return UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=ip, aes_128_key=args.aes_key)


async def main():
    args = parse_args()
    if not sys.stdin.isatty():
        print("❌ Keyboard control needs an interactive terminal")
        return
    controller = KeyboardController()
    conn = None
    # Show robot errors in the status panel instead of the driver's printout
    webrtc_datachannel.handle_error = controller.on_robot_errors

    try:
        conn = create_connection(args)
        if conn is None:
            return
        
        controller.conn = conn
        
        # Connect to the WebRTC service.
        print("🔗 Connecting to robot...")
        await conn.connect()
        print("✅ Connected successfully!")
        controller.start_telemetry()
        if args.video:
            controller.start_video()
        if args.lidar:
            await controller.start_lidar()
        
        ####### NORMAL MODE ########
        print("🔍 Checking current motion mode...")
        # Get the current motion_switcher status
        response = await conn.datachannel.pub_sub.publish_request_new(
            RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001}
        )
        
        current_motion_switcher_mode = None
        if response["data"]["header"]["status"]["code"] == 0:
            data = json.loads(response["data"]["data"])
            current_motion_switcher_mode = data["name"]
            print(f"🤖 Current motion mode: {current_motion_switcher_mode}")
        
        # Switch to "normal" mode if not already
        if current_motion_switcher_mode != "normal":
            print(f"🔄 Switching motion mode from {current_motion_switcher_mode} to 'normal'...")
            await conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["MOTION_SWITCHER"],
                {"api_id": 1002, "parameter": {"name": "normal"}},
            )
            await asyncio.sleep(5)  # Wait while it stands up
            print("✅ Motion mode switched to normal")
        
        await asyncio.sleep(1)

        # Leave joint-locked stand (e.g. after a dropped session) so Move works
        print("⚖️ Switching to Balance Stand...", end="", flush=True)
        await controller.execute_sport_command("BalanceStand")
        await asyncio.sleep(1)
        
        # Start keyboard control
        await controller.keyboard_listener()
        
    except ValueError as e:
        # Log any value errors that occur during the process.
        print(f"❌ {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Close the peer connection explicitly: aiortc's receiver threads only
        # stop on pc.close(), and left running they block interpreter exit
        if conn is not None:
            try:
                await asyncio.wait_for(conn.disconnect(), timeout=5)
            except Exception as e:
                print(f"⚠️ Disconnect did not finish cleanly: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle Ctrl+C to exit gracefully.
        print("\nProgram interrupted by user")
        sys.exit(0)
