// Browsers authenticate to Convex with a short-lived RS256 token minted by the FastAPI backend for the signed-in
// user (GET /api/v1/convex/token). Configure per deployment (dev and prod have DIFFERENT keys):
//   CURALINK_JWT_ISSUER  must equal the backend's CONVEX_JWT_ISSUER (a fixed name, e.g. curalink-api-production)
//   CURALINK_JWKS        the backend's PUBLIC key set as a data: URI (no secret; avoids Convex fetching from the API)
//                        — if unset, Convex fetches ${CURALINK_JWT_ISSUER}/api/v1/convex/jwks.json instead.
const issuer = process.env.CURALINK_JWT_ISSUER ?? 'http://127.0.0.1:8000'

export default {
  providers: [
    {
      type: 'customJwt',
      applicationID: 'curalink-convex',
      issuer,
      jwks: process.env.CURALINK_JWKS ?? `${issuer}/api/v1/convex/jwks.json`,
      algorithm: 'RS256',
    },
  ],
}
