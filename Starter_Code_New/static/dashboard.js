// 仪表盘数据刷新周期(毫秒)
const REFRESH_INTERVAL = 5000;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 测试JS是否成功加载
    const jsTestElement = document.getElementById('js-test');
    if (jsTestElement) {
        jsTestElement.textContent = "JS已成功加载";
        jsTestElement.style.backgroundColor = "#d4edda";
        jsTestElement.style.color = "#155724";
        jsTestElement.style.padding = "3px 8px";
        jsTestElement.style.borderRadius = "4px";
        console.log('dashboard.js 已成功加载并执行');
    }

    // 获取并显示节点ID
    const peerId = document.getElementById('peer-id').textContent;
    console.log(`Dashboard initialized for peer: ${peerId}`);
    
    // 首次加载数据
    refreshAllData();
    
    // 设置定时刷新
    setInterval(refreshAllData, REFRESH_INTERVAL);
});

// 刷新所有数据
function refreshAllData() {
    // 显示更新动画
    document.getElementById('last-updated').classList.add('updating');
    
    Promise.all([
        fetchPeers(),
        fetchBlocks(),
        fetchOrphanBlocks(),
        fetchTransactions(),
        fetchLatency(),
        fetchCapacity(),
        fetchRedundancy(),
        fetchBlacklist(),
        fetchNetworkStats()
    ]).then(() => {
        // 更新最后刷新时间
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        const lastUpdated = document.getElementById('last-updated');
        lastUpdated.textContent = timeString;
        
        // 移除更新动画
        setTimeout(() => {
            lastUpdated.classList.remove('updating');
        }, 300);
    }).catch(error => {
        console.error('数据刷新失败:', error);
    });
}

// 截断长ID
function truncateId(id, length = 8) {
    if (!id) return '未知';
    if (id.length <= length) return id;
    return `${id.substring(0, length)}...`;
}

// 获取节点信息
function fetchPeers() {
    return fetch('/peers')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('peers-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('peers-section');
            
            if (Object.keys(data).length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td colspan="6" class="empty-state">没有已知节点</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新节点数量
            updateCounter('peers-section', Object.keys(data).length);
            
            for (const [peerId, peerInfo] of Object.entries(data)) {
                const row = document.createElement('tr');
                const statusClass = peerInfo.status.toLowerCase() === 'active' ? 'status-online' : 'status-offline';
                row.innerHTML = `
                    <td><span class="truncate-id" title="${peerInfo.peer_id}">${peerInfo.peer_id}</span></td>
                    <td>${peerInfo.ip}</td>
                    <td>${peerInfo.port}</td>
                    <td><span class="status ${statusClass}">${peerInfo.status}</span></td>
                    <td>${peerInfo.is_nated ? '是' : '否'}</td>
                    <td>${peerInfo.is_lightweight ? '是' : '否'}</td>
                `;
                tableBody.appendChild(row);
            }
        })
        .catch(error => console.error('获取节点信息失败:', error));
}

