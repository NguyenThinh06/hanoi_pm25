import { useEffect, useState } from 'react'

export const url = (path, params) => `${path}?${new URLSearchParams(params)}`

async function getJson(path, signal) {
  let res
  try {
    res = await fetch(path, { signal })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new Error('Không kết nối được máy chủ API.')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok || body === null) {
    throw new Error(body?.error?.message ?? `API trả về lỗi (HTTP ${res.status}).`)
  }
  return body
}

// path = null: chưa đủ tham số, chưa gọi. Giữ data cũ khi đang tải để bản đồ không nháy.
export function useGet(path) {
  const [state, setState] = useState({})
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!path) {
      setState({})
      return
    }
    const ctrl = new AbortController()
    setState((s) => ({ data: s.data, loading: true }))
    getJson(path, ctrl.signal).then(
      (data) => setState({ data }),
      (e) => e.name !== 'AbortError' && setState({ error: e.message }),
    )
    return () => ctrl.abort()
  }, [path, attempt])

  return { ...state, retry: () => setAttempt((n) => n + 1) }
}
