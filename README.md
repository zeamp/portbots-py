# Portbots.py - Multi-IP IRC Botnet Client

Portbots.py is a Python-based IRC bot client designed to spawn and manage multiple IRC bots across all available system IP addresses (both IPv4 and IPv6). Each bot runs independently with a unique nickname, ident, and real name, and they collectively connect to an IRC server and coordinate actions inside a designated hub channel.

Features:

* Multi-IP Binding: Detects all available network addresses and binds individual bots to unique IPs.
* Coordinator System: One “coordinator bot” manages operator propagation and centralizes op distribution.
* Channel Management: Bots can join, part, and rejoin channels automatically if kicked, with periodic retry logic.
* Command Handling: Supports bot master commands (.mjoin, .mpart, .msay, .maction, .mmode, .opall, .help) sent through the hub channel.
* CTCP Support: Responds to CTCP VERSION, TIME, and PING requests with system information and timestamps.
* Idle Activity: Sends random anti-idle messages periodically to maintain presence.
* Op Propagation: Coordinator distributes ops to online bots in safe, chunked batches to avoid flooding.
* Resilience: Supports optional persistent reconnect mode with configurable reconnect delays.
* Status Tracking: Periodically reports the number of connected/online bots to the console.
* System Awareness: Provides system uptime, CTCP version replies, and platform information.

Portbots is primarily a multi-bot management framework for IRC networks, useful for stress-testing, bot orchestration, or experimental distributed coordination. It is configurable and supports large IRC bot counts while respecting clone limits.

Inspired by a Perl script written in the late 1990s by Samy Kamkar (CommPort5).
