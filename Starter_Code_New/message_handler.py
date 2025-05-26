import json
import threading
import time
import hashlib
import random
from collections import defaultdict
from peer_discovery import handle_hello_message, known_peers, peer_config
from block_handler import handle_block, get_block_by_id, create_getblock
from inv_message import  create_inv, get_inventory
from block_handler import create_getblock
from peer_manager import  update_peer_heartbeat, record_offense, create_pong, handle_pong
from transaction import add_transaction
from outbox import enqueue_message, gossip_message
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Global State ===
SEEN_EXPIRY_SECONDS = 600  # 10 minutes
seen_message_ids = {}
seen_txs = set()
redundant_blocks = 0
redundant_txs = 0
message_redundancy = defaultdict(int)
peer_inbound_timestamps = defaultdict(list)


# === Inbound Rate Limiting ===
INBOUND_RATE_LIMIT = 20       # 入站速率限制
INBOUND_TIME_WINDOW = 10      # 入站速率时间窗口(秒)

def is_inbound_limited(peer_id):
    """检查发送者是否超过入站速率限制"""
    current_time = time.time()
    
    # 记录当前时间戳
    peer_inbound_timestamps[peer_id].append(current_time)
    
    # 删除过期的时间戳
    peer_inbound_timestamps[peer_id] = [ts for ts in peer_inbound_timestamps[peer_id] 
                                      if current_time - ts <= INBOUND_TIME_WINDOW]
    
    # 检查是否超过入站速率限制
    return len(peer_inbound_timestamps[peer_id]) > INBOUND_RATE_LIMIT

# ===  Redundancy Tracking ===

def get_redundancy_stats():
    """返回重复消息的统计信息"""
    return dict(message_redundancy)

