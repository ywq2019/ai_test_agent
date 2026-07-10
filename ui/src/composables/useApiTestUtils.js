/**
 * 接口测试通用工具函数
 * 供 CaseList / UnitExec / LoadTest / ReportList 复用
 */

export function useApiTestUtils() {
  const methodColor = (m) => {
    const map = { GET: '', POST: 'success', PUT: 'warning', DELETE: 'danger', PATCH: 'info' }
    return map[m] || ''
  }

  const formatTime = (iso) => {
    if (!iso) return ''
    const d = new Date(iso.includes('Z') ? iso : iso + 'Z')
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }

  const passRate = (r) => {
    if (!r.total) return 0
    return ((r.passed / r.total) * 100).toFixed(1)
  }

  const passRateColor = (r) => {
    const rate = r.total ? r.passed / r.total : 1
    return rate >= 0.9 ? 'color:#67c23a' : rate >= 0.6 ? 'color:#e6a23c' : 'color:#f56c6c'
  }

  const matchTypeLabel = (mt) => {
    const map = { equals: '等于', contains: '包含', exists: '存在', not_exists: '不存在', not_empty: '非空', type: '类型是', regex: '正则' }
    return map[mt] || mt
  }

  const isJsonResponse = (text) => {
    if (!text) return false
    const t = text.trim()
    return (t.startsWith('{') || t.startsWith('['))
  }

  const formatResponsePreview = (text) => {
    if (!text) return ''
    const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    let source = text
    if (isJsonResponse(text)) {
      try { source = JSON.stringify(JSON.parse(text), null, 2) } catch { /* keep original */ }
    }
    return escape(source).replace(
      /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
      (m) => {
        if (/^"/.test(m)) return /:$/.test(m) ? `<span class="rp-key">${m}</span>` : `<span class="rp-str">${m}</span>`
        if (/true|false/.test(m)) return `<span class="rp-bool">${m}</span>`
        if (/null/.test(m)) return `<span class="rp-null">${m}</span>`
        return `<span class="rp-num">${m}</span>`
      }
    )
  }

  const copyResponseText = (text) => {
    import('element-plus').then(({ ElMessage }) => {
      navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制')).catch(() => ElMessage.error('复制失败'))
    })
  }

  const formatBodyPreview = (c) => {
    if (c.body_type === 'raw' && c.body_raw) {
      const raw = c.body_raw
      const m = raw.match(/^\{\{(\w+)\(([^{}]*)\)\}\}$/)
      if (m) return `[自定义函数: ${m[1]}(${m[2]})]`
      if (raw.includes('{{')) return raw.length > 120 ? raw.slice(0, 120) + '…' : raw
      return raw.length > 200 ? raw.slice(0, 200) + '…' : raw
    }
    if (c.body) {
      try { return JSON.stringify(c.body, null, 2) } catch { return String(c.body) }
    }
    return ''
  }

  return {
    methodColor, formatTime, passRate, passRateColor,
    matchTypeLabel, isJsonResponse, formatResponsePreview,
    copyResponseText, formatBodyPreview,
  }
}
