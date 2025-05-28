import json, time, threading
from utils import generate_message_id
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Lock for shared peer data structures
peer_data_lock = threading.Lock()

known_peers = {}        # { peer_id: (ip, port) }
peer_flags = {}         # { peer_id: { 'nat': True/False, 'light': True/False } }
reachable_by = {}       # { peer_id: { set of peer_ids who can reach this peer }}
peer_config={}

def start_peer_discovery(self_id, self_info):
    from outbox import enqueue_message
    
    # 确保用字符串类型的键
    str_self_id = str(self_id)
    
    # 初始化自己的可达性记录
    with peer_data_lock:
        if str_self_id not in reachable_by:
            reachable_by[str_self_id] = set()
    
    # 先立即发送一次HELLO消息，不等待循环
    msg = {
        "type": "HELLO",
        "sender_id": self_id,
        "ip": self_info["ip"],
        "port": self_info["port"],
        "flags": {
            "nat": self_info.get("nat", False),  # 使用False作为默认值而不是"unknown"
            "light": self_info.get("light", False)
        },
        "message_id": f"hello_init_{time.time()}"
    }

    msg_str = json.dumps(msg) + "\n"
    logger.info(f"节点 {self_id} 初始化发送HELLO消息，flags: nat={msg['flags']['nat']}, light={msg['flags']['light']}")

    # 向所有已知节点发送HELLO消息
    # Create a copy of known_peers for safe iteration
    current_known_peers_copy = {}
    with peer_data_lock:
        current_known_peers_copy = dict(known_peers)

    for peer_id, (peer_ip, peer_port) in current_known_peers_copy.items():
        if peer_id != self_id:  # 不给自己发送HELLO消息
            logger.info(f"向节点 {peer_id} ({peer_ip}:{peer_port}) 发送初始HELLO消息")
            enqueue_message(peer_id, peer_ip, peer_port, msg_str)
    
    def loop():
        # TODO: Define the JSON format of a `hello` message, which should include: `{message type, sender's ID, IP address, port, flags, and message ID}`. 
        # A `sender's ID` can be `peer_port`. 
        # The `flags` should indicate whether the peer is `NATed or non-NATed`, and `full or lightweight`. 
        # The `message ID` can be a random number.

        # TODO: Send a `hello` message to all known peers and put the messages into the outbox queue.

        while True:  # 添加循环使HELLO消息定期发送
            msg = {
                "type": "HELLO",
                "sender_id": self_id,
                "ip": self_info["ip"],
                "port": self_info["port"],
                "flags": {
                    "nat": self_info.get("nat", False),  # 使用False作为默认值而不是"unknown"
                    "light": self_info.get("light", False)
                },
                "message_id": f"hello_periodic_{time.time()}"
            }

            msg_str = json.dumps(msg) + "\n"
            logger.info(f"节点 {self_id} 定期发送HELLO消息，flags: nat={msg['flags']['nat']}, light={msg['flags']['light']}")

            # 获取当前的已知节点列表(可能已经更新)
            # Create a copy for safe iteration
            current_peers_copy = []
            with peer_data_lock:
                current_peers_copy = list(known_peers.keys())
            
            sent_count = 0
            
            for peer_id_str in current_peers_copy:
                if peer_id_str != str(self_id):
                    with peer_data_lock: # Lock before accessing known_peers[peer_id_str]
                        if peer_id_str in known_peers: # Re-check if peer still exists after acquiring lock
                            peer_ip, peer_port = known_peers[peer_id_str]
                        else:
                            continue # Peer was removed
                    enqueue_message(peer_id_str, peer_ip, peer_port, msg_str)
                    sent_count += 1
            
            logger.info(f"已向 {sent_count} 个节点发送定期HELLO消息")
                    
            # 每30秒重发一次HELLO消息
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()

def _parse_flag_value(flag_value):
    if flag_value is True:
        return True
    if flag_value is False:
        return False
    if isinstance(flag_value, str):
        if flag_value.lower() == 'true':
            return True
        if flag_value.lower() == 'false':
            return False
    return None # Default to None if unknown string, or not a boolean/recognized string

