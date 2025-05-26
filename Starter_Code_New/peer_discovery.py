import json, time, threading
import logging
import random
from utils import generate_message_id
from outbox import enqueue_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 全局变量
known_peers = set()  # 已知的节点集合
peer_flags = {}      # 节点标志(NATed/非NATed, 轻量级/全节点)
peer_config = {}     # 节点配置
reachable_by = {}    # 可达节点映射 (NATed节点 -> 可以访问它的节点集合)

def init_peer_discovery(config):
    """初始化节点发现模块"""
    global peer_config
    peer_config = config
    
    # 如果配置了初始节点，将它们添加到已知节点列表中
    if "initial_peers" in config:
        for peer in config["initial_peers"]:
            peer_port = str(peer["port"])
            if peer_port != str(config["port"]):  # 不将自己添加到已知节点列表
                known_peers.add(peer_port)

def start_peer_discovery(peer_id, ip, port, is_nated, is_lightweight):
    """向已知节点发送hello消息"""
    # 确保使用字符串格式
    peer_id = str(peer_id)
    port = str(port)
    
    # 创建hello消息
    hello_message = {
        "type": "HELLO",
        "sender_id": peer_id,
        "ip": ip,
        "port": port,
        "flags": {
            "is_nated": is_nated,
            "is_lightweight": is_lightweight
        },
        "message_id": generate_message_id()
    }
    
    logger.info(f"节点 {peer_id} 开始发现过程，向已知节点发送hello消息")
    
    # 向所有已知节点发送hello消息
    for peer_port in known_peers:
        enqueue_message(hello_message, peer_port, peer_id)
    
    # 周期性地重新触发节点发现过程
    threading.Timer(300, start_peer_discovery, 
                   args=[peer_id, ip, port, is_nated, is_lightweight]).start()

def handle_hello_message(message, sender_id, self_id):
    """处理收到的hello消息"""
    message_sender_id = message.get("sender_id")
    sender_ip = message.get("ip")
    sender_port = message.get("port")
    flags = message.get("flags", {})
    
    # 确保使用字符串格式
    if sender_port is not None:
        sender_port = str(sender_port)
    self_id = str(self_id)
    
    # 将发送方添加到已知节点列表(如果尚未存在)
    if sender_port not in known_peers and sender_port != self_id:
        known_peers.add(sender_port)
        peer_flags[sender_port] = flags
        logger.info(f"节点 {self_id} 添加了新的已知节点: {sender_port}")
        
    # 更新可达节点映射
    if flags.get("is_nated"):
        if sender_port not in reachable_by:
            reachable_by[sender_port] = set()
        reachable_by[sender_port].add(self_id)
        logger.info(f"节点 {self_id} 被记录为节点 {sender_port} 的中继")


