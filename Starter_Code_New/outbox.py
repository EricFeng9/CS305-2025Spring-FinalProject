import socket
import threading
import time
import json
import random
from collections import defaultdict, deque
from threading import Lock
import logging

# === Per-peer Rate Limiting ===
RATE_LIMIT = 10  # max messages
TIME_WINDOW = 10  # per seconds
peer_send_timestamps = defaultdict(list) # the timestamps of sending messages to each peer

MAX_RETRIES = 3
RETRY_INTERVAL = 5  # seconds
QUEUE_LIMIT = 50

# Priority levels
PRIORITY_HIGH = {"PING", "PONG", "BLOCK", "INV", "GETDATA"}
PRIORITY_MEDIUM = {"TX", "HELLO"}
PRIORITY_LOW = {"RELAY"}

DROP_PROB = 0.05
LATENCY_MS = (20, 100)
SEND_RATE_LIMIT = 5  # messages per second

drop_stats = {
    "BLOCK": 0,
    "TX": 0,
    "HELLO": 0,
    "PING": 0,
    "PONG": 0,
    "OTHER": 0
}

priority_order = {
    "BLOCK": 1,
    "TX": 2,
    "PING": 3,
    "PONG": 4,
    "HELLO": 5
}

# Queues per peer and priority
queues = defaultdict(lambda: defaultdict(deque))
retries = defaultdict(int)
lock = threading.Lock()

# 自定义JSON编码器，处理set类型
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)

