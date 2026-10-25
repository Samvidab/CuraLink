/**
 * Real-time sync through Convex (frontend/convex). The FastAPI API stays the source of truth for every screen;
 * Convex pushes "something you may see changed" so open pages refresh immediately (e.g. Dr. Rivera's case page
 * updates the moment Sam submits a summary). Enabled only when VITE_CONVEX_URL is set AND the API reports Convex
 * sync is on, so local development without Convex is unchanged.
 */
import { useCallback, useEffect, useMemo, useRef, type PropsWithChildren } from 'react'
import { ConvexProviderWithAuth, ConvexReactClient, useConvexAuth, useQuery as useConvexQuery } from 'convex/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api as convexApi } from '../../convex/_generated/api'
import { api } from './api'
import { useAuth } from './auth'
import type { Health } from './types'

const CONVEX_URL = import.meta.env.VITE_CONVEX_URL as string | undefined
let client: ConvexReactClient | null = null

function useCuraLinkConvexAuth() {
  const { me, loading } = useAuth()
  const meId = me?.id
  const fetchAccessToken = useCallback(async () => {
    if (!meId) return null
    try { return (await api.get<{ token: string }>('/convex/token')).token } catch { return null }
  }, [meId])
  return useMemo(() => ({ isLoading: loading, isAuthenticated: !!meId, fetchAccessToken }), [loading, meId, fetchAccessToken])
}

function Refresher() {
  const qc = useQueryClient()
  const { isAuthenticated } = useConvexAuth()
  const cursor = useConvexQuery(convexApi.live.cursor, isAuthenticated ? {} : 'skip')
  const last = useRef<string | null>(null)
  useEffect(() => {
    if (!cursor) return
    const key = JSON.stringify(cursor.tables)
    if (last.current !== null && last.current !== key) qc.invalidateQueries({ predicate: q => q.queryKey[0] !== 'me' && q.queryKey[0] !== 'health' })
    last.current = key
  }, [cursor, qc])
  return null
}

/** Wraps the app; a no-op unless Convex is configured on both sides. */
export function LiveSync({ children }: PropsWithChildren) {
  const health = useQuery({ queryKey: ['health'], queryFn: () => api.get<Health>('/health'), staleTime: 60_000 })
  const on = Boolean(CONVEX_URL && health.data?.convex?.enabled)
  if (!on) return <>{children}</>
  client ??= new ConvexReactClient(CONVEX_URL!)
  return <ConvexProviderWithAuth client={client} useAuth={useCuraLinkConvexAuth}><Refresher/>{children}</ConvexProviderWithAuth>
}
