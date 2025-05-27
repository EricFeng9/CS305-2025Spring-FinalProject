import json, time, threading
from utils import generate_message_id


known_peers = {}        # { peer_id: (ip, port) }
peer_flags = {}         # { peer_id: { 'nat': True/False, 'light': True/False } }
reachable_by = {}       # { peer_id: { set of peer_ids who can reach this peer }}
peer_config={}

def start_peer_discovery(self_id, self_info):
    from outbox import enqueue_message
    def loop():
        # TODO: Define the JSON format of a `hello` message, which should include: `{message type, sender’s ID, IP address, port, flags, and message ID}`. 
        # A `sender’s ID` can be `peer_port`. 
        # The `flags` should indicate whether the peer is `NATed or non-NATed`, and `full or lightweight`. 
        # The `message ID` can be a random number.

        # TODO: Send a `hello` message to all known peers and put the messages into the outbox queue.

        msg = {
            "type": "HELLO",
            "sender_id": self_id,
            "ip": self_info["ip"],
            "port": self_info["port"],
            "flags": {
                "nat": self_info.get("nat", False),
                "light": self_info.get("light", False)
            },
            "message_id": generate_message_id()
        }

        msg_str = json.dumps(msg) + "\n"

        for peer_id, (peer_ip, peer_port) in known_peers.items():
            enqueue_message(peer_id, peer_ip, peer_port, msg_str)

    threading.Thread(target=loop, daemon=True).start()

def handle_hello_message(msg, self_id):
    new_peers = []
    
    # TODO: Read information in the received `hello` message.
     
    # TODO: If the sender is unknown, add it to the list of known peers (`known_peer`) and record their flags (`peer_flags`).
     
    # TODO: Update the set of reachable peers (`reachable_by`).

    new_peers = []

    sender_id = msg.get("sender_id")
    sender_ip = msg.get("ip")
    sender_port = msg.get("port")
    sender_flags = msg.get("flags", {})

    # 不处理自己的HELLO
    if sender_id == self_id:
        return []

    # 添加到已知节点表
    if sender_id not in known_peers:
        known_peers[sender_id] = (sender_ip, sender_port)
        peer_flags[sender_id] = {
            "nat": sender_flags.get("nat", False),
            "light": sender_flags.get("light", False)
        }
        new_peers.append(sender_id)

    # 可达性更新
    if sender_id not in reachable_by:
        reachable_by[sender_id] = set()

    reachable_by[sender_id].add(self_id)

    return new_peers 


