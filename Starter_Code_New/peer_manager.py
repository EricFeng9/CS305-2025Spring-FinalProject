import threading
import time
import json
from collections import defaultdict

from utils import generate_message_id

peer_status = {}  # {peer_id: 'ALIVE', 'UNREACHABLE' or 'UNKNOWN'}
last_ping_time = {}  # {peer_id: timestamp}
rtt_tracker = {}  # {peer_id: transmission latency}

PING_INTERVAL = 5  # 每隔 5 秒 ping 一次
PING_TIMEOUT = 10  # 超过 10 秒无响应就标记 UNREACHABLE


# === Check if peers are alive ===

def start_ping_loop(self_id, peer_table):
    from outbox import enqueue_message

    def loop():
        # TODO: Define the JSON format of a `ping` message, which should include `{message typy, sender's ID,
        #  timestamp}`.

        # TODO: Send a `ping` message to each known peer periodically.
        while True:
            now = time.time()
            for peer_id, (ip, port) in peer_table.items():
                msg = {
                    "type": "PING",
                    "sender_id": self_id,
                    "timestamp": now,
                    "message_id": generate_message_id()
                }
                msg_str = json.dumps(msg) + "\n"
                enqueue_message(peer_id, ip, port, msg_str)
            time.sleep(PING_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


def create_pong(sender, recv_ts):
    # TODO: Create the JSON format of a `pong` message, which should include `{message type, sender's ID,
    #  timestamp in the received ping message}`.
    return json.dumps({
        "type": "PONG",
        "sender_id": sender,
        "timestamp": recv_ts,
        "message_id": generate_message_id()
    }) + "\n"


def handle_pong(msg):
    # TODO: Read the information in the received `pong` message.

    # TODO: Update the transmission latenty between the peer and the sender (`rtt_tracker`).
    sender_id = msg.get("sender_id")
    ping_ts = msg.get("timestamp")
    now = time.time()
    rtt = now - ping_ts

    rtt_tracker[sender_id] = rtt
    update_peer_heartbeat(sender_id)


def start_peer_monitor():
    import threading

    def loop():
        # TODO: Check the latest time to receive `ping` or `pong` message from each peer in `last_ping_time`.

        # TODO: If the latest time is earlier than the limit, mark the peer's status in `peer_status` as
        #  `UNREACHABLE` or otherwise `ALIVE`.

        while True:
            now = time.time()
            for peer_id, last_time in last_ping_time.items():
                if now - last_time > PING_TIMEOUT:
                    peer_status[peer_id] = 'UNREACHABLE'
                else:
                    peer_status[peer_id] = 'ALIVE'
            time.sleep(PING_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


def update_peer_heartbeat(peer_id):
    # TODO: Update the `last_ping_time` of a peer when receiving its `ping` or `pong` message.
    last_ping_time[peer_id] = time.time()


# === Blacklist Logic ===

blacklist = set()  # The set of banned peers

peer_offense_counts = defaultdict(int)  # The offence times of peers


def record_offense(peer_id):
    # TODO: Record the offence times of a peer when malicious behaviors are detected.

    # TODO: Add a peer to `blacklist` if its offence times exceed 3. 

    peer_offense_counts[peer_id] += 1
    if peer_offense_counts[peer_id] > 3:
        blacklist.add(peer_id)
