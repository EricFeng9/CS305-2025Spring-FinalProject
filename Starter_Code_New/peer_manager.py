import threading
import time
import json
from collections import defaultdict
import logging
from outbox import enqueue_message
from utils import generate_message_id

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

peer_status = {} # {peer_id: 'ALIVE', 'UNREACHABLE' or 'UNKNOWN'}
last_ping_time = {} # {peer_id: timestamp}
rtt_tracker = {} # {peer_id: transmission latency}
offense_counter = {}  # 记录节点的不良行为次数

# === Check if peers are alive ===

PING_INTERVAL = 30   # ping消息发送间隔(秒)
TIMEOUT = 60         # 节点超时时间(秒)
MAX_OFFENSES = 3     # 最大允许的不良行为次数

def start_ping_loop(peer_id):
    """
    启动周期性的ping循环以检查已知节点的状态
    """
    from peer_discovery import known_peers
    
    def ping_peers():
        current_time = time.time()
        for peer_port in known_peers:
            # 创建ping消息
            ping_message = {
                "type": "PING",
                "sender_id": peer_id,
                "timestamp": current_time,
                "message_id": generate_message_id()
            }
            
            # 发送ping消息到队列
            enqueue_message(ping_message, peer_port, peer_id)
            
        # 再次调度ping循环
        threading.Timer(PING_INTERVAL, ping_peers).start()
    
    # 启动ping循环
    ping_peers()

def create_pong(self_id, target_id):
    """
    创建pong响应消息
    
    参数:
    self_id -- 发送者节点ID
    target_id -- 接收者节点ID（之前发送ping的节点）
    """
    pong_message = {
        "type": "PONG",
        "sender_id": self_id,
        "timestamp": time.time(),
        "message_id": generate_message_id(),
        "target_id": target_id
    }
    
    return pong_message

def handle_pong(message, sender_id, self_id):
    """
    处理接收到的pong消息，计算RTT
    """
    ping_time = message.get("timestamp", time.time() - 1)  # 默认值，避免错误
    
    # 计算RTT
    current_time = time.time()
    rtt = current_time - ping_time
    
    # 更新RTT追踪器
    if sender_id not in rtt_tracker:
        rtt_tracker[sender_id] = []
    
    # 保留最近5个RTT值的平均值
    rtt_tracker[sender_id].append(rtt)
    if len(rtt_tracker[sender_id]) > 5:
        rtt_tracker[sender_id].pop(0)
    
    logger.debug(f"节点 {self_id} 从节点 {sender_id} 收到PONG，RTT: {rtt:.3f}秒")

def start_peer_monitor(peer_id):
    """
    监控节点状态，将长时间未响应的节点标记为不可达
    """
    from peer_discovery import known_peers
    
    def monitor_peers():
        current_time = time.time()
        for peer_port in known_peers:
            # 如果没有记录过ping时间，或者最后一次ping时间超过了超时时间
            if peer_port not in last_ping_time or current_time - last_ping_time[peer_port] > TIMEOUT:
                peer_status[peer_port] = "UNREACHABLE"
                logger.warning(f"节点 {peer_id} 将节点 {peer_port} 标记为不可达")
            else:
                peer_status[peer_port] = "ALIVE"
        
        # 再次调度监控
        threading.Timer(TIMEOUT/2, monitor_peers).start()
    
    # 启动监控
    monitor_peers()

def update_peer_heartbeat(peer_port):
    """
    当收到来自节点的ping或pong消息时更新最后ping时间
    """
    last_ping_time[peer_port] = time.time()
    peer_status[peer_port] = "ALIVE"

def record_offense(peer_port, reason="未指定原因"):
    """
    记录节点的不良行为，如果超过阈值则将其加入黑名单
    
    参数:
    peer_port -- 节点ID
    reason -- 记录原因
    """
    if peer_port not in offense_counter:
        offense_counter[peer_port] = 0
    
    offense_counter[peer_port] += 1
    logger.warning(f"节点 {peer_port} 行为不良({reason})，当前累计: {offense_counter[peer_port]}")
    
    if offense_counter[peer_port] >= MAX_OFFENSES:
        blacklist.add(peer_port)
        logger.warning(f"节点 {peer_port} 已被加入黑名单")

def get_peer_status():
    """获取所有节点的状态信息"""
    from peer_discovery import known_peers, peer_flags
    
    status_info = {}
    # 确保节点ID为字符串类型
    for peer_id in known_peers:
        str_peer_id = str(peer_id)
        status = peer_status.get(str_peer_id, "UNKNOWN")
        
        # 获取RTT数据
        rtt = None
        if str_peer_id in rtt_tracker and rtt_tracker[str_peer_id]:
            rtt = sum(rtt_tracker[str_peer_id]) / len(rtt_tracker[str_peer_id])
            
        # 获取节点标志
        flags = peer_flags.get(str_peer_id, {})
        
        # 获取违规记录
        offense_count = offense_counter.get(str_peer_id, 0)
        
        # 创建节点状态信息
        status_info[str_peer_id] = {
            "status": status,
            "rtt": rtt,
            "flags": flags,
            "offenses": offense_count,
            "blacklisted": str_peer_id in blacklist
        }
    
    return status_info

# === Blacklist Logic ===

blacklist = set() # The set of banned peers

peer_offense_counts = {} # The offence times of peers


