/**
 * useWebSocket — 可复用的 WebSocket 连接管理 Composable
 *
 * 解决原来各组件各自维护 ws 变量的问题：
 *  - 统一心跳 pong 响应
 *  - 安全关闭（避免重复 close / 竞态）
 *  - onUnmounted 自动清理
 *
 * 用法：
 *   const { connect, disconnect, send } = useWebSocket(onMessage)
 *   connect('cases_gen')
 *
 * @param {Function} onMessage  收到业务消息时的回调，参数为解析后的对象
 * @returns {{ connect, disconnect, send, isConnected }}
 */
import { ref, onUnmounted } from 'vue'

export function useWebSocket(onMessage) {
  let _ws = null
  let _clientId = ''
  const isConnected = ref(false)

  /** 建立连接，若已有旧连接则先关闭 */
  function connect(clientId) {
    disconnect()
    _clientId = clientId
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    _ws = new WebSocket(`${proto}://${window.location.host}/ws?client_id=${clientId}`)

    _ws.onopen = () => { isConnected.value = true }

    _ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        // 心跳 pong，防止服务端超时断开
        if (data.type === 'ping') {
          if (_ws && _ws.readyState === WebSocket.OPEN) {
            _ws.send(JSON.stringify({ type: 'pong' }))
          }
          return
        }
        onMessage && onMessage(data)
      } catch (_) { /* 忽略非 JSON 帧 */ }
    }

    _ws.onclose = () => { isConnected.value = false }
    _ws.onerror = () => { isConnected.value = false }
  }

  /** 安全关闭连接 */
  function disconnect() {
    if (_ws) {
      try {
        if (_ws.readyState <= WebSocket.OPEN) _ws.close()
      } catch (_) { /* 忽略关闭异常 */ }
      _ws = null
    }
    isConnected.value = false
  }

  /** 发送消息（仅在连接 OPEN 时发送） */
  function send(data) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  // 组件卸载时自动清理，防止内存泄漏
  onUnmounted(disconnect)

  return { connect, disconnect, send, isConnected }
}