# === Main Message Dispatcher ===
def dispatch_message(msg, self_id, self_ip):
    """处理接收到的消息"""
    try:
        msg_type = msg.get("type")  # 修复：使用get方法而不是下标访问
        
        # 消息合法性检查
        if not msg_type:
            logger.warning(f"收到无类型消息: {msg}")
            return
            
        # 检查消息ID，防止重放攻击
        msg_id = msg.get("id", str(hash(str(msg))))
        current_time = time.time()
        
        if msg_id in seen_message_ids:
            if current_time - seen_message_ids[msg_id] < SEEN_EXPIRY_SECONDS:
                message_redundancy[msg_id] += 1
                return
        
        # 记录消息ID和时间戳
        seen_message_ids[msg_id] = current_time
        
        # 获取消息发送者
        sender_id = msg.get("sender_id")
        if not sender_id:
            logger.warning(f"收到无发送者ID的消息: {msg}")
            return
            
        # 检查入站速率限制
        if is_inbound_limited(sender_id):
            logger.warning(f"节点 {sender_id} 超过入站速率限制")
            return
            
        # 检查节点是否在黑名单中
        from peer_manager import blacklist
        if sender_id in blacklist:
            logger.warning(f"丢弃来自黑名单节点 {sender_id} 的消息")
            return

        # 处理不同类型的消息
        if msg_type == "RELAY":
            target_id = msg.get("target_id")
            if target_id == self_id:
                payload = msg.get("payload", {})
                dispatch_message(payload, self_id, self_ip)
            else:
                from outbox import enqueue_message
                enqueue_message(msg, target_id, self_id)
                
        elif msg_type == "HELLO":
            from peer_discovery import handle_hello_message
            handle_hello_message(msg, sender_id, self_id)
            
        elif msg_type == "BLOCK":
            block_id = msg.get("block_id")
            block_data = msg.get("data", {})
            
            # 验证区块ID正确性
            if block_id and block_data:
                calculated_id = hashlib.sha256(json.dumps(block_data, sort_keys=True).encode()).hexdigest()[:16]
                if calculated_id != block_id:
                    from peer_manager import record_offense
                    record_offense(sender_id, "区块ID不匹配")
                    return
                    
                # 处理区块
                from block_handler import handle_block
                handle_block(block_data, sender_id, self_id)
                
                # 创建并广播INV消息
                from block_handler import create_inv
                inv_msg = create_inv([block_id], "block", self_id)
                from outbox import gossip_message
                gossip_message(inv_msg, self_id)
                
        elif msg_type == "TX":
            tx_id = msg.get("tx_id")
            tx_data = msg.get("data", {})
            
            # 验证交易ID正确性
            if tx_id and tx_data:
                calculated_id = hashlib.sha256(json.dumps(tx_data, sort_keys=True).encode()).hexdigest()[:16]
                if calculated_id != tx_id:
                    from peer_manager import record_offense
                    record_offense(sender_id, "交易ID不匹配")
                    return
                
                # 添加交易到交易池
                if tx_id not in seen_txs:
                    seen_txs.add(tx_id)
                    from transaction import add_transaction
                    add_transaction(tx_data)
                    
                    # 广播交易
                    from outbox import gossip_message
                    gossip_message(msg, self_id)
                    
        elif msg_type == "PING":
            # 更新节点心跳
            from peer_manager import update_peer_heartbeat
            update_peer_heartbeat(sender_id)
            
            # 创建并发送PONG消息
            from peer_manager import create_pong
            pong_msg = create_pong(self_id, sender_id)
            from outbox import enqueue_message
            enqueue_message(pong_msg, sender_id, self_id)
            
        elif msg_type == "PONG":
            # 更新节点心跳
            from peer_manager import update_peer_heartbeat, handle_pong
            update_peer_heartbeat(sender_id)
            
            # 处理PONG消息
            handle_pong(msg, sender_id, self_id)
            
        elif msg_type == "INV":
            inventory = msg.get("inventory", [])
            inv_type = msg.get("inv_type", "")
            
            # 获取本地区块链中的所有区块ID
            if inv_type == "block":
                from block_handler import get_inventory
                local_blocks = get_inventory()
                
                # 比较并找出缺失的区块
                missing_blocks = [block_id for block_id in inventory if block_id not in local_blocks]
                
                if missing_blocks:
                    # 创建GETBLOCK消息
                    from block_handler import create_getblock
                    getblock_msg = create_getblock(missing_blocks, self_id)
                    from outbox import enqueue_message
                    enqueue_message(getblock_msg, sender_id, self_id)
            
        elif msg_type == "GETBLOCK":
            requested_blocks = msg.get("blocks", [])
            
            # 发送请求的区块
            for block_id in requested_blocks:
                from block_handler import get_block_by_id
                block = get_block_by_id(block_id)
                if block:
                    block_msg = {
                        "type": "BLOCK",
                        "sender_id": self_id,
                        "block_id": block_id,
                        "data": block
                    }
                    from outbox import enqueue_message
                    enqueue_message(block_msg, sender_id, self_id)
            
        elif msg_type == "GET_BLOCK_HEADERS":
            # 获取本地区块链中的所有区块头
            from block_handler import blockchain
            headers = []
            
            for block in blockchain:
                headers.append({
                    "block_id": block["block_id"],
                    "prev_block_id": block.get("prev_block_id", ""),
                    "height": block.get("height", 0),
                    "timestamp": block.get("timestamp", 0)
                })
                
            # 创建并发送BLOCK_HEADERS消息
            headers_msg = {
                "type": "BLOCK_HEADERS",
                "sender_id": self_id,
                "headers": headers
            }
            
            from outbox import enqueue_message
            enqueue_message(headers_msg, sender_id, self_id)
            
        elif msg_type == "BLOCK_HEADERS":
            pass  # 由于需要更复杂的处理，这部分暂时保留为pass
            
        else:
            logger.warning(f"[{self_id}] 未知消息类型: {msg_type}")
            
    except Exception as e:
        logger.error(f"处理消息时出错: {e}")