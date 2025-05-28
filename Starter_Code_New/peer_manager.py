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
    import logging
    logger = logging.getLogger(__name__)

    def loop():
        # TODO: Define the JSON format of a `ping` message, which should include `{message typy, sender's ID,
        #  timestamp}`.

        # TODO: Send a `ping` message to each known peer periodically.
        while True:
            now = time.time()
            str_self_id = str(self_id)  # 确保使用字符串ID
            
            # 创建peer_table的副本以避免在迭代过程中修改它
            peer_table_copy = dict(peer_table)
            
            for peer_id, (ip, port) in peer_table_copy.items():
                str_peer_id = str(peer_id)  # 确保使用字符串ID
                if str_peer_id != str_self_id:  # 不给自己发送PING消息
                    msg = {
                        "type": "PING",
                        "sender_id": self_id,
                        "timestamp": now,
                        "message_id": generate_message_id()
                    }
                    msg_str = json.dumps(msg) + "\n"
                    logger.debug(f"[{str_self_id}] 向节点 {str_peer_id} 发送PING消息")
                    enqueue_message(str_peer_id, ip, port, msg_str)
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
    import logging
    logger = logging.getLogger(__name__)
    
    sender_id = msg.get("sender_id")
    ping_ts = msg.get("timestamp")
    now = time.time()
    rtt = now - ping_ts

    # 统一使用字符串类型的键
    str_sender_id = str(sender_id)
    
    # 计算RTT并更新
    if ping_ts and now > ping_ts:
        rtt = (now - ping_ts) * 1000  # 转换为毫秒
        
        if str_sender_id not in rtt_tracker:
            rtt_tracker[str_sender_id] = []
        
        # 保留最近的10个RTT记录
        rtt_list = rtt_tracker[str_sender_id]
        rtt_list.append(rtt)
        if len(rtt_list) > 10:
            rtt_list.pop(0)
            
        avg_rtt = sum(rtt_list) / len(rtt_list)
        logger.info(f"收到来自节点 {str_sender_id} 的PONG，RTT: {rtt:.2f}ms，平均RTT: {avg_rtt:.2f}ms")
    else:
        logger.warning(f"收到来自节点 {str_sender_id} 的PONG，但时间戳无效: {ping_ts}")
    
    # 更新节点心跳时间
    update_peer_heartbeat(str_sender_id)


def start_peer_monitor():
    import threading
    import logging
    logger = logging.getLogger(__name__)

    def loop():
        # TODO: Check the latest time to receive `ping` or `pong` message from each peer in `last_ping_time`.

        # TODO: If the latest time is earlier than the limit, mark the peer's status in `peer_status` as
        #  `UNREACHABLE` or otherwise `ALIVE`.

        while True:
            now = time.time()
            for peer_id, last_time in list(last_ping_time.items()):  # 使用list()创建副本避免运行时修改字典
                # 确保键是字符串类型
                str_peer_id = str(peer_id)
                if now - last_time > PING_TIMEOUT:
                    old_status = peer_status.get(str_peer_id, "UNKNOWN")
                    peer_status[str_peer_id] = 'UNREACHABLE'
                    if old_status != 'UNREACHABLE':
                        logger.info(f"节点 {str_peer_id} 状态变更: {old_status} -> UNREACHABLE (超过 {PING_TIMEOUT}秒无响应)")
                else:
                    old_status = peer_status.get(str_peer_id, "UNKNOWN")
                    peer_status[str_peer_id] = 'ALIVE'
                    if old_status != 'ALIVE':
                        logger.info(f"节点 {str_peer_id} 状态变更: {old_status} -> ALIVE")
            time.sleep(PING_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


def update_peer_heartbeat(peer_id):
    # TODO: Update the `last_ping_time` of a peer when receiving its `ping` or `pong` message.
    # 确保键是字符串类型
    import logging
    logger = logging.getLogger(__name__)
    
    str_peer_id = str(peer_id)
    current_time = time.time()
    
    # 记录上次更新时间，用于计算更新频率
    last_time = last_ping_time.get(str_peer_id, 0)
    time_diff = current_time - last_time if last_time > 0 else 0
    
    last_ping_time[str_peer_id] = current_time
    
    # 同时更新状态为ALIVE
    old_status = peer_status.get(str_peer_id, "UNKNOWN")
    peer_status[str_peer_id] = 'ALIVE'
    
    if old_status != 'ALIVE':
        logger.info(f"节点 {str_peer_id} 心跳更新: 状态从 {old_status} 变为 ALIVE")
    elif time_diff > 0:
        logger.debug(f"节点 {str_peer_id} 心跳更新: 距上次更新间隔 {time_diff:.2f}秒")


# === Blacklist Logic ===

blacklist = set()  # The set of banned peers

peer_offense_counts = defaultdict(int)  # The offence times of peers


def record_offense(peer_id):
    # TODO: Record the offence times of a peer when malicious behaviors are detected.

    # TODO: Add a peer to `blacklist` if its offence times exceed 3. 

    # 确保键是字符串类型
    str_peer_id = str(peer_id)
    peer_offense_counts[str_peer_id] += 1
    
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"记录节点 {peer_id} 的违规行为，当前违规次数: {peer_offense_counts[str_peer_id]}")
    
    if peer_offense_counts[str_peer_id] > 3:
        blacklist.add(str_peer_id)
        logger.warning(f"节点 {peer_id} 已被加入黑名单，违规次数超过阈值")

#--------------------------------
def get_peer_status():
    """获取所有节点的状态信息"""
    from peer_discovery import known_peers, peer_flags
    import logging
    logger = logging.getLogger(__name__)
    
    status_info = {}
    # 确保节点ID为字符串类型
    for peer_id in known_peers:
        str_peer_id = str(peer_id)
        status = peer_status.get(str_peer_id, "unknown")
        
        # 获取RTT数据 - 修复类型不匹配问题
        rtt = None
        if str_peer_id in rtt_tracker:
            # 使用字符串键访问rtt_tracker
            rtt = rtt_tracker[str_peer_id]
            
        # 获取节点标志
        flags = peer_flags.get(str_peer_id, {})
        nat_status = flags.get("nat")
        light_status = flags.get("light")
        


            
        # 获取违规记录
        offense_count = peer_offense_counts.get(str_peer_id, 0)
        
        # 创建节点状态信息
        status_info[str_peer_id] = {
            "status": status,
            "rtt": rtt,
            "flags": flags,
            "offenses": offense_count,
            "blacklisted": str_peer_id in blacklist
        }
    
    logger.debug(f"当前所有节点状态信息: {status_info}")
    return status_info

