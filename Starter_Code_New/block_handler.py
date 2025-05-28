import time
import hashlib
import json
import threading
import random
from transaction import get_recent_transactions, clear_pool
from peer_discovery import known_peers, peer_config
from utils import generate_message_id

from outbox import  enqueue_message, gossip_message
from peer_manager import record_offense

received_blocks = [] # The local blockchain. The blocks are added linearly at the end of the set.
header_store = [] # The header of blocks in the local blockchain. Used by lightweight peers.
orphan_blocks = {} # The block whose previous block is not in the local blockchain. Waiting for the previous block.

#sync change(new peer join in)
def request_block_sync(self_id):
    # TODO: Define the JSON format of a `GET_BLOCK_HEADERS`, which should include `{message type, sender's ID}`.
    msg={
        "type": "GET_BLOCK_HEADERS",
        "sender_id": self_id,
        "message_id": generate_message_id(self_id)
    }
    # TODO: Send a `GET_BLOCK_HEADERS` message to each known peer and put the messages in the outbox queue.
    for peer_id, (ip, port) in known_peers.items():
        if peer_id != self_id:
            enqueue_message(peer_id, ip, port, msg)

def block_generation(self_id, MALICIOUS_MODE, interval=20):
    from inv_message import create_inv
    def mine():
        while True:
            time.sleep(interval)
    # TODO: Create a new block periodically using the function `create_dummy_block`.
            new_block = create_dummy_block(self_id, MALICIOUS_MODE)
    # TODO: Create an `INV` message for the new block using the function `create_inv` in `inv_message.py`.
            block_ids=[]
            for block in received_blocks:
                block_ids.append(block["block_id"])
            inv_msg=create_inv(self_id, block_ids)
    # TODO: Broadcast the `INV` message to known peers using the function `gossip` in `outbox.py`.
            gossip_message(self_id, inv_msg)
    threading.Thread(target=mine, daemon=True).start()

#create a dummy block
def create_dummy_block(peer_id, MALICIOUS_MODE):

    # TODO: Define the JSON format of a `block`, which should include `{message type, peer's ID, timestamp, block ID, previous block's ID, and transactions}`. 
    # The `block ID` is the hash value of block structure except for the item `block ID`. 
    # `previous block` is the last block in the blockchain, to which the new block will be linked. 
    # If the block generator is malicious, it can generate random block ID.
    block={
        "type": "BLOCK",
        "peer_id": peer_id,
        "timestamp": time.time(),
        "block_id": "",  
        "previous_block_id": received_blocks[-1]["block_id"] if received_blocks else None,  
        "transactions": []  
    }
    # TODO: Read the transactions in the local `tx_pool` using the function `get_recent_transactions` in `transaction.py`.
    transactions = get_recent_transactions()
    block["transactions"] = transactions
    # TODO: Create a new block with the transactions and generate the block ID using the function `compute_block_hash`.
    if MALICIOUS_MODE:
        #generate a random block ID
        block["block_id"] = hashlib.sha256(str(random.random()).encode()).hexdigest()
    else:
        block["block_id"] = compute_block_hash(block)
    # TODO: Clear the local transaction pool and add the new block into the local blockchain (`receive_block`).
    clear_pool()
    received_blocks.append(block)
    header_store.append({
        "block_id": block["block_id"],
        "previous_block_id": block["previous_block_id"]
    })
    return block

def compute_block_hash(block):
    # TODO: Compute the hash of a block except for the term `block ID`.
    block_data=block.copy()
    block_data.pop("block_id", None)
    block_data_str = json.dumps(block_data, sort_keys=True).encode()
    return hashlib.sha256(block_data_str).hexdigest()


def handle_block(msg, self_id):
    # 注意：区块哈希验证已经在message_handler.py中完成，这里不再重复验证
    # computed_hash = compute_block_hash(msg)
    # if computed_hash != msg["block_id"]:
    #     sender_id = msg.get("peer_id") or msg.get("sender_id") 
    #     if sender_id:
    #         print(f"检测到恶意节点 {sender_id}，区块ID验证失败")
    #         record_offense(sender_id)
    #     return
    
    # TODO: Check if the block exists in the local blockchain. If yes, drop the block.
    for block in received_blocks:
        if block["block_id"] == msg["block_id"]:
            print("区块已存在于本地区块链中，忽略")
            return
            
    # TODO: Check if the previous block of the block exists in the local blockchain. If not, add the block to the list of orphaned blocks (`orphan_blocks`). If yes, add the block to the local blockchain.
    previous_block_id = msg.get("previous_block_id")
    isPreviousBlockExist = False
    for block in received_blocks:
        if block["block_id"] == previous_block_id:
            isPreviousBlockExist = True
            break
            
    if previous_block_id is None or isPreviousBlockExist:
        received_blocks.append(msg)
        header_store.append({
            "block_id": msg["block_id"],
            "previous_block_id": msg["previous_block_id"]
        })
        print(f"区块 {msg['block_id']} 已添加到本地区块链中")

    else:
        orphan_blocks[msg["block_id"]] = msg
        print(f"区块 {msg['block_id']} 的前置区块 {previous_block_id} 不存在，暂存为孤块")
        return
        
    # TODO: Check if the block is the previous block of blocks in `orphan_blocks`. If yes, add the orphaned blocks to the local blockchain.
    orphaned_to_add = []
    for orphan_id, orphan_block in orphan_blocks.items():
        if orphan_block["previous_block_id"] == msg["block_id"]:
            received_blocks.append(orphan_block)
            header_store.append({
                "block_id": orphan_block["block_id"],
                "previous_block_id": orphan_block["previous_block_id"]
            })
            orphaned_to_add.append(orphan_id)
            print(f"孤块 {orphan_id} 现在可以添加到区块链中")
            
    for orphan_id in orphaned_to_add:
        del orphan_blocks[orphan_id]



def create_getblock(sender_id, requested_ids):
    # TODO: Define the JSON format of a `GETBLOCK` message, which should include `{message type, sender's ID, requesting block IDs}`.
    msg = {
        "type": "GETBLOCK",
        "sender_id": sender_id,
        "requested_ids": requested_ids
    }
    return msg


def get_block_by_id(block_id):
    # TODO: Return the block in the local blockchain based on the block ID.
    for block in received_blocks:
        if block["block_id"] == block_id:
            return block
    return

def get_inventory():
    """获取本地区块链中的所有区块ID"""
    block_ids = []
    for block in received_blocks:
        block_ids.append(block["block_id"])
    return block_ids