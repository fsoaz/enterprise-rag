# Enterprise RAG web

The Next.js frontend provides bilingual chat and document administration. In the
default OIDC configuration, browser requests use `/api/backend/...`; the Next.js
server forwards them to FastAPI with a bearer token. Authentication routes and
token refresh run on the web server.

## Getting started

Use Node **22** and npm. Run the commands below from the **repository root**.
First start the backend dependencies using the
[local development guide](../../docs/guides/local-development.md#run-processes-separately).
API and Keycloak must be reachable for sign-in and data access.

For a fresh local configuration:

```bash
cp apps/web/.env.example apps/web/.env.local
npm ci --prefix apps/web
npm run dev --prefix apps/web
```

Keep an existing `.env.local` if already configured. Open `http://localhost:3000`
and use the [seeded sign-in identities](../../docs/guides/local-development.md#development-sign-in).
The [first-upload walkthrough](../../docs/guides/local-development.md#verify-an-upload)
checks the backend and worker as well as the page.

## Configuration

[.env.example](.env.example) is the canonical frontend configuration template.
Server settings include the API origin and OIDC issuer/client configuration.
`NEXT_PUBLIC_*` values enter the client bundle and must never contain secrets.
Restart local development after configuration changes; rebuild deployed client
bundles when changing public values.

Use `localhost` consistently with the seeded issuer and callback configuration.
For optional header-based impersonation and its required API/CORS settings, see
[development authentication](../../docs/guides/local-development.md#header-based-impersonation-bypass).
The full Compose workflow sets web configuration through its build arguments and
service environment, rather than this local file.

## Checks and contribution

```bash
npm run lint --prefix apps/web
npm test --prefix apps/web
npm run test:coverage --prefix apps/web
npm run build --prefix apps/web
```

Run `make typecheck` from the repository root for TypeScript and Python checks.
Frontend coverage thresholds are configured in [vitest.config.ts](vitest.config.ts).
Route visible strings through [i18n.tsx](src/lib/i18n.tsx) with English and Portuguese
translations. Follow the [API generation workflow](../../docs/standards/conventions.md#2-toolchain)
when backend contracts change; generated files must not be edited manually.

Useful source entry points:

- [Chat page](<src/app/(chat)/page.tsx>).
- [Document administration](<src/app/(admin)/admin/page.tsx>).
- [API proxy](<src/app/api/backend/[...path]/route.ts>).
- [Server authentication](src/lib/auth/server.ts).

## Deployment and troubleshooting

The [root Compose workflow](../../README.md#getting-started) builds and runs the web
container with the other services. Cloud deployment is a
[proposed architecture](../../docs/context/architecture.md#172-cloud--aws), not an
implemented release procedure. Use the
[local troubleshooting guide](../../docs/guides/local-development.md#troubleshooting)
for readiness and ingestion failures.
