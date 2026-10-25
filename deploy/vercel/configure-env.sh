#!/usr/bin/env bash
# Production configuration for CuraLink on Vercel (frontend + FastAPI) + Convex + Neon, WITHOUT printing secrets.
#   deploy/vercel/configure-env.sh core       # generate + set all non-API-key settings (Vercel production + Convex prod)
#   deploy/vercel/configure-env.sh api-keys   # copy ANTHROPIC/CARTESIA keys from the git-ignored .env into Vercel
# Production and development keep SEPARATE secrets: everything below is freshly generated for production only.
# DATABASE_URL comes from the Neon integration and is not touched here.
set -euo pipefail
VERCEL="npx -y vercel@63.1.2"
CONVEX_PROD="fantastic-porpoise-318"
CONVEX_URL="https://${CONVEX_PROD}.convex.cloud"
CONVEX_SITE_URL="https://${CONVEX_PROD}.convex.site"
ISSUER="https://production.curalink-issuer.example"   # an identifier (never fetched): the public keys are given to Convex inline
umask 077
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

setv() { # NAME FILE [--sensitive]  -> Vercel Production; value read from FILE, never echoed
  $VERCEL env rm "$1" production -y >/dev/null 2>&1 || true
  $VERCEL env add "$1" production ${3:-} < "$2" >/dev/null && echo "  Vercel: set $1"
}
val() { printf '%s' "$2" > "$T/$1"; echo "$T/$1"; }

case "${1:-}" in
core)
  python3 -c "import secrets; print(secrets.token_urlsafe(40), end='')" > "$T/sync"
  python3 -c "import secrets; print(secrets.token_urlsafe(40), end='')" > "$T/admin"
  python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode(), end='')" > "$T/sig"
  uv run --quiet --project backend python - "$T/jwt" "$T/jwks" <<'PY'
import base64, hashlib, json, sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
open(sys.argv[1], "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
n = k.public_key().public_numbers()
b = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
nb = n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")
jwks = {"keys": [{"kty": "RSA", "n": b(n.n), "e": b(n.e), "alg": "RS256", "use": "sig", "kid": hashlib.sha256(nb).hexdigest()[:16]}]}
open(sys.argv[2], "w").write("data:text/plain;charset=utf-8;base64," + base64.b64encode(json.dumps(jwks).encode()).decode())
PY
  setv ENVIRONMENT "$(val env production)"
  setv DEMO_MODE "$(val dm true)"
  setv COOKIE_SECURE "$(val cs true)"
  setv DEMO_CONTROLS "$(val dc token)"
  setv DEMO_INBOX_REDIRECT "$(val dir true)"
  setv EMAIL_DELIVERY_MODE "$(val edm test_inbox)"
  setv TEST_EMAIL_ALLOWLIST "$(val tea example.com)"
  setv MAX_UPLOAD_MB "$(val mum 4)"
  setv CONVEX_SITE_URL "$(val csu "$CONVEX_SITE_URL")"
  setv CONVEX_JWT_ISSUER "$(val iss "$ISSUER")"
  setv VITE_CONVEX_URL "$(val vcu "$CONVEX_URL")"
  setv CONVEX_SYNC_SECRET "$T/sync" --sensitive
  setv DEMO_ADMIN_TOKEN "$T/admin" --sensitive
  setv SIGNATURE_ENCRYPTION_KEY "$T/sig" --sensitive
  setv CONVEX_JWT_PRIVATE_KEY "$T/jwt" --sensitive
  # Convex production deployment (separate from dev/local): sync secret, issuer name, PUBLIC key set.
  (cd frontend && npx convex env set --deployment "$CONVEX_PROD" CURALINK_SYNC_SECRET "$(cat "$T/sync")" >/dev/null && echo "  Convex prod: set CURALINK_SYNC_SECRET")
  (cd frontend && npx convex env set --deployment "$CONVEX_PROD" CURALINK_JWT_ISSUER "$ISSUER" >/dev/null && echo "  Convex prod: set CURALINK_JWT_ISSUER")
  (cd frontend && npx convex env set --deployment "$CONVEX_PROD" CURALINK_JWKS "$(cat "$T/jwks")" >/dev/null && echo "  Convex prod: set CURALINK_JWKS (public keys)")
  install -m 600 "$T/admin" "$HOME/.curalink-demo-admin-token" && echo "  Demo admin token saved to ~/.curalink-demo-admin-token (chmod 600)"
  ;;
api-keys)
  for k in ANTHROPIC_API_KEY CARTESIA_API_KEY CARTESIA_VOICE_ID ANTHROPIC_MODEL; do
    grep -E "^$k=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' > "$T/$k" || true
    if [ -s "$T/$k" ]; then
      if [ "$k" = ANTHROPIC_API_KEY ] || [ "$k" = CARTESIA_API_KEY ]; then setv "$k" "$T/$k" --sensitive; else setv "$k" "$T/$k"; fi
    else echo "  (skipped $k: not in .env)"; fi
  done
  ;;
*) echo "usage: $0 core|api-keys"; exit 2 ;;
esac
