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
import os
import sys
import termios
import tty
import select
import unicodedata
import shutil
import signal
from unitree_webrtc_connect import (
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
    RTC_TOPIC,
    SPORT_CMD,
    discover_ip_sn,
)

# Enable logging for debugging
logging.basicConfig(level=logging.FATAL)

class KeyboardController:
    def __init__(self):
        self.running = True
        self.conn = None
        
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
            'l': {
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
        """Get keyboard input for Mac OS X"""
        if select.select([sys.stdin], [], [], 0.1)[0]:
            key = sys.stdin.read(1).lower()
            if key in ('\x1b', '\x03'):  # ESC, or Ctrl+C (no SIGINT in raw mode)
                return 'esc'
            elif key == ' ':  # Space
                return 'space'
            elif key in self.get_valid_keys():
                return key
        return None
    
    def print_action(self, message):
        """Print action message with proper formatting for raw terminal mode"""
        print(f"\r{message}\n", end='', flush=True)

    def check_response(self, command_name, response):
        """Print the robot's reply if it rejected the command"""
        try:
            status = response["data"]["header"]["status"]
        except (KeyError, TypeError):
            return
        if status.get("code") != 0:
            self.print_action(f"⚠️ Robot rejected {command_name}: {status} {response['data'].get('data', '')}")
    
    async def move_robot(self, x=0, y=0, z=0):
        """Send movement command to robot"""
        if self.conn:
            try:
                response = await self.conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"],
                    {"api_id": SPORT_CMD["Move"], "parameter": {"x": x, "y": y, "z": z}},
                )
                self.check_response("Move", response)
            except Exception as e:
                self.print_action(f"Error sending movement command: {e}")
    
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
        return lines

    def print_help(self):
        """Draw the help menu pinned to the top; actions scroll below it"""
        width, height = shutil.get_terminal_size()
        lines = self.help_lines(width)
        # Reset scroll region, clear screen, draw the menu at the top
        out = "\x1b[r\x1b[2J\x1b[H" + "\r\n".join(lines) + "\r\n"
        if len(lines) < height - 1:
            # Restrict scrolling to the area below the menu
            top = len(lines) + 1
            out += f"\x1b[{top};{height}r\x1b[{top};1H"
        sys.stdout.write(out)
        sys.stdout.flush()

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
                self.check_response(command_name, response)
            except Exception as e:
                self.print_action(f"Error sending {command_name} command: {e}")
    
    async def handle_key_action(self, key):
        """Handle a key press based on the key_actions configuration"""
        if key not in self.key_actions:
            return
            
        action = self.key_actions[key]
        
        # Print the action message
        self.print_action(action['message'])
        
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
        self.print_action("🤖 Robot Control Started! Press 'ESC' to exit.")
        
        try:
            while self.running:
                key = self.get_key()
                
                if key is None:
                    await asyncio.sleep(0.1)
                    continue

                # Handle all other actions
                await self.handle_key_action(key)
                
                # Break if exit was requested
                if not self.running:
                    break
                
                await asyncio.sleep(0.1)  # Small delay to prevent overwhelming the robot
                
        finally:
            # Restore terminal settings
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

    try:
        conn = create_connection(args)
        if conn is None:
            return
        
        controller.conn = conn
        
        # Connect to the WebRTC service.
        print("🔗 Connecting to robot...")
        await conn.connect()
        print("✅ Connected successfully!")
        
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
        print("⚖️ Switching to Balance Stand...")
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
