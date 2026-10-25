// Browsers authenticate to Convex with a short-lived RS256 token minted by the FastAPI backend for the signed-in
// user (GET /api/v1/convex/token). CURALINK_JWT_ISSUER is the public API origin, e.g. https://api.example.com;
// its JWKS is served at /.well-known/jwks.json. Set it with: npx convex env set CURALINK_JWT_ISSUER https://...
const issuer = process.env.CURALINK_JWT_ISSUER ?? 'http://127.0.0.1:8000'

export default {
  providers: [
    {
      type: 'customJwt',
      applicationID: 'curalink-convex',
      issuer,
      jwks: `${issuer}/.well-known/jwks.json`,
      algorithm: 'RS256',
    },
  ],
}