// 获取区块信息
function fetchBlocks() {
    return fetch('/blocks')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('blocks-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('blocks-section');
            
            if (data.length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td colspan="5" class="empty-state">没有区块</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新区块数量
            updateCounter('blocks-section', data.length);
            
            data.forEach(block => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td><span class="truncate-id" title="${block.block_id}">${truncateId(block.block_id)}</span></td>
                    <td><span class="truncate-id" title="${block.prev_block_id}">${truncateId(block.prev_block_id || '创世区块')}</span></td>
                    <td>${block.height || '未知'}</td>
                    <td>${formatTimestamp(block.timestamp)}</td>
                    <td>${block.tx_count || block.transactions?.length || '0'}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取区块信息失败:', error));
}

// 获取孤立区块信息
function fetchOrphanBlocks() {
    return fetch('/orphans')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('orphan-blocks-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('orphan-blocks-section');
            
            if (data.length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td colspan="3" class="empty-state">没有孤立区块</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新孤块数量
            updateCounter('orphan-blocks-section', data.length);
            
            data.forEach(block => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td><span class="truncate-id" title="${block.block_id}">${truncateId(block.block_id)}</span></td>
                    <td><span class="truncate-id" title="${block.prev_block_id}">${truncateId(block.prev_block_id || '未知')}</span></td>
                    <td>${formatTimestamp(block.timestamp)}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取孤立区块信息失败:', error));
}

// 获取交易信息
function fetchTransactions() {
    return fetch('/transactions')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('transactions-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('transactions-section');
            
            if (data.length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td colspan="5" class="empty-state">没有交易</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新交易数量
            updateCounter('transactions-section', data.length);
            
            data.forEach(tx => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td><span class="truncate-id" title="${tx.id || '未知'}">${truncateId(tx.id || '未知')}</span></td>
                    <td><span class="truncate-id" title="${tx.from || tx.from_peer || '未知'}">${truncateId(tx.from || tx.from_peer || '未知')}</span></td>
                    <td><span class="truncate-id" title="${tx.to || tx.to_peer || '未知'}">${truncateId(tx.to || tx.to_peer || '未知')}</span></td>
                    <td>${tx.amount || '未知'}</td>
                    <td>${formatTimestamp(tx.timestamp)}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取交易信息失败:', error));
}

// 获取延迟信息
function fetchLatency() {
    return fetch('/latency')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('latency-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('latency-section');
            
            if (Object.keys(data).length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td colspan="2" class="empty-state">没有延迟数据</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新节点数量
            updateCounter('latency-section', Object.keys(data).length);
            
            // 按延迟排序
            const sortedPeers = Object.entries(data).sort((a, b) => a[1] - b[1]);
            
            sortedPeers.forEach(([peerId, latency]) => {
                const row = document.createElement('tr');
                // 高亮显示高延迟
                const isHighLatency = latency > 500;
                if (isHighLatency) {
                    row.classList.add('highlight-row');
                }
                
                row.innerHTML = `
                    <td>${peerId}</td>
                    <td>${latency.toFixed(2)} ms</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取延迟信息失败:', error));
}

// 获取容量信息
function fetchCapacity() {
    return fetch('/capacity')
        .then(response => response.json())
        .then(data => {
            document.getElementById('capacity').textContent = data;
        })
        .catch(error => console.error('获取容量信息失败:', error));
}

// 获取冗余信息
function fetchRedundancy() {
    return fetch('/redundancy')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('redundancy-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('redundancy-section');
            
            if (Object.keys(data).length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td colspan="2" class="empty-state">没有冗余消息</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新消息数量
            updateCounter('redundancy-section', Object.keys(data).length);
            
            // 按重复次数排序
            const sortedMessages = Object.entries(data).sort((a, b) => b[1] - a[1]);
            
            sortedMessages.forEach(([msgId, count]) => {
                const row = document.createElement('tr');
                // 高亮显示高重复次数
                if (count > 3) {
                    row.classList.add('highlight-row');
                }
                
                row.innerHTML = `
                    <td><span class="truncate-id" title="${msgId}">${truncateId(msgId)}</span></td>
                    <td>${count}</td>
                `;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取冗余信息失败:', error));
}

// 获取黑名单信息
function fetchBlacklist() {
    return fetch('/api/blacklist')
        .then(response => response.json())
        .then(data => {
            const tableBody = document.getElementById('blacklist-table');
            tableBody.innerHTML = '';
            const section = document.getElementById('blacklist-section');
            
            if (data.length === 0) {
                section.classList.add('empty');
                tableBody.innerHTML = '<tr><td class="empty-state">没有黑名单节点</td></tr>';
                return;
            }
            
            section.classList.remove('empty');
            
            // 更新黑名单数量
            updateCounter('blacklist-section', data.length);
            
            data.forEach(peerId => {
                const row = document.createElement('tr');
                row.innerHTML = `<td>${peerId}</td>`;
                tableBody.appendChild(row);
            });
        })
        .catch(error => console.error('获取黑名单信息失败:', error));
}

// 获取网络统计信息
function fetchNetworkStats() {
    return fetch('/api/network/stats')
        .then(response => response.json())
        .then(data => {
            const container = document.getElementById('network-stats-content');
            const section = document.getElementById('network-stats-section');
            
            if (!data || (Object.keys(data.outbox_status || {}).length === 0 && Object.keys(data.drop_stats || {}).length === 0)) {
                section.classList.add('empty');
                container.innerHTML = '<div class="empty-state">没有网络统计数据</div>';
                return;
            }
            
            section.classList.remove('empty');
            
            let html = '<dl>';
            
            // 显示发送队列状态
            html += '<dt>发送队列状态</dt>';
            if (Object.keys(data.outbox_status || {}).length === 0) {
                html += '<dd>无发送队列数据</dd>';
            } else {
                html += '<dd><ul>';
                for (const [peerId, queueInfo] of Object.entries(data.outbox_status)) {
                    html += `<li>节点 ${peerId}: ${queueInfo.total_messages} 条消息等待发送</li>`;
                }
                html += '</ul></dd>';
            }
            
            // 显示消息丢弃统计
            html += '<dt>消息丢弃统计</dt>';
            if (Object.keys(data.drop_stats || {}).length === 0) {
                html += '<dd>无消息丢弃数据</dd>';
            } else {
                html += '<dd><ul>';
                for (const [msgType, count] of Object.entries(data.drop_stats)) {
                    html += `<li>${msgType}: 丢弃 ${count} 次</li>`;
                }
                html += '</ul></dd>';
            }
            
            html += '</dl>';
            container.innerHTML = html;
        })
        .catch(error => console.error('获取网络统计信息失败:', error));
}

// 更新卡片标题中的计数器
function updateCounter(sectionId, count) {
    const section = document.getElementById(sectionId);
    if (!section) return;
    
    const title = section.querySelector('h2');
    if (!title) return;
    
    // 查找或创建计数器元素
    let counter = title.querySelector('.counter');
    if (!counter) {
        counter = document.createElement('span');
        counter.className = 'counter';
        title.appendChild(counter);
    }
    
    counter.textContent = count;
}

// 格式化时间戳
function formatTimestamp(timestamp) {
    if (!timestamp) return '未知';
    
    try {
        const date = new Date(timestamp * 1000);
        return date.toLocaleString();
    } catch (e) {
        return timestamp;
    }
} 