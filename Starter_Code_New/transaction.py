import time
import json
import hashlib
import random
import threading
from peer_discovery import known_peers
from outbox import gossip_message
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TransactionMessage:
    def __init__(self, sender, receiver, amount, timestamp=None):
        self.type = "TX"
        self.from_peer = sender
        self.to_peer = receiver
        self.amount = amount
        self.timestamp = timestamp if timestamp else time.time()
        self.id = self.compute_hash()

    def compute_hash(self):
        tx_data = {
            "type": self.type,
            "from": self.from_peer,
            "to": self.to_peer,
            "amount": self.amount,
            "timestamp": self.timestamp
        }
        return hashlib.sha256(json.dumps(tx_data, sort_keys=True).encode()).hexdigest()

    def to_dict(self):
        return {
            "type": self.type,
            "id": self.id,
            "from": self.from_peer,
            "to": self.to_peer,
            "amount": self.amount,
            "timestamp": self.timestamp
        }

    @staticmethod
    def from_dict(data):
        return TransactionMessage(
            sender=data["from"],
            receiver=data["to"],
            amount=data["amount"],
            timestamp=data["timestamp"]
        )
    
# 全局变量
tx_pool = []      # 交易池
tx_ids = set()    # 已处理交易ID集合
is_malicious = False  # 恶意节点标志

def init_transaction_module(malicious_flag):
    """初始化交易模块"""
    global is_malicious
    is_malicious = malicious_flag

def compute_tx_id(tx):
    """计算交易ID"""
    # 复制交易并删除ID字段以计算哈希
    tx_copy = tx.copy()
    if "tx_id" in tx_copy:
        del tx_copy["tx_id"]
    
    tx_str = json.dumps(tx_copy, sort_keys=True)
    return hashlib.sha256(tx_str.encode()).hexdigest()[:16]

def transaction_generation(peer_id):
    """
    生成新交易并广播给其他节点
    """
    from peer_discovery import known_peers
    
    def generate_tx():
        # 如果没有已知节点，则等待并重试
        if not known_peers:
            threading.Timer(5, generate_tx).start()
            return
        
        # 随机选择一个接收者
        recipients = list(known_peers)
        if peer_id in recipients:
            recipients.remove(peer_id)
        
        if recipients:
            recipient = random.choice(recipients)
            amount = random.uniform(0.1, 10.0)
            
            # 创建新交易
            tx = {
                "type": "TX",
                "sender_id": peer_id,
                "recipient_id": recipient,
                "amount": round(amount, 2),
                "timestamp": time.time()
            }
            
            # 计算交易ID
            if is_malicious:
                tx["tx_id"] = "malicious_" + str(random.getrandbits(64))
                logger.warning(f"恶意节点 {peer_id} 生成了错误的交易ID")
            else:
                tx["tx_id"] = compute_tx_id(tx)
            
            # 添加到本地交易池
            add_transaction(tx)
            
            # 广播交易
            gossip_message(tx, peer_id, exclude_lightweight=True)
            logger.info(f"节点 {peer_id} 生成了新交易: {tx['tx_id'][:8]}...")
        
        # 每5-15秒生成一次新交易
        next_interval = random.uniform(5, 15)
        threading.Timer(next_interval, generate_tx).start()
    
    # 启动交易生成循环
    threading.Timer(random.uniform(1, 5), generate_tx).start()

def add_transaction(tx):
    """
    将交易添加到本地交易池
    """
    tx_id = tx.get("tx_id")
    
    if tx_id not in tx_ids:
        tx_pool.append(tx)
        tx_ids.add(tx_id)
        return True
    return False

def get_recent_transactions(limit=None):
    """
    获取本地交易池中的最新交易
    """
    if limit:
        return tx_pool[-limit:]
    return tx_pool

def clear_pool():
    """
    清空交易池
    """
    global tx_pool
    tx_pool = []