# Portbots.py - Multi-IP IRC Botnet Client
# by Richard Ward (zeamp)
# How To Run: screen -dm python portbots.py
#
# Portbots.py is a Python-based IRC bot client designed to spawn and manage multiple IRC bots across all available system IP addresses (both IPv4 and IPv6).
# Each bot runs independently with a unique nickname, ident, and real name, and they collectively connect to an IRC server and coordinate actions inside a designated hub channel.
# Portbots is primarily a multi-bot management framework for IRC networks, useful for stress-testing, bot orchestration, or experimental distributed coordination.
# It is configurable and supports large IRC bot counts while respecting clone limits.

import socket
import threading
import random
import time
import subprocess
import re
import ipaddress
import platform

# --- Configuration ---
SERVER = "irc.2600.net"
PORT = 6667
HUB_CHANNEL = "#uptown"
BOT_MASTER = "zeamp"
BASE_BOT_NICK = "port"
COORDINATOR_BOT_NICK = f"{BASE_BOT_NICK}001c" # Only this bot will initiate op propagation
REJOIN_INTERVAL = 60 # Seconds between re-join attempts (1 minute)
RECONNECT_DELAY = 60 # Seconds to wait before attempting to reconnect
MAX_BOTS = 200 # Set a maximum number of bots to avoid clone limits

# A new global setting to enable or disable persistent reconnection
PERSISTENT_RECONNECT = False
# A new setting for how often to report the status of connected bots
STATUS_REPORT_INTERVAL = 60 # Seconds between status reports

# A list of random anti-idle messages
IDLE_MESSAGES = [
    "lol", "ok", "hmm", "yes", "no", "maybe", "brb", "afk", "yo", "nice.", "hey"
]

# A list of real names for the bots
REAL_NAMES = [
    "Kim", "Bob", "John", "Steve", "Alex", "Sam", "Pat", "Chris", "Jay", "Lee",
    "Max", "Casey", "Taylor", "Jordan", "Terry", "Robin", "Charlie", "Jamie", "Drew", "Ryan"
]

# A list of all bot nicknames for easy checking
ALL_BOT_NICKS = []
# A set to track bots that successfully connected to the server and joined the hub channel
ONLINE_BOTS = set()
online_lock = threading.Lock()
# A set to keep track of opped bots to prevent loops and manage .opall
OPPED_BOTS = set()
op_lock = threading.Lock()

# Get system info for CTCP version
SYSTEM_INFO = f"{platform.system()} {platform.machine()}"

# --- Helper Functions ---
def get_ip_addresses():
    """Looks up all IPv4 and IPv6 addresses on the system."""
    try:
        output = subprocess.check_output(['ip', '-o', 'addr']).decode('utf-8')
        ip_list = []
        for line in output.split('\n'):
            match = re.search(r'inet6? ([\w.:/]+)', line)
            if match:
                ip_addr = match.group(1).split('/')[0]
                try:
                    ip_obj = ipaddress.ip_address(ip_addr)
                    if not ip_obj.is_loopback and not ip_obj.is_link_local:
                        ip_list.append(ip_addr)
                except ValueError:
                    continue
        return list(set(ip_list))
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'ip' command not found or failed.")
        return []