# === Sending Rate Limiter ===
class RateLimiter:
    def __init__(self, rate=SEND_RATE_LIMIT):
        self.capacity = rate               # Max burst size
        self.tokens = rate                # Start full
        self.refill_rate = rate           # Tokens added per second
        self.last_check = time.time()
        self.lock = Lock()

    def allow(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_check
            self.tokens += elapsed * self.refill_rate
            self.tokens = min(self.tokens, self.capacity)
            self.last_check = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False

rate_limiter = RateLimiter()

def enqueue_message(message, target_peer, sender_id):
    """将消息放入发送队列"""
    from peer_manager import blacklist
    
    # 检查速率限制
    if is_rate_limited(sender_id, target_peer):
        logger.debug(f"节点 {sender_id} 发送到 {target_peer} 的消息被限制")
        return False
    
    # 检查黑名单
    if target_peer in blacklist:
        logger.debug(f"节点 {sender_id} 尝试发送消息到黑名单中的节点 {target_peer}")
        return False
    
    # 获取消息优先级
    priority = classify_priority(message)
    
    # 初始化目标节点的队列(如果不存在)
    if target_peer not in queues:
        queues[target_peer] = defaultdict(deque)
    
    # 检查队列长度限制
    if sum(len(q) for q in queues[target_peer].values()) >= QUEUE_LIMIT:
        logger.warning(f"发往节点 {target_peer} 的队列已满")
        return False
    
    # 将消息加入队列
    with lock:
        queues[target_peer][priority].append((message, time.time()))
    return True

def is_rate_limited(sender_id, target_peer):
    """检查消息发送频率是否超过限制"""
    key = (sender_id, target_peer)
    current_time = time.time()
    
    # 初始化时间戳列表(如果不存在)
    if key not in peer_send_timestamps:
        peer_send_timestamps[key] = []
    
    # 移除过期的时间戳
    timestamps = peer_send_timestamps[key]
    while timestamps and timestamps[0] < current_time - TIME_WINDOW:
        timestamps.pop(0)
    
    # 检查发送频率
    if len(timestamps) >= RATE_LIMIT:
        return True
    
    # 记录当前发送时间
    timestamps.append(current_time)
    return False

def classify_priority(message):
    """根据消息类型分类优先级"""
    msg_type = message.get("type", "")
    
    if msg_type in PRIORITY_HIGH:
        return 1  # 高优先级
    elif msg_type in PRIORITY_MEDIUM:
        return 2  # 中优先级
    return 3  # 低优先级

def send_from_queue():
    """从队列中发送消息"""
    def worker():
        from peer_discovery import known_peers
        
        # 记录上次处理的节点索引，确保公平处理
        last_peer_index = 0
        
        while True:
            try:
                # 获取当前已知节点列表
                peers = list(queues.keys())
                if not peers:
                    time.sleep(0.1)
                    continue
                
                # 轮询处理每个节点的消息
                if last_peer_index >= len(peers):
                    last_peer_index = 0
                
                current_peer = peers[last_peer_index]
                last_peer_index = (last_peer_index + 1) % len(peers)
                
                # 获取当前节点队列中优先级最高的消息
                message = None
                with lock:
                    for priority in sorted(queues[current_peer].keys()):
                        if queues[current_peer][priority]:
                            message, enqueue_time = queues[current_peer][priority].popleft()
                            break
                
                if not message:
                    continue
                
                # 获取消息目标和发送者
                target_peer = current_peer
                sender_id = message.get("sender_id")
                
                # 检查消息是否超时
                if time.time() - enqueue_time > 30:  # 30秒超时
                    logger.warning(f"消息发送超时，丢弃: {message.get('type')} 到 {target_peer}")
                    continue
                
                # 发送消息
                success = relay_or_direct_send(message, target_peer, sender_id)
                
                if not success:
                    # 记录重试次数
                    retries[target_peer] = retries.get(target_peer, 0) + 1
                    
                    if retries[target_peer] <= MAX_RETRIES:
                        # 重新入队，但降低优先级
                        priority = classify_priority(message) + 1
                        with lock:
                            queues[target_peer][priority].append((message, time.time()))
                        logger.debug(f"重试发送消息到 {target_peer}，尝试次数: {retries[target_peer]}")
                    else:
                        logger.warning(f"发送到 {target_peer} 的消息已达最大重试次数，放弃发送")
                        retries[target_peer] = 0
                else:
                    retries[target_peer] = 0
            
            except Exception as e:
                logger.error(f"发送消息时出错: {e}")
            
            finally:
                time.sleep(0.01)  # 避免CPU过载
    
    threading.Thread(target=worker, daemon=True).start()

def relay_or_direct_send(message, target_peer, sender_id):
    """决定是直接发送消息还是通过中继节点"""
    from peer_discovery import peer_flags, known_peers
    
    # 检查目标节点是否在NAT后面
    is_nated = False
    if target_peer in peer_flags and peer_flags[target_peer].get("is_nated"):
        is_nated = True
    
    if is_nated:
        # 找到最佳中继节点
        relay_peer = get_relay_peer(target_peer)
        
        if relay_peer:
            # 创建中继消息
            relay_message = {
                "type": "RELAY",
                "sender_id": sender_id,
                "target_id": target_peer,
                "payload": message
            }
            
            # 发送中继消息
            return send_message(relay_peer, relay_message)
        else:
            logger.warning(f"找不到节点 {target_peer} 的中继节点")
            return False
    else:
        # 直接发送消息
        return send_message(target_peer, message)

def get_relay_peer(target_peer):
    """为NAT后的节点找到最佳中继节点"""
    from peer_discovery import reachable_by
    from peer_manager import rtt_tracker
    
    if target_peer not in reachable_by or not reachable_by[target_peer]:
        return None
    
    relay_candidates = reachable_by[target_peer]
    best_relay = None
    best_rtt = float('inf')
    
    # 选择RTT最小的中继节点
    for relay in relay_candidates:
        if relay in rtt_tracker and rtt_tracker[relay]:
            avg_rtt = sum(rtt_tracker[relay]) / len(rtt_tracker[relay])
            if avg_rtt < best_rtt:
                best_rtt = avg_rtt
                best_relay = relay
    
    return best_relay

def send_message(target_peer, message):
    """发送消息到目标节点"""
    from peer_discovery import known_peers
    
    try:
        # 使用自定义编码器处理set类型
        message_json = json.dumps(message, cls=CustomJSONEncoder)
        message_data = (message_json + "\n").encode('utf-8')
        
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(5)
        
        # 连接目标节点 - 确保端口是整数
        host = f"peer{target_peer}"
        port = int(target_peer)
        
        client_socket.connect((host, port))
        client_socket.sendall(message_data)
        client_socket.close()
        
        logger.debug(f"消息已发送: {message.get('type')} 到节点 {target_peer}")
        return True
        
    except Exception as e:
        logger.error(f"发送消息到节点 {target_peer} 失败: {e}")
        return False

# 应用网络条件模拟
def apply_network_conditions(send_func):
    def wrapper(target_peer, message):
        # 检查发送容量限制
        if not rate_limiter.allow():
            msg_type = message.get("type", "OTHER")
            drop_stats[msg_type] = drop_stats.get(msg_type, 0) + 1
            logger.debug(f"消息因容量限制而丢弃: {msg_type}")
            return False
        
        # 模拟随机丢包
        if random.random() < DROP_PROB:
            msg_type = message.get("type", "OTHER")
            drop_stats[msg_type] = drop_stats.get(msg_type, 0) + 1
            logger.debug(f"消息因随机丢包而丢弃: {msg_type}")
            return False
        
        # 模拟网络延迟
        latency = random.uniform(LATENCY_MS[0], LATENCY_MS[1]) / 1000.0
        time.sleep(latency)
        
        # 执行实际发送
        return send_func(target_peer, message)
    
    return wrapper

# 应用网络条件模拟到send_message函数
send_message = apply_network_conditions(send_message)

def start_dynamic_capacity_adjustment():
    """动态调整节点的发送容量"""
    def adjust_loop():
        while True:
            try:
                # 随机调整容量(2-10)
                new_capacity = random.randint(2, 10)
                rate_limiter.capacity = new_capacity
                rate_limiter.refill_rate = new_capacity
                logger.info(f"节点发送容量已调整为: {new_capacity}")
                
                # 每30-60秒调整一次
                sleep_time = random.uniform(30, 60)
                time.sleep(sleep_time)
            
            except Exception as e:
                logger.error(f"调整容量时出错: {e}")
                time.sleep(30)
    
    threading.Thread(target=adjust_loop, daemon=True).start()

def gossip_message(message, sender_id, exclude_lightweight=False):
    """使用gossip协议广播消息到随机选择的节点"""
    from peer_discovery import known_peers, peer_flags, peer_config
    
    # 获取配置的fanout值
    fanout = peer_config.get("fanout", 3)
    
    # 过滤已知节点
    candidates = []
    for peer in known_peers:
        if peer != sender_id:  # 不向自己发送
            if exclude_lightweight:
                # 如果需要排除轻量级节点
                if peer in peer_flags and not peer_flags[peer].get("is_lightweight", False):
                    candidates.append(peer)
            else:
                candidates.append(peer)
    
    # 如果候选节点数量少于fanout，则全部发送
    if len(candidates) <= fanout:
        target_peers = candidates
    else:
        # 随机选择fanout个节点
        target_peers = random.sample(candidates, fanout)
    
    # 发送消息到选定的节点
    for target_peer in target_peers:
        enqueue_message(message, target_peer, sender_id)
    
    logger.debug(f"节点 {sender_id} 通过gossip发送了 {message.get('type')} 给 {len(target_peers)} 个节点")

def get_outbox_status():
    """获取outbox队列状态"""
    status = {}
    
    for peer, priority_queues in queues.items():
        peer_status = {
            "total_messages": sum(len(q) for q in priority_queues.values()),
            "priority_breakdown": {
                priority: len(queue) for priority, queue in priority_queues.items()
            }
        }
        status[peer] = peer_status
    
    return status

def get_drop_stats():
    """获取丢弃的消息统计"""
    return drop_stats

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

