import time
import logging
from utils import generate_message_id
from outbox import gossip_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_inv(block_ids, peer_id):
    """创建INV消息"""
    return {
        "type": "INV",
        "sender_id": peer_id,
        "block_ids": block_ids,
        "message_id": generate_message_id(),
        "timestamp": time.time()
    }

def get_inventory():
    """获取本地区块链中的所有区块ID"""
    from block_handler import blockchain, block_headers, is_lightweight
    
    if is_lightweight:
        return [header["block_id"] for header in block_headers]
    else:
        return [block["block_id"] for block in blockchain]

def broadcast_inventory(peer_id):
    """广播本地区块链的库存"""
    # 获取所有区块ID
    block_ids = get_inventory()
    
    if block_ids:
        # 创建INV消息
        inv_message = create_inv(block_ids, peer_id)
        
        # 广播INV消息
        gossip_message(inv_message, peer_id)
        
        logger.info(f"节点 {peer_id} 广播了 {len(block_ids)} 个区块的库存")


