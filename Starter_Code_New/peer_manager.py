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
                # 直接发送字典对象，不转换为字符串
                enqueue_message(peer_id, ip, port, msg)
            time.sleep(PING_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


def create_pong(sender, recv_ts):
    # TODO: Create the JSON format of a `pong` message, which should include `{message type, sender's ID,
    #  timestamp in the received ping message}`.
    return {
        "type": "PONG",
        "sender_id": sender,
        "timestamp": recv_ts,
        "message_id": generate_message_id()
    }


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
    if peer_offense_counts[peer_id] > 0: #TODO:临时修改！我就是测试一下
        blacklist.add(peer_id)
        print(f"节点 {peer_id} 违规次数达到阈值，已加入黑名单")

# === Peer Status ===
def get_peer_status():
    """
    返回所有已知节点的状态信息
    
    Returns:
        dict: 包含所有节点状态的字典，格式为 {peer_id: status}
    """
    from peer_discovery import known_peers, peer_flags
    
    result = {}
    for peer_id, (ip, port) in known_peers.items():
        str_peer_id = str(peer_id)
        status = peer_status.get(str_peer_id, "UNKNOWN")
        
        # 获取节点RTT信息
        rtt = None
        if str_peer_id in rtt_tracker:
            rtt = rtt_tracker[str_peer_id]
        
        # 获取节点标志信息
        flags = peer_flags.get(str_peer_id, {})
        
        result[str_peer_id] = {
            "status": status,
            "rtt": rtt,
            "ip": ip,
            "port": port,
            "flags": flags,
            "blacklisted": str_peer_id in blacklist
        }
    
    return result