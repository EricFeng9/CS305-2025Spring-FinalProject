import socket
import threading
import json
import logging
from message_handler import dispatch_message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def start_socket_server(ip, port, peer_id):
    """
    创建TCP套接字并绑定到节点的IP地址和端口
    开始在套接字上监听接收传入的消息
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((ip, port))
        server_socket.listen(5)
        logger.info(f"节点 {peer_id} 在 {ip}:{port} 上启动")
        
        # 启动接收消息的线程
        threading.Thread(target=listen_for_messages, 
                         args=(server_socket, peer_id, ip), 
                         daemon=True).start()
        
        return server_socket
    except Exception as e:
        logger.error(f"启动套接字服务器失败: {e}")
        return None

def listen_for_messages(server_socket, peer_id, ip):
    """监听并处理传入的消息"""
    while True:
        try:
            client_socket, address = server_socket.accept()
            threading.Thread(target=handle_client, 
                            args=(client_socket, address, peer_id, ip), 
                            daemon=True).start()
        except Exception as e:
            logger.error(f"接受连接失败: {e}")
            break

def handle_client(client_socket, client_address, peer_id, self_ip):
    """处理来自客户端的请求"""
    try:
        # 设置接收超时
        client_socket.settimeout(10)
        data = b''
        
        # 接收数据直到找到换行符
        while b'\n' not in data:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            data += chunk
        
        # 如果收到的数据为空，关闭连接
        if not data:
            client_socket.close()
            return
        
        # 尝试解析为JSON
        try:
            # 以换行符分割，处理可能的多消息情况
            messages = data.decode('utf-8').split('\n')
            for message_str in messages:
                if not message_str.strip():
                    continue
                
                # 检查消息是否为有效的JSON格式
                if message_str and message_str[0] in ['{', '[']:    
                    msg = json.loads(message_str)
                    if msg:
                        # 处理接收到的消息
                        dispatch_message(msg, peer_id, self_ip)
                else:
                    if message_str.strip():
                        logger.error(f"收到的消息不是有效的JSON格式: {message_str[:50]}...")
        except json.JSONDecodeError as e:
            logger.error(f"解析消息失败: {e}")
            logger.debug(f"解析失败的原始消息: {data[:100]}...")
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")
            
    except socket.error as e:
        logger.error(f"处理客户端连接时出错: {e}")
    finally:
        client_socket.close()

