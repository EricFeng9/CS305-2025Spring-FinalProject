import json
import time
import threading
import logging
import random
import hashlib
from outbox import enqueue_message, gossip_message
from transaction import get_recent_transactions, clear_pool
from utils import generate_message_id

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 全局变量
blockchain = []        # 本地区块链
block_headers = []     # 区块头(轻量级节点)
orphan_blocks = []     # 孤块列表
block_ids = set()      # 已知区块ID集合
is_malicious = False   # 恶意节点标志
is_lightweight = False # 轻量级节点标志

# 常量
BLOCK_GENERATION_INTERVAL = 30  # 区块生成间隔(秒)

def init_block_handler(peer_config):
    """初始化区块处理模块"""
    global is_malicious, is_lightweight
    
    is_malicious = peer_config.get("is_malicious", False)
    is_lightweight = peer_config.get("is_lightweight", False)
    
    # 创建创世区块
    if not blockchain:
        genesis_block = create_genesis_block()
        if is_lightweight:
            block_header = extract_block_header(genesis_block)
            block_headers.append(block_header)
        else:
            blockchain.append(genesis_block)
            block_ids.add(genesis_block["block_id"])

def create_genesis_block():
    """创建创世区块"""
    genesis_block = {
        "type": "BLOCK",
        "block_id": "0" * 64,
        "prev_block_id": "0" * 64,
        "timestamp": 0,
        "transactions": [],
        "height": 0
    }
    return genesis_block

def extract_block_header(block):
    """从区块中提取区块头"""
    return {
        "block_id": block["block_id"],
        "prev_block_id": block["prev_block_id"],
        "timestamp": block["timestamp"],
        "height": block["height"],
        "tx_count": len(block.get("transactions", []))
    }

def request_block_sync(peer_id):
    """请求区块头同步"""
    from peer_discovery import known_peers
    
    # 创建GET_BLOCK_HEADERS消息
    get_headers_msg = {
        "type": "GET_BLOCK_HEADERS",
        "sender_id": peer_id,
        "message_id": generate_message_id()
    }
    
    # 向已知节点发送请求
    for peer_port in known_peers:
        enqueue_message(get_headers_msg, peer_port, peer_id)
    
    logger.info(f"节点 {peer_id} 请求同步区块头")

def block_generation(peer_id, is_malicious_mode=False):
    """周期性生成新区块"""
    global is_malicious
    is_malicious = is_malicious_mode  # 使用传入的参数设置全局变量
    
    def generate_block():
        # 创建新区块
        new_block = create_dummy_block(peer_id)
        
        # 创建并广播INV消息
        from inv_message import create_inv
        inv_message = create_inv([new_block["block_id"]], peer_id)
        gossip_message(inv_message, peer_id)
        
        logger.info(f"节点 {peer_id} 生成了新区块: {new_block['block_id'][:8]}...")
        
        # 再次调度区块生成
        next_interval = BLOCK_GENERATION_INTERVAL * random.uniform(0.8, 1.2)
        threading.Timer(next_interval, generate_block).start()
    
    # 延迟启动区块生成(让节点有时间同步)
    if not is_lightweight:  # 轻量级节点不生成区块
        threading.Timer(BLOCK_GENERATION_INTERVAL, generate_block).start()

def create_dummy_block(peer_id):
    """创建新区块"""
    # 获取最新区块作为前一个区块
    prev_block = None
    if is_lightweight:
        if block_headers:
            prev_block = block_headers[-1]
    else:
        if blockchain:
            prev_block = blockchain[-1]
    
    # 如果没有前一个区块，使用创世区块
    if not prev_block:
        prev_block = create_genesis_block()
        if is_lightweight:
            block_headers.append(extract_block_header(prev_block))
        else:
            blockchain.append(prev_block)
            block_ids.add(prev_block["block_id"])
    
    # 从交易池获取交易
    transactions = get_recent_transactions()
    
    # 创建新区块
    new_block = {
        "type": "BLOCK",
        "sender_id": peer_id,
        "timestamp": time.time(),
        "prev_block_id": prev_block["block_id"],
        "transactions": transactions,
        "height": prev_block.get("height", 0) + 1
    }
    
    # 计算区块ID
    if is_malicious:
        new_block["block_id"] = "malicious_" + str(random.getrandbits(64))
        logger.warning(f"恶意节点 {peer_id} 生成了错误的区块ID")
    else:
        new_block["block_id"] = compute_block_hash(new_block)
    
    # 清空交易池并添加到区块链
    clear_pool()
    
    if is_lightweight:
        block_headers.append(extract_block_header(new_block))
    else:
        blockchain.append(new_block)
        block_ids.add(new_block["block_id"])
    
    return new_block

