from flask import Flask, jsonify, render_template, request, url_for
from threading import Thread
from peer_manager import peer_status, rtt_tracker, get_peer_status, blacklist
from transaction import get_recent_transactions
from outbox import rate_limiter, get_outbox_status, get_drop_stats
from message_handler import get_redundancy_stats
from peer_discovery import known_peers,peer_flags
from block_handler import received_blocks, header_store
import json
import time
import threading
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))
static_folder = os.path.join(current_dir, 'static')
template_folder = os.path.join(current_dir, 'templates')

# 打印文件夹路径信息
print(f"静态文件夹路径: {static_folder}")
print(f"模板文件夹路径: {template_folder}")
print(f"静态文件存在: {os.path.exists(static_folder)}")
print(f"模板文件存在: {os.path.exists(template_folder)}")
if os.path.exists(static_folder):
    print(f"静态文件列表: {os.listdir(static_folder)}")
if os.path.exists(template_folder):
    print(f"模板文件列表: {os.listdir(template_folder)}")

# 初始化Flask应用程序，指定静态文件和模板目录
app = Flask(__name__, 
           static_folder=static_folder,
           template_folder=template_folder)

blockchain_data_ref = None
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

#--------------------------------------------#
def start_dashboard(peer_id, port=None):
    global blockchain_data_ref, known_peers_ref, dashboard_data
    dashboard_data["peer_id"] = peer_id
    blockchain_data_ref = received_blocks
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
def home():
    # 渲染主页模板，传递节点ID
    return render_template('index.html', peer_id=os.environ.get('PEER_ID', 'Unknown'))

@app.route('/blocks')
def blocks():
    # display the blocks in the local blockchain.
    # 返回区块链数据
    return jsonify(dashboard_data["blocks"])

@app.route('/peers')
def peers():
    # display the information of known peers, 
    # including `{peer's ID, IP address, port, status, NATed or non-NATed, lightweight or full}`.
    peers_info = {}
    
    # 整合所有节点信息
    for peer_id, (ip, port) in known_peers.items():
        peer_id_str = str(peer_id)
        peers_info[peer_id_str] = {
            "peer_id": peer_id_str,
            "ip": ip,
            "port": port,
            "status": peer_status.get(peer_id, "UNKNOWN"),
            "is_nated": peer_flags.get(peer_id, {}).get("nat", False),
            "is_lightweight": peer_flags.get(peer_id, {}).get("light", False)
        }
    
    return jsonify(peers_info)

@app.route('/transactions')
def transactions():
    # display the transactions in the local pool `tx_pool`.
    # 返回交易池数据
    return jsonify(dashboard_data["transactions"])

@app.route('/latency')
def latency():
    # display the transmission latency between peers.
    # 返回延迟数据
    return jsonify(dashboard_data["latency"])

@app.route('/capacity')
def capacity():
    # display the sending capacity of the peer.
    # 返回节点容量
    return jsonify(rate_limiter.capacity)

@app.route('/orphans')
def orphan_blocks():
    # display the orphaned blocks.
    # 返回孤块数据
    return jsonify(dashboard_data["orphan_blocks"])

@app.route('/redundancy')
def redundancy_stats():
    # display the number of redundant messages received.
    # 返回冗余消息统计
    return jsonify(dashboard_data["redundancy"])
#--------------------------------------------#

#------以下为额外添加内容-------
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
    chain_length = len(received_blocks)
    latest_block = received_blocks[-1] if received_blocks else {}
    
    return jsonify({
        'chain_length': chain_length,
        'latest_block': latest_block
    })

@app.route('/api/blockchain/blocks')
def get_blockchain_blocks():
    # 获取区块链上的所有区块
    return jsonify(received_blocks)

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
    from block_handler import received_blocks, orphan_blocks
    # 使用header_store代替不存在的block_headers
    is_lightweight = False
    if is_lightweight:
        dashboard_data["blocks"] = header_store
    else:
        dashboard_data["blocks"] = [{
            "block_id": block["block_id"],
            "prev_block_id": block.get("previous_block_id", None),
            "height": block.get("height", 0),
            "timestamp": block["timestamp"],
            "tx_count": len(block.get("transactions", []))
        } for block in received_blocks]
    
    # 更新孤块信息
    dashboard_data["orphan_blocks"] = [{
        "block_id": block["block_id"],
        "prev_block_id": block.get("previous_block_id", None),
        "timestamp": block["timestamp"]
    } for block in orphan_blocks.values()]
    
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
