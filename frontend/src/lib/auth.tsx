import { createContext, useContext, useState, type PropsWithChildren } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import type { Me, Role } from './types'

interface AuthState {
  me: Me | null
  loading: boolean
  /** True after an explicit sign-out: guarded pages send the visitor to the welcome page, not a sign-in form. */
  signedOut: boolean
  demoLogin: (persona: Role) => Promise<Me>
  login: (email: string, password: string, expectedRole: Role) => Promise<Me>
  register: (email: string, password: string) => Promise<Me>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: PropsWithChildren) {
  const qc = useQueryClient()
  const [signedOut, setSignedOut] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.get<Me>('/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 60_000,
  })
  // Drop every cached query from the previous identity, but keep the ['me']
  // query itself so its live observer (this provider) receives the update.
  const resetCache = (me: Me | null) => {
    qc.removeQueries({ predicate: q => q.queryKey[0] !== 'me' })
    qc.setQueryData(['me'], me)
  }
  const signedIn = (me: Me) => { setSignedOut(false); resetCache(me); return me }
  const value: AuthState = {
    me: data ?? null,
    loading: isLoading,
    signedOut,
    demoLogin: async persona => signedIn(await api.post<Me>('/auth/demo/login', { persona })),
    login: async (email, password, expectedRole) => signedIn(await api.post<Me>('/auth/login', { email, password, expected_role: expectedRole })),
    register: async (email, password) => signedIn(await api.post<Me>('/auth/register', { email, password })),
    logout: async () => {
      await api.post('/auth/logout').catch(() => undefined)
      setSignedOut(true)
      resetCache(null)
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
