import { joinURL } from 'ufo'
import { defineEventHandler, proxyRequest } from 'h3'

export default defineEventHandler((event) => {
  const config = useRuntimeConfig(event)
  const targetBase = String(config.apiProxyTarget || 'http://127.0.0.1:8100')
  const target = joinURL(targetBase, event.path)
  return proxyRequest(event, target)
})
