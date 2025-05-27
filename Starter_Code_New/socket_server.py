import socket
import threading
import json
import logging
from message_handler import dispatch_message

# 初始化日志器
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def start_socket_server(self_id, self_ip, port):

    def listen_loop():
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self_ip, port))
            server_socket.listen()
            logger.info(f"节点 {self_id} 正在 {self_ip}:{port} 上监听连接")

        except Exception as e:
            logger.error(f"节点 {self_id} 启动失败：{e}")
            return

        while True:
            try:
                client_socket, addr = server_socket.accept()
                logger.info(f"节点 {self_id} 接收到来自 {addr} 的连接")

                def handle_client(sock):
                    try:
                        data = b""
                        while b"\n" not in data:
                            chunk = sock.recv(4096)
                            if not chunk:
                                break
                            data += chunk

                        messages = data.decode().split("\n")
                        for msg in messages:
                            if msg.strip():
                                try:
                                    json_data = json.loads(msg)
                                    dispatch_message(json_data, self_id, self_ip)
                                except json.JSONDecodeError:
                                    logger.warning(f"节点 {self_id} 收到非法JSON：{msg[:100]}")

                    except Exception as e:
                        logger.error(f"处理客户端消息失败：{e}")
                    finally:
                        sock.close()
                        logger.debug(f"关闭与客户端 {addr} 的连接")

                threading.Thread(target=handle_client, args=(client_socket,), daemon=True).start()

            except Exception as e:
                logger.error(f"接收连接出错：{e}")

    threading.Thread(target=listen_loop, daemon=True).start()