def handle_hello_message(msg, self_id):
    # new_peers = [] # This variable is not used in the current logic flow
    
    # TODO: Read information in the received `hello` message.
     
    # TODO: If the sender is unknown, add it to the list of known peers (`known_peer`) and record their flags (`peer_flags`).
     
    # TODO: Update the set of reachable peers (`reachable_by`).

    # new_peers = [] # This variable is not used

    sender_id_orig = msg.get("sender_id")
    sender_ip = msg.get("ip")
    sender_port = msg.get("port")
    sender_flags = msg.get("flags", {})

    # 使用字符串ID进行内部处理
    str_self_id = str(self_id)
    str_sender_id = str(sender_id_orig)

    # 不处理自己的HELLO
    if str_sender_id == str_self_id:
        return # Removed new_peers as it's unused

    newly_discovered = False
    with peer_data_lock:
        # 添加到已知节点表或更新已知节点的标志
        if str_sender_id not in known_peers:
            known_peers[str_sender_id] = (sender_ip, sender_port)
            newly_discovered = True  # 标记为新发现的节点
            logger.info(f"[{str_self_id}] handle_hello_message: 发现新节点: {str_sender_id} ({sender_ip}:{sender_port})")
        else:
            # 如果已知节点的IP或端口发生变化，更新它
            current_ip, current_port = known_peers[str_sender_id]
            if current_ip != sender_ip or current_port != sender_port:
                logger.info(f"[{str_self_id}] handle_hello_message: 更新节点 {str_sender_id} 的地址: 从 {current_ip}:{current_port} 到 {sender_ip}:{sender_port}")
                known_peers[str_sender_id] = (sender_ip, sender_port)
        
        raw_nat_flag = sender_flags.get("nat")
        raw_light_flag = sender_flags.get("light")

        parsed_nat_flag = _parse_flag_value(raw_nat_flag)
        parsed_light_flag = _parse_flag_value(raw_light_flag)
        
        current_peer_flag_entry = peer_flags.get(str_sender_id, {})
        updated_nat = parsed_nat_flag if parsed_nat_flag is not None else current_peer_flag_entry.get("nat")
        updated_light = parsed_light_flag if parsed_light_flag is not None else current_peer_flag_entry.get("light")

        peer_flags[str_sender_id] = {
            "nat": updated_nat,
            "light": updated_light
        }
        logger.info(f"[{str_self_id}] handle_hello_message: 更新节点 {str_sender_id} 的标志: nat={peer_flags[str_sender_id]['nat']}, light={peer_flags[str_sender_id]['light']} (来自原始值 nat:{raw_nat_flag}, light:{raw_light_flag})")

        self_node_flags_lock = peer_flags.get(str_self_id, {})
        if self_node_flags_lock.get("nat") is False:
            if str_sender_id not in reachable_by:
                reachable_by[str_sender_id] = set()
            reachable_by[str_sender_id].add(str_self_id)
            logger.info(f"[{str_self_id}] handle_hello_message: 本节点非NAT。更新可达性: 节点 {str_sender_id} 可通过本节点 ({str_self_id}) 被联系。reachable_by[{str_sender_id}] = {reachable_by[str_sender_id]}")
        else:
             logger.info(f"[{str_self_id}] handle_hello_message: 本节点是NAT或状态未知（nat: {self_node_flags_lock.get('nat')}），不作为 {str_sender_id} 的已知中继方更新 reachable_by。")

    self_node_config_info_global = peer_config.get(self_id, {})

    if not self_node_config_info_global:
         logger.error(f"[{str_self_id}] handle_hello_message: 无法在 peer_config 中找到自身配置 ({self_id}) 来发送回复HELLO。peer_config keys: {list(peer_config.keys())}")
    elif sender_ip and sender_port :
        from outbox import enqueue_message
        reply_msg_payload = {
            "type": "HELLO",
            "sender_id": self_id, 
            "ip": self_node_config_info_global.get("ip", ""),
            "port": self_node_config_info_global.get("port", 0),
            "flags": {
                "nat": self_node_config_info_global.get("nat", False),
                "light": self_node_config_info_global.get("light", False)
            },
            "message_id": f"hello_reply_{self_id}_{time.time()}"
        }
        logger.info(f"[{str_self_id}] handle_hello_message: 向节点 {str_sender_id} ({sender_ip}:{sender_port}) 发送回复HELLO消息，flags: nat={reply_msg_payload['flags']['nat']}, light={reply_msg_payload['flags']['light']}")
        enqueue_message(str_sender_id, sender_ip, sender_port, json.dumps(reply_msg_payload) + "\n")

    from peer_manager import update_peer_heartbeat, peer_status
    
    update_peer_heartbeat(str_sender_id) 
    
    with peer_data_lock:
        if newly_discovered or peer_status.get(str_sender_id) != 'ALIVE':
            peer_status[str_sender_id] = 'ALIVE'
            logger.info(f"[{str_self_id}] handle_hello_message: 节点 {str_sender_id} 状态设置为 ALIVE。")
    
    logger.info(f"[{str_self_id}] handle_hello_message: 已处理来自 {str_sender_id} 的HELLO消息。最终存储的Flags: nat={peer_flags.get(str_sender_id, {}).get('nat')}, light={peer_flags.get(str_sender_id, {}).get('light')}")