def get_system_uptime():
    """Gets the system uptime in a human-readable format."""
    try:
        uptime_seconds = float(subprocess.check_output(["cat", "/proc/uptime"]).decode().split()[0])
        days = int(uptime_seconds // (24 * 3600))
        hours = int((uptime_seconds % (24 * 3600)) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        uptime_str = f"Uptime: "
        if days > 0:
            uptime_str += f"{days}d "
        if hours > 0:
            uptime_str += f"{hours}h "
        uptime_str += f"{minutes}m"
        
        return uptime_str.strip()
    except (FileNotFoundError, ValueError, IndexError):
        return "Uptime: N/A"

def generate_nick(bot_id=0):
    """Generates a unique nick using the configurable BASE_BOT_NICK.
    Appends 'c' to the first bot's nick to make it the coordinator."""
    if bot_id == 1:
        return f"{BASE_BOT_NICK}{bot_id:03d}c"
    else:
        return f"{BASE_BOT_NICK}{bot_id:03d}"

def generate_ident():
    """Generates a random ident string."""
    chars = "abcdefghijklmnopqrstuvwxyz"
    return "".join(random.choice(chars) for _ in range(4)) + f"{random.randint(0, 99):02d}"

# --- Bot Class ---
class IRC_Bot:
    def __init__(self, ip_address, nick, ident, realname):
        self.ip_address = ip_address
        self.nick = nick
        self.ident = ident
        self.realname = realname
        self.sock = None
        self.connected = False
        self.channels = set()
        self.last_idle_message = 0
        self.is_coordinator = (self.nick == COORDINATOR_BOT_NICK)
        self.kicked_channels = {} # Stores {channel: last_attempt_timestamp}

    def connect(self):
        """Connects to the IRC server."""
        try:
            family = socket.AF_INET6 if ":" in self.ip_address else socket.AF_INET
            self.sock = socket.socket(family, socket.SOCK_STREAM)
            self.sock.bind((self.ip_address, 0))
            self.sock.connect((SERVER, PORT))
            self.connected = True
            print(f"[{self.nick}] Connecting from IP: {self.ip_address}")
            self.send_raw(f"NICK {self.nick}")
            self.send_raw(f"USER {self.ident} 0 * :{self.realname}")
            return True
        except Exception as e:
            print(f"[{self.nick}] Failed to connect: {e}")
            self.connected = False
            # Remove the bot from the online list upon connection failure
            with online_lock:
                if self.nick in ONLINE_BOTS:
                    ONLINE_BOTS.discard(self.nick)
            with op_lock:
                if self.nick in OPPED_BOTS:
                    OPPED_BOTS.discard(self.nick)
            return False

    def send_raw(self, message):
        """Sends a raw message to the IRC server."""
        if self.sock:
            self.sock.send(f"{message}\r\n".encode('utf-8'))
            print(f"[{self.nick}] -> {message}")
            time.sleep(0.5)

    def process_line(self, line):
        """Handles a single line of data from the server."""
        sender_nick = line.split('!', 1)[0][1:]
        
        if line.startswith('PING'):
            # Correctly handle PING-PONG for connection stability
            ping_payload = line.split(':', 1)[-1]
            print(f"[{self.nick}] <- PING, sending PONG to keep connection alive...")
            self.send_raw(f"PONG :{ping_payload}")
            return

        if "\x01" in line:
            ctcp_command = line.split(":", 2)[-1].strip().split('\x01')[1]
            ctcp_parts = ctcp_command.split()
            
            if ctcp_parts[0].upper() == "VERSION":
                self.send_raw(f"NOTICE {sender_nick} :\x01VERSION Portbots v2.29 ({SYSTEM_INFO})\x01")
            elif ctcp_parts[0].upper() == "TIME":
                self.send_raw(f"NOTICE {sender_nick} :\x01TIME {time.ctime(time.time())}\x01")
            elif ctcp_parts[0].upper() == "PING":
                # Handle CTCP PING with timestamp for lag calculation
                if len(ctcp_parts) > 1:
                    timestamp = ctcp_parts[1]
                    self.send_raw(f"NOTICE {sender_nick} :\x01PING {timestamp}\x01")
                
            return

        parts = line.split(' ')
        
        try:
            # Handle KICK messages
            if parts[1] == 'KICK' and len(parts) > 3:
                channel = parts[2]
                target_nick = parts[3]
                if target_nick == self.nick:
                    print(f"[{self.nick}] Kicked from {channel}! Attempting to rejoin...")
                    self.channels.discard(channel)
                    self.kicked_channels[channel] = time.time()
                    self.send_raw(f"JOIN {channel}")
                    # Remove the bot from the opped list upon being kicked
                    with op_lock:
                        if self.nick in OPPED_BOTS:
                            OPPED_BOTS.discard(self.nick)
                            print(f"[{self.nick}] De-opped due to kick.")
            
            # Handle MODE messages
            elif parts[1] == 'MODE' and len(parts) > 3:
                channel = parts[2]
                mode_str = parts[3]
                
                with op_lock:
                    param_index = 4
                    for mode_char in mode_str:
                        if mode_char in '+-':
                            mode_sign = mode_char
                            continue
                        
                        if mode_char in 'o':
                            # This mode change affects a user, so get the corresponding parameter
                            if param_index < len(parts):
                                target_nick = parts[param_index]
                                if target_nick in ALL_BOT_NICKS:
                                    if mode_sign == '+':
                                        OPPED_BOTS.add(target_nick)
                                        # Op-propagation is now handled ONLY by the coordinator bot
                                        if self.is_coordinator and self.nick == target_nick:
                                            print(f"[{self.nick}] I have been opped in {channel}! Taking control.")
                                            with online_lock:
                                                un_opped_bots = [n for n in ONLINE_BOTS if n not in OPPED_BOTS]
                                            if un_opped_bots:
                                                chunk_size = 4
                                                for i in range(0, len(un_opped_bots), chunk_size):
                                                    chunk = un_opped_bots[i:i + chunk_size]
                                                    op_modes = '+' + 'o' * len(chunk)
                                                    op_nicks = ' '.join(chunk)
                                                    self.send_raw(f"MODE {channel} {op_modes} {op_nicks}")
                                    elif mode_sign == '-':
                                        if target_nick in OPPED_BOTS:
                                            OPPED_BOTS.discard(target_nick)
                                            print(f"[{self.nick}] {target_nick} has been deopped.")
                                # Move to the next parameter for the next mode char
                                param_index += 1
                                
        except IndexError:
            # Silently ignore mode changes that don't match the expected format, like user modes (+iw)
            pass

        # Update the list of online bots after joining the channel
        if "End of /MOTD command." in line:
            self.send_raw(f"JOIN {HUB_CHANNEL}")
            self.channels.add(HUB_CHANNEL)
            self.last_idle_message = time.time()
            with online_lock:
                ONLINE_BOTS.add(self.nick)
        
        # Handle bot master commands and user-to-bot messages
        if f"PRIVMSG {HUB_CHANNEL}" in line:
            if sender_nick == BOT_MASTER:
                message = line.split(':', 2)[-1].strip()
                parts = message.split()
                if not parts: return

                cmd = parts[0]
                args = parts[1:]

                if cmd == ".mjoin" and len(args) > 0:
                    self.send_raw(f"JOIN {args[0]}")
                    self.channels.add(args[0])
                elif cmd == ".mpart" and len(args) > 0:
                    target_channel = args[0]
                    if target_channel == HUB_CHANNEL:
                        self.send_raw(f"NOTICE {sender_nick} :Cannot part the hub channel.")
                    else:
                        self.send_raw(f"PART {target_channel}")
                        self.channels.discard(target_channel)
                elif cmd == ".msay" and len(args) > 1:
                    target = args[0]
                    msg = " ".join(args[1:])
                    self.send_raw(f"PRIVMSG {target} :{msg}")
                elif cmd == ".maction" and len(args) > 1:
                    target = args[0]
                    msg = " ".join(args[1:])
                    self.send_raw(f"PRIVMSG {target} :\x01ACTION {msg}\x01")
                elif cmd == ".mmode" and len(args) > 1:
                    target = args[0]
                    modes = " ".join(args[1:])
                    self.send_raw(f"MODE {target} {modes}")
                elif cmd == ".opall" and len(args) > 0:
                    target_channel = args[0]
                    with op_lock:
                        with online_lock:
                            un_opped_bots = [n for n in ONLINE_BOTS if n not in OPPED_BOTS]
                    if un_opped_bots:
                        chunk_size = 4
                        for i in range(0, len(un_opped_bots), chunk_size):
                            chunk = un_opped_bots[i:i + chunk_size]
                            op_modes = '+' + 'o' * len(chunk)
                            op_nicks = ' '.join(chunk)
                            self.send_raw(f"MODE {target_channel} {op_modes} {op_nicks}")
                    else:
                        self.send_raw(f"NOTICE {sender_nick} :All bots are already opped.")
                elif cmd == ".help":
                    version_string = f"Portbots v2.29 ({SYSTEM_INFO})"
                    uptime_string = get_system_uptime()
                    help_msg = "Commands: .mjoin <channel>, .mpart <channel>, .msay <channel> <msg>, .maction <channel> <msg>, .mmode <channel> <modes>, .opall <channel>, .help"
                    self.send_raw(f"NOTICE {sender_nick} :{version_string} | {uptime_string}")
                    self.send_raw(f"NOTICE {sender_nick} :{help_msg}")

    def run(self):
        """The main loop for the bot, now with an optional persistent connection mode."""
        if PERSISTENT_RECONNECT:
            while True:
                if self.connect():
                    self._run_main_loop()
                print(f"[{self.nick}] Retrying connection in {RECONNECT_DELAY} seconds...")
                time.sleep(RECONNECT_DELAY)
        else:
            self.connect()
            self._run_main_loop()
        
        if self.sock:
            self.sock.close()

    def _run_main_loop(self):
        """The main loop for an active bot."""
        while self.connected:
            try:
                # --- Periodic Re-join Attempt ---
                current_time = time.time()
                channels_to_rejoin = list(self.kicked_channels.keys())
                for channel in channels_to_rejoin:
                    if current_time - self.kicked_channels[channel] > REJOIN_INTERVAL:
                        print(f"[{self.nick}] Trying to re-join {channel}...")
                        self.send_raw(f"JOIN {channel}")
                        self.kicked_channels[channel] = current_time # Update timestamp for next attempt
                
                # --- Idle Message ---
                idle_duration = random.randint(3600, 18000)
                if time.time() - self.last_idle_message > idle_duration:
                    random_msg = random.choice(IDLE_MESSAGES)
                    self.send_raw(f"PRIVMSG {HUB_CHANNEL} :{random_msg}")
                    self.last_idle_message = time.time()
                
                self.sock.settimeout(1.0)
                data = self.sock.recv(2048).decode('utf-8', 'ignore')
                if not data:
                    print(f"[{self.nick}] Disconnected from server.")
                    self.connected = False
                    # Remove the bot from the online list upon disconnection
                    with online_lock:
                        if self.nick in ONLINE_BOTS:
                            ONLINE_BOTS.discard(self.nick)
                    with op_lock:
                        if self.nick in OPPED_BOTS:
                            OPPED_BOTS.discard(self.nick)
                    break
                
                for line in data.strip().split('\r\n'):
                    print(f"[{self.nick}] <- {line}")
                    self.process_line(line)
            except socket.timeout:
                continue
            except (socket.error, ConnectionResetError) as e:
                print(f"[{self.nick}] Socket error: {e}")
                self.connected = False
                # Remove the bot from the online list upon disconnection
                with online_lock:
                    if self.nick in ONLINE_BOTS:
                        ONLINE_BOTS.discard(self.nick)
                with op_lock:
                    if self.nick in OPPED_BOTS:
                        OPPED_BOTS.discard(self.nick)
                break

def print_online_status(num_bots_to_create):
    """A separate thread function to periodically print the number of online bots."""
    while True:
        time.sleep(STATUS_REPORT_INTERVAL)
        with online_lock:
            online_count = len(ONLINE_BOTS)
        print(f"\nStatus: {online_count}/{num_bots_to_create} bots online.\n")


# --- Main Execution ---
if __name__ == "__main__":
    print("Portbots v2.29")
    ip_addresses = get_ip_addresses()
    if not ip_addresses:
        print("No usable IP addresses found. Exiting.")
    else:
        print("Found IP addresses:", ip_addresses)
        
        # Ensure the number of bots to create doesn't exceed the available IPs or the MAX_BOTS limit
        num_bots_to_create = min(len(ip_addresses), MAX_BOTS)
        
        # Start the status reporter thread
        status_thread = threading.Thread(target=print_online_status, args=(num_bots_to_create,))
        status_thread.daemon = True
        status_thread.start()

        print(f"Waiting 15 seconds to create bots...")
        time.sleep(15)
        print(f"Attempting to create {num_bots_to_create} bots...")

        # Create and launch the coordinator bot first
        coordinator_ip = ip_addresses[0]
        coordinator_nick = generate_nick(bot_id=1)
        ALL_BOT_NICKS.append(coordinator_nick)
        coordinator_ident = generate_ident()
        coordinator_realname = random.choice(REAL_NAMES)
        
        print(f"Creating coordinator bot {coordinator_nick} for IP {coordinator_ip}...")
        coordinator_bot = IRC_Bot(coordinator_ip, coordinator_nick, coordinator_ident, coordinator_realname)
        coordinator_thread = threading.Thread(target=coordinator_bot.run)
        coordinator_thread.daemon = True
        coordinator_thread.start()

        # Create and launch the remaining bots
        for i in range(1, num_bots_to_create):
            ip = ip_addresses[i]
            nick = generate_nick(bot_id=i + 1)
            ALL_BOT_NICKS.append(nick)
            ident = generate_ident()
            realname = random.choice(REAL_NAMES)
            
            print(f"Creating bot {nick} for IP {ip}...")
            bot = IRC_Bot(ip, nick, ident, realname)
            thread = threading.Thread(target=bot.run)
            thread.daemon = True
            thread.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down portbots...")