def compute_block_hash(block):
    """计算区块哈希"""
    block_copy = block.copy()
    if "block_id" in block_copy:
        del block_copy["block_id"]
    
    block_str = json.dumps(block_copy, sort_keys=True)
    return hashlib.sha256(block_str.encode()).hexdigest()

def handle_block(block, sender_id, peer_id=None):
    """处理接收到的区块"""
    if peer_id is None:
        peer_id = sender_id  # 如果未提供peer_id，使用sender_id作为默认值
        
    block_id = block.get("block_id")
    prev_block_id = block.get("prev_block_id")
    
    # 验证区块ID
    calculated_id = compute_block_hash(block)
    if calculated_id != block_id:
        from peer_manager import record_offense
        record_offense(sender_id)
        logger.warning(f"节点 {peer_id} 收到无效区块: {block_id[:8]}... 从 {sender_id}")
        return False
    
    # 检查区块是否已存在
    if block_id in block_ids:
        logger.debug(f"节点 {peer_id} 已经有区块: {block_id[:8]}...")
        return False
    
    # 检查前一个区块是否存在
    prev_block_exists = False
    
    if is_lightweight:
        for header in block_headers:
            if header["block_id"] == prev_block_id:
                prev_block_exists = True
                break
    else:
        for existing_block in blockchain:
            if existing_block["block_id"] == prev_block_id:
                prev_block_exists = True
                break
    
    if not prev_block_exists:
        # 将区块添加到孤块列表
        orphan_blocks.append(block)
        logger.info(f"节点 {peer_id} 将区块添加到孤块列表: {block_id[:8]}...")
        return False
    
    # 将区块添加到区块链
    if is_lightweight:
        block_headers.append(extract_block_header(block))
    else:
        blockchain.append(block)
    
    block_ids.add(block_id)
    logger.info(f"节点 {peer_id} 添加了新区块: {block_id[:8]}...")
    
    # 检查孤块是否可以添加到区块链
    process_orphan_blocks(peer_id)
    
    return True

def process_orphan_blocks(peer_id):
    """处理孤块列表，尝试将它们添加到区块链"""
    global orphan_blocks
    
    added = True
    while added:
        added = False
        remaining_orphans = []
        
        for orphan in orphan_blocks:
            if handle_block(orphan, orphan.get("sender_id"), peer_id):
                added = True
            else:
                remaining_orphans.append(orphan)
        
        orphan_blocks = remaining_orphans

def create_getblock(block_ids, peer_id):
    """创建GETBLOCK消息"""
    return {
        "type": "GETBLOCK",
        "sender_id": peer_id,
        "block_ids": block_ids,
        "message_id": generate_message_id()
    }

def create_inv(block_ids, inv_type, sender_id):
    """创建INV消息"""
    return {
        "type": "INV",
        "sender_id": sender_id,
        "inventory": block_ids,
        "inv_type": inv_type,
        "message_id": generate_message_id()
    }

def get_inventory():
    """获取本地区块链中的所有区块ID"""
    return block_ids

def get_block_by_id(block_id):
    """根据区块ID获取区块"""
    if is_lightweight:
        for header in block_headers:
            if header["block_id"] == block_id:
                return header
    else:
        for block in blockchain:
            if block["block_id"] == block_id:
                return block
    
    return None



