from flask import Flask, jsonify, render_template, request
from threading import Thread
from peer_manager import peer_status, rtt_tracker, get_peer_status, blacklist
from transaction import get_recent_transactions
from outbox import rate_limiter, get_outbox_status, get_drop_stats
from message_handler import get_redundancy_stats
from peer_discovery import known_peers
import json
from block_handler import blockchain
import time
import threading
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)

app = Flask(__name__)
app.json_encoder = CustomJSONEncoder

blockchain_data_ref = blockchain
known_peers_ref = None

# 全局状态数据，由节点主线程更新
dashboard_data = {
    "peers": {},
    "transactions": [],
    "blocks": [],
    "orphan_blocks": [],
    "latency": {},
    "capacity": 0,
    "redundancy": {}
}

def start_dashboard(peer_id, port=None):
    global blockchain_data_ref, known_peers_ref, dashboard_data
    dashboard_data["peer_id"] = peer_id
    blockchain_data_ref = blockchain
    known_peers_ref = known_peers
    
    # 使用节点ID作为环境变量，使其在模板中可访问
    os.environ['PEER_ID'] = str(peer_id)
    
    # 如果未提供端口，则根据节点ID计算端口
    if port is None:
        port = 7000 + int(peer_id) % 10000
    
    # 打印已知节点
    print(f"[{peer_id}] Known peers before dashboard start: {known_peers}")
    
    # 启动仪表盘
    print(f"[{peer_id}] Starting dashboard on port {port}")
    
    # 在新线程中运行Flask应用
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    
    # 打印节点状态
    ip = os.environ.get('NODE_IP', 'localhost')
    print(f"[{peer_id}] Node is now running at {ip}:{peer_id}")
    
    # 每30秒打印一次节点心跳
    def print_heartbeat():
        while True:
            print(f"[{peer_id}] Still alive at {time.strftime('%H:%M:%S')}")
            time.sleep(30)
    
    threading.Thread(target=print_heartbeat, daemon=True).start()
    
    # 添加以下代码，定期更新仪表盘数据
    def update_data_loop():
        while True:
            update_dashboard_data(peer_id)
            time.sleep(5)  # 每5秒更新一次
    
    # 启动更新线程
    threading.Thread(target=update_data_loop, daemon=True).start()

@app.route('/')
def index():
    peer_id = request.args.get('peer_id', os.environ.get('PEER_ID', '未知'))
    return render_template('index.html', peer_id=peer_id)

@app.route('/blocks')
def blocks():
    # 返回区块链数据
    return jsonify(dashboard_data["blocks"])

@app.route('/peers')
def peers():
    # 获取所有已知节点的状态
    status_info = {}
    raw_status = get_peer_status()
    
    # 确保键都是字符串类型
    for peer_id, info in raw_status.items():
        status_info[str(peer_id)] = info
    
    return jsonify(status_info)

@app.route('/api/network/peers')
def get_peers():
    # 获取所有已知节点的状态
    status_info = {}
    raw_status = get_peer_status()
    
    # 确保键都是字符串类型
    for peer_id, info in raw_status.items():
        status_info[str(peer_id)] = info
    
    return jsonify(status_info)

@app.route('/transactions')
def transactions():
    # 返回交易池数据
    return jsonify(dashboard_data["transactions"])

@app.route('/latency')
def latency():
    # 返回延迟数据
    return jsonify(dashboard_data["latency"])

@app.route('/capacity')
def capacity():
    # 返回节点容量
    return jsonify(rate_limiter.capacity)

@app.route('/orphan')
def orphan():
    # 返回孤块数据
    return jsonify(dashboard_data["orphan_blocks"])

@app.route('/redundancy')
def redundancy_stats():
    # 返回冗余消息统计
    return jsonify(dashboard_data["redundancy"])

@app.route('/api/network/stats')
def get_network_stats():
    # 获取网络统计信息
    redundancy = get_redundancy_stats()
    outbox_status = get_outbox_status()
    drop_stats = get_drop_stats()
    
    return jsonify({
        'message_redundancy': redundancy,
        'outbox_status': outbox_status,
        'drop_stats': drop_stats
    })

@app.route('/api/blockchain/status')
def get_blockchain_status():
    # 获取区块链状态
    chain_length = len(blockchain)
    latest_block = blockchain[-1] if blockchain else {}
    
    return jsonify({
        'chain_length': chain_length,
        'latest_block': latest_block
    })

@app.route('/api/blockchain/blocks')
def get_blockchain_blocks():
    # 获取区块链上的所有区块
    return jsonify(blockchain)

@app.route('/api/blacklist')
def get_blacklist():
    # 获取黑名单列表
    return jsonify(list(blacklist))

@app.route('/api/capacity')
def get_capacity():
    # 获取节点当前发送容量
    capacity = {
        'current': rate_limiter.capacity,
        'usage': rate_limiter.tokens / rate_limiter.capacity
    }
    return jsonify(capacity)

def update_dashboard_data(peer_id):
    """更新仪表盘数据"""
    global dashboard_data
    
    # 更新节点信息
    from peer_manager import get_peer_status
    dashboard_data["peers"] = get_peer_status()
    
    # 更新交易信息
    from transaction import get_recent_transactions
    dashboard_data["transactions"] = get_recent_transactions()
    
    # 更新区块信息
    from block_handler import blockchain, block_headers, orphan_blocks, is_lightweight
    if is_lightweight:
        dashboard_data["blocks"] = block_headers
    else:
        dashboard_data["blocks"] = [{
            "block_id": block["block_id"],
            "prev_block_id": block["prev_block_id"],
            "height": block.get("height", 0),
            "timestamp": block["timestamp"],
            "tx_count": len(block.get("transactions", []))
        } for block in blockchain]
    
    # 更新孤块信息
    dashboard_data["orphan_blocks"] = [{
        "block_id": block["block_id"],
        "prev_block_id": block["prev_block_id"],
        "timestamp": block["timestamp"]
    } for block in orphan_blocks]
    
    # 更新传输延迟信息
    from peer_manager import rtt_tracker
    latency_data = {}
    for peer, rtts in rtt_tracker.items():
        if rtts:
            latency_data[peer] = sum(rtts) / len(rtts)
    dashboard_data["latency"] = latency_data
    
    # 更新节点发送容量
    from outbox import rate_limiter
    dashboard_data["capacity"] = rate_limiter.capacity
    
    # 更新冗余消息信息
    from message_handler import get_redundancy_stats
    dashboard_data["redundancy"] = get_redundancy_stats()


