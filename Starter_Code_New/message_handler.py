import json
import threading
import time
import hashlib
import random
from collections import defaultdict
from peer_discovery import handle_hello_message, known_peers, peer_config
from block_handler import handle_block, get_block_by_id, create_getblock, received_blocks, header_store
from inv_message import  create_inv, get_inventory
from block_handler import create_getblock
from peer_manager import  update_peer_heartbeat, record_offense, create_pong, handle_pong
from transaction import add_transaction
from outbox import enqueue_message, gossip_message
from utils import generate_message_id
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# === Global State ===
SEEN_EXPIRY_SECONDS = 600  # 10 minutes
seen_message_ids = {}
seen_txs = set()
redundant_blocks = 0
redundant_txs = 0
message_redundancy = {}
peer_inbound_timestamps = defaultdict(list)


# === Inbound Rate Limiting ===
INBOUND_RATE_LIMIT = 10
INBOUND_TIME_WINDOW = 10  # seconds

def is_inbound_limited(peer_id):
    # Record the timestamp when receiving message from a sender.
    """检查发送者是否超过入站速率限制"""
    current_time = time.time()
    
    # 确保键是字符串类型
    str_peer_id = str(peer_id)
    
    # 记录当前时间戳
    peer_inbound_timestamps[str_peer_id].append(current_time)
    
    # 删除过期的时间戳
    peer_inbound_timestamps[str_peer_id] = [ts for ts in peer_inbound_timestamps[str_peer_id] 
                                      if current_time - ts <= INBOUND_TIME_WINDOW]
    # Check if the number of messages sent by the sender exceeds `INBOUND_RATE_LIMIT` 
    # during the `INBOUND_TIME_WINDOW`. If yes, return `TRUE`. If not, return `FALSE`.
     # 检查剩余的时间戳数量是否超过入站速率限制
    return len(peer_inbound_timestamps[str_peer_id]) > INBOUND_RATE_LIMIT

# ===  Redundancy Tracking ===

def get_redundancy_stats():
    # Return the times of receiving duplicated messages (`message_redundancy`).
    """返回重复消息次数的统计信息"""
    return message_redundancy

# === Main Message Dispatcher ===
def dispatch_message(msg, self_id, self_ip):
    """处理接收到的消息"""
    try:
        msg_type = msg.get("type")
        
        # 消息合法性检查
        if not msg_type:
            logger.warning(f"收到无类型消息: {msg}")
            return
        
        #  Check if the message has been seen in `seen_message_ids` to prevent replay attacks. 
        # If yes, drop the message and add one to `message_redundancy`. 
        # If not, add the message ID to `seen_message_ids`.
        # 检查消息ID，防止重放攻击
        msg_id = msg.get("message_id", str(hash(str(msg)))) #为消息生成一个唯一标识符（ID）
        current_time = time.time()
        if msg_id in seen_message_ids:
                if current_time - seen_message_ids[msg_id] < SEEN_EXPIRY_SECONDS:
                    message_redundancy[msg_id] = message_redundancy.get(msg_id, 0) + 1
                    return
        # 记录消息ID和时间戳
        seen_message_ids[msg_id] = current_time
        
        # Check if the sender sends message too frequently using the function `in_bound_limited`. 
        # If yes, drop the message.
        # 获取消息发送者
        sender_id = msg.get("sender_id")
        if not sender_id:
            logger.warning(f"收到无发送者ID的消息: {msg}")
            return
                
        # 检查入站速率限制
        if is_inbound_limited(sender_id):
            logger.warning(f"节点 {sender_id} 超过入站速率限制")
            return
        
        # Check if the sender exists in the `blacklist` of `peer_manager.py`. If yes, drop the message.
        # 检查节点是否在黑名单中
        from peer_manager import blacklist
        if str(sender_id) in blacklist:
            logger.warning(f"丢弃来自黑名单节点 {sender_id} 的消息")
            return
        

        if msg_type == "RELAY":

            # Check if the peer is the target peer.
            # If yes, extract the payload and recall the function `dispatch_message` to process the payload.
            # If not, forward the message to target peer using the function `enqueue_message` in `outbox.py`.
            target_id = msg.get("target_id")
            str_target_id = str(target_id)
            payload = msg.get("payload", {})
            
            logger.info(f"收到RELAY消息，目标节点: {target_id}, 发送者: {sender_id}")
            
            if str_target_id == str(self_id):
                logger.info(f"本节点是RELAY消息的目标节点，处理payload")
                if payload:
                    dispatch_message(payload, self_id, self_ip)
                else:
                    logger.warning(f"RELAY消息中没有payload")
            else:
                from outbox import enqueue_message
                # 检查目标是否在已知节点列表中
                if target_id in known_peers:
                    target_ip, target_port = known_peers[target_id]
                    logger.info(f"转发RELAY消息到目标节点 {target_id} ({target_ip}:{target_port})")
                    enqueue_message(target_id, target_ip, target_port, msg)
                else:
                    logger.warning(f"无法转发RELAY消息，目标节点 {target_id} 不在已知节点列表中")

        elif msg_type == "HELLO":
            #  Call the function `handle_hello_message` in `peer_discovery.py` to process the message.
            from peer_discovery import handle_hello_message
            logger.info(f"收到HELLO消息：发送者={msg.get('sender_id')}, IP={msg.get('ip')}, 端口={msg.get('port')}")
            new_peers = handle_hello_message(msg, self_id)
            if new_peers:
                logger.info(f"通过HELLO消息发现新节点: {new_peers}")
            else:
                logger.info("没有发现新节点")

        elif msg_type == "BLOCK":
            block_id = msg.get("block_id")
            block_data = msg.get("data", {})
            # Check the correctness of block ID. 
            # If incorrect, record the sender's offence using the function `record_offence` in `peer_manager.py`.
            # 验证区块ID正确性
            if block_id and block_data:
                calculated_id = hashlib.sha256(json.dumps(block_data, sort_keys=True).encode()).hexdigest()[:16]
                if calculated_id != block_id:
                    from peer_manager import record_offense
                    record_offense(sender_id, "区块ID不匹配")
                    return
            # TODO: Call the function `handle_block` in `block_handler.py` to process the block.
            # 处理区块
                from block_handler import handle_block
                handle_block(block_data, self_id)
                     
            # Call the function `create_inv` to create an `INV` message for the block.
            # Broadcast the `INV` message to known peers using the function `gossip_message` in `outbox.py`.
                # 创建并广播INV消息
                from inv_message import create_inv
                inv_msg = create_inv(self_id, [block_id])
                from outbox import gossip_message
                gossip_message(self_id, inv_msg)  
                
            #INV消息的工作流程
            #触发条件：当节点验证并接受一个新区块后
            #消息创建：通过 create_inv 函数创建INV消息
            #消息传播：通过 gossip_message 将INV消息传播给网络中的其他节点
            #接收处理：其他节点收到INV消息后，会检查自己是否已有这些数据
            #数据请求：如果没有，会发送GETDATA消息请求完整数据
            


        elif msg_type == "TX":
            tx_id = msg.get("tx_id")
            tx_data = msg.get("data", {})
            # Check the correctness of transaction ID. 
            # If incorrect, record the sender's offence using the function `record_offence` in `peer_manager.py`.
            # 验证交易ID正确性
            if tx_id and tx_data:
                calculated_id = hashlib.sha256(json.dumps(tx_data, sort_keys=True).encode()).hexdigest()[:16]
                if calculated_id != tx_id:
                    from peer_manager import record_offense
                    record_offense(sender_id, "交易ID不匹配")
                    return
            
            # Add the transaction to `tx_pool` using the function `add_transaction` in `transaction.py`.
            # 添加交易到交易池
                if tx_id not in seen_txs:
                    seen_txs.add(tx_id)
                    from transaction import add_transaction
                    add_transaction(tx_data)                
            # Broadcast the transaction to known peers using the function `gossip_message` in `outbox.py`.
                    # 广播交易
                    from outbox import gossip_message
                    gossip_message(self_id, msg)

        elif msg_type == "PING":
            
            # Update the last ping time using the function `update_peer_heartbeat` in `peer_manager.py`.
            # 更新the last ping time
            from peer_manager import update_peer_heartbeat
            update_peer_heartbeat(sender_id)
            
            # Create a `pong` message using the function `create_pong` in `peer_manager.py`.
            from peer_manager import create_pong
            pong_msg = create_pong(self_id, msg.get("timestamp"))
            
            # Send the `pong` message to the sender using the function `enqueue_message` in `outbox.py`.
            #发送PONG消息
            from outbox import enqueue_message
            # 检查发送者是否在已知节点列表中
            if sender_id in known_peers:
                enqueue_message(sender_id, known_peers[sender_id][0], known_peers[sender_id][1], pong_msg)
            else:
                logger.warning(f"无法回复PING消息，发送者 {sender_id} 不在已知节点列表中")
            

        elif msg_type == "PONG":
            
            # Update the last ping time using the function `update_peer_heartbeat` in `peer_manager.py`.
            from peer_manager import update_peer_heartbeat, handle_pong
            update_peer_heartbeat(sender_id)
            #  Call the function `handle_pong` in `peer_manager.py` to handle the message.
            handle_pong(msg)
            

        elif msg_type == "INV":
            inventory = msg.get("inventory", [])
            inv_type = msg.get("inv_type", "")
            # Read all blocks IDs in the local blockchain 
            # using the function `get_inventory` in `block_handler.py`.
            # 获取本地区块链中的所有区块ID
            if inv_type == "block":
                from block_handler import get_inventory
                local_blocks = get_inventory()
                # Compare the local block IDs with those in the message.
                # 比较并找出缺失的区块
                missing_blocks = [block_id for block_id in inventory if block_id not in local_blocks]
                    
                # If there are missing blocks, create a `GETBLOCK` message to request the missing blocks from the sender.
                # Send the `GETBLOCK` message to the sender using the function `enqueue_message` in `outbox.py`.
                if missing_blocks and sender_id in known_peers:
                    # 创建GETBLOCK消息
                    from block_handler import create_getblock
                    getblock_msg = create_getblock(self_id, missing_blocks)
                    # 获取发送者的IP和端口
                    sender_ip, sender_port = known_peers[sender_id]
                    # 发送GETBLOCK消息
                    enqueue_message(sender_id, sender_ip, sender_port, getblock_msg)
                    logger.info(f"向节点 {sender_id} 请求缺失的区块: {missing_blocks}")

        elif msg_type == "GETBLOCK":
            
            # Extract the block IDs from the message.
            requested_blocks = msg.get("blocks", [])
            # 获取当前重试次数
            retry_count = msg.get("retry_count", 0)
            # Retry getting the blocks from the local blockchain. 
            # If the retry times exceed 3, drop the message.
            # 检查重试次数是否超过上限
            if retry_count >= 3:
                logger.warning(f"区块请求 {msg.get('message_id', '未知ID')} 重试次数已达上限 ({retry_count}/3)，放弃处理")
                return
                
            # Get the blocks from the local blockchain according to the block IDs 
            # using the function `get_block_by_id` in `block_handler.py`.
            # 发送请求的区块
            missing_blocks = []
            
            # If the blocks exist in the local blockchain, 
            # send the blocks one by one to the requester using the function `enqueue_message` in `outbox.py`.
            for block_id in requested_blocks:
                from block_handler import get_block_by_id
                block = get_block_by_id(block_id)
                if block:
                    # 如果区块存在，发送给请求者
                    block_msg = {
                        "type": "BLOCK",
                        "sender_id": self_id,
                        "block_id": block_id,
                        "data": block,
                        "message_id": generate_message_id()
                    }
                    if sender_id in known_peers:
                        sender_ip, sender_port = known_peers[sender_id]
                        from outbox import enqueue_message
                        # Send the `GETBLOCK` message to known peers 
                        # using the function `enqueue_message` in `outbox.py`.
                        enqueue_message(sender_id, sender_ip, sender_port, json.dumps(block_msg) + "\n")
                        logger.info(f"发送区块 {block_id} 到节点 {sender_id}")
                    else:
                        logger.warning(f"无法发送区块 {block_id}，节点 {sender_id} 不在已知节点列表中")
                else:
                    # 如果本地没有该区块，记录为缺失的区块
                    missing_blocks.append(block_id)
                    
            # If the blocks are not in the local blockchain, 
            # create a `GETBLOCK` message to request the missing blocks from known peers.        
            # 如果有缺失的区块，尝试从其他已知节点获取
            if missing_blocks:
                # 递增重试计数
                retry_count += 1
                
                # 创建GETBLOCK消息并包含重试计数
                from block_handler import create_getblock
                getblock_msg_data = {
                    "type": "GETBLOCK",
                    "sender_id": self_id,
                    "blocks": missing_blocks,
                    "retry_count": retry_count,
                    "message_id": generate_message_id()
                }
                getblock_msg = json.dumps(getblock_msg_data) + "\n"
                
                # 向其他节点发送请求（排除自己和原请求者）
                request_sent = False
                for peer_id, (peer_ip, peer_port) in known_peers.items():
                    if peer_id != self_id and peer_id != sender_id:
                        # 不向自己或原请求者发送
                        enqueue_message(peer_id, peer_ip, peer_port, getblock_msg)
                        request_sent = True                    
                if request_sent:
                    logger.info(f"向其他节点请求缺失的区块: {missing_blocks}，重试次数: {retry_count}/3")
                else:
                    logger.warning(f"无法向其他节点请求缺失的区块，没有其他已知节点，重试次数: {retry_count}/3")

        elif msg_type == "GET_BLOCK_HEADERS":
            
            # Read all block header in the local blockchain and store them in `headers`.
            # Create a `BLOCK_HEADERS` message, which should include `{message type, sender's ID, headers}`.
            from block_handler import header_store
            
            # 创建BLOCK_HEADERS消息
            headers_msg = {
                "type": "BLOCK_HEADERS",
                "sender_id": self_id,
                "headers": header_store,
                "message_id": generate_message_id()
            }
            
            # Send the `BLOCK_HEADERS` message to the requester using the function `enqueue_message` in `outbox.py`.
            from outbox import enqueue_message
            if sender_id in known_peers:
                sender_ip, sender_port = known_peers[sender_id]
                enqueue_message(sender_id, sender_ip, sender_port, json.dumps(headers_msg) + "\n")
            else:
                logger.warning(f"无法发送区块头信息，节点 {sender_id} 不在已知节点列表中")

        elif msg_type == "BLOCK_HEADERS":
            
            # Check if the previous block of each block exists in the local blockchain or the received block headers.
            received_headers = msg.get("headers", [])
            from peer_discovery import peer_flags
            from block_handler import header_store, received_blocks
            
            # 检查接收到的区块头是否为空
            if not received_headers:
                logger.warning(f"从节点 {sender_id} 接收到空的区块头列表")
                return
                
            # 构建本地区块链和收到的区块头的ID集合，用于快速查找
            local_block_ids = {block.get("block_id", "") for block in received_blocks}
            local_header_ids = {header.get("block_id", "") for header in header_store}
            received_header_ids = {header.get("block_id", "") for header in received_headers}
            
            # 检查区块头链的连续性
            is_valid = True
            missing_blocks = []
            
            for header in received_headers:
                block_id = header.get("block_id", "")
                prev_id = header.get("prev_block_id", "")
                
                # 检查前一个区块是否存在于本地区块链或收到的区块头列表中
                if prev_id and (prev_id not in local_block_ids) and (prev_id not in local_header_ids) and (prev_id not in received_header_ids):
                    is_valid = False
                    logger.warning(f"区块头链不连续: 区块 {block_id} 的前置区块 {prev_id} 不存在")
                    break
                    
                # 记录本地不存在的区块
                if (block_id not in local_block_ids) and (block_id not in local_header_ids):
                    missing_blocks.append(block_id)
                    
            # If not, drop the message since there are orphaned blocks in the received message and, thus, the message is invalid.
            if not is_valid:
                logger.warning(f"丢弃来自节点 {sender_id} 的区块头消息，因为包含孤儿区块")
                return
                
            # 检查当前节点是轻量级还是完整节点
            is_lightweight = False
            if self_id in peer_flags and peer_flags[self_id].get("light", False):
                is_lightweight = True
                
            # If yes and the peer is lightweight, add the block headers to the local blockchain.
            if is_lightweight:
                # 轻量级节点只存储区块头
                for header in received_headers:
                    block_id = header.get("block_id", "")
                    if block_id not in local_header_ids:
                        header_store.append(header)
                        logger.info(f"轻量级节点添加区块头: {block_id}")
                        
            # If yes and the peer is full, check if there are missing blocks in the local blockchain. 
            # If there are missing blocks, create a `GET_BLOCK` message and send it to the sender.
            else:
                # 完整节点需要请求缺失的完整区块
                if missing_blocks:
                    from block_handler import create_getblock
                    from outbox import enqueue_message
                    
                    getblock_msg = create_getblock(self_id, missing_blocks)
                    
                    if sender_id in known_peers:
                        sender_ip, sender_port = known_peers[sender_id]
                        enqueue_message(sender_id, sender_ip, sender_port, getblock_msg)
                        logger.info(f"完整节点请求缺失的区块: {missing_blocks}")
                    else:
                        logger.warning(f"无法向节点 {sender_id} 请求缺失区块，节点不在已知节点列表中")

        else:
            logger.warning(f"[{self_id}] 未知消息类型: {msg_type}")
    
    except Exception as e:
        logger.error(f"处理消息时发生异常: {e}", exc_info=True)