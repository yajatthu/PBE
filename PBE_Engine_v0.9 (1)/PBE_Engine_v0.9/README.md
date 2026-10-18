# Polymorphic Business Engine v0.9

PBE v0.9 preserves the existing Observation-to-Code engine, Capability Replacement Desk, Composio tool authorization/execution, OpenRouter planning, native capability proposal pipeline, workspace authentication, tenant isolation, audit history, UOL, module registry, and safety checks. It adds the process visibility specified for the PBE foundation that DOOM will use: persistent workflow timelines, execution history, connected-account access status, expected duration, and an OpenRouter final consistency review when all planned external actions have success records.

## v0.9 additions

- Top-right header displays **v0.9 only**; investor/demo labels have been removed from the application header.
- Persistent workflow timeline events are stored in PostgreSQL and scoped to tenant/workspace/plan.
- Workflow history lists saved plans and lets the user inspect a workflow timeline.
- Expected duration and expected completion timestamp are shown as estimates, not guarantees.
- Connected-account panel shows the provider-reported account identity/status and scopes/permissions if Composio returns them. It does not invent missing permission details.
- After all planned Composio actions succeed, PBE asks OpenRouter to review the execution trace. A `PASS` marks the workflow actions complete; it does not independently prove the external application state or replace human acceptance testing.
- Access checks, explicit per-action confirmation, tool schema revalidation, and duplicate-execution protection remain in place.
- New database migration is additive and creates `workflow_timeline_events`; existing tables are not dropped.

## API keys and configuration needed

Only **two provider API keys** are required for the core integrations:
1. `COMPOSIO_API_KEY` — required for Composio authorization links, connected-account listing, tool discovery, and tool execution.
2. `OPENROUTER_API_KEY` — required for model-assisted planning and final workflow review.

The following are configuration values or infrastructure credentials, not additional AI-provider API keys:
- `COMPOSIO_AUTH_CONFIGS` — map each supported toolkit slug to the auth-config ID from your own Composio project (for example `canva`, `notion`, `gmail`). These IDs are required to create authorization links for each service you want to connect.
- `DATABASE_URL` — PostgreSQL connection string.
- `REDIS_URL` — Redis connection string for worker-related functions.
- `JWT_SECRET` — long, random, private secret for signing PBE sessions; replace the development placeholder.
- `PBE_APP_URL` — the actual deployed PBE URL, used in OAuth callbacks/links and OpenRouter request metadata.
- `PBE_ALLOWED_ORIGINS` — allowed browser origins if frontend and API are hosted separately.
- `OPENROUTER_PRIMARY_MODEL` and optional `OPENROUTER_FALLBACK_MODELS` — model routing configuration; model names are not API keys.
- `COMPOSIO_WEBHOOK_SECRET` and `COMPOSIO_WEBHOOK_URL` — optional if you configure provider webhooks; the webhook secret is a signing secret, not a provider API key.
- `PBE_SANDBOX_ENABLED` — optional and only enable when the configured sandbox runtime is available and reviewed.

Never paste keys into frontend JavaScript, commit them to Git, or share them in screenshots. Put them in the server environment / private `.env` file.

## Preserved v0.7 engine baseline — Capability Replacement Prototype

PBE preserves the existing PBE concept and engine pipeline. It adds a simpler, outcome-first experience for discovering the capability a business actually needs, using authorized Composio actions where useful, and proposing PBE-native modules that can reduce dependency on external SaaS over time.

**This is an investor-demo prototype, not a claim that PBE already replaces all of Canva, Figma, Notion, or any other SaaS product.** It demonstrates the intended workflow and supports explicit Composio tool execution when the provider configuration, connected account, available tool, inputs, and permissions all line up.

## What changed in v0.7

- Added the **Capability Replacement Desk**: users describe an outcome in plain language rather than configure a complex automation.
- Added a service picker for Canva, Figma, Notion, Google Docs, Google Sheets, Slack, and Gmail. The list is deliberately small and easy to understand; Composio may support many more toolkits.
- Added server-side mapping from friendly service names to Composio auth-config IDs, so users do not need to handle those IDs during normal use.
- Added Composio tool discovery and a capability planner that uses OpenRouter when configured. The model receives the current tool catalog and must select exact discovered tool slugs; unknown slugs are removed.
- The plan separates **actions in connected SaaS tools** from **PBE-native capability proposals**. Owners can submit a selected proposal into the existing Observation-to-Code pipeline, which may generate and validate a staged module. A staged module is not live-deployed and is not yet proof of SaaS replacement.
- Added explicit plan approval and per-action confirmation before a connected action executes. Connected account ownership, current tool schema, required inputs, and extra input keys are checked before execution.
- Added workspace-scoped PostgreSQL persistence for plans and execution records.
- Added an honest no-OpenRouter fallback: it creates a template plan and explicitly says it is not AI-generated.
- Preserved the existing Observation-to-Code pipeline, Cognitive Arbiter, Engineer Agent, validation boundary, module registry, authentication, tenant/workspace isolation, audit trail, UOL, PostgreSQL/pgvector, Redis/Celery, and existing demo routes.

## The intended product loop

1. **Connect:** the user authorizes their own service through Composio and chooses the permissions offered by that provider.
2. **Describe:** the user explains the outcome they want and selects relevant services.
3. **Understand:** OpenRouter analyzes the goal alongside the available Composio tool catalog and current PBE modules.
4. **Act:** the user approves the plan and separately confirms each supported tool action. PBE records the result.
5. **Build:** after approving the plan, the owner can submit a native capability proposal into PBE's existing Observation-to-Code pipeline. The pipeline records a UOL event, runs the Cognitive Arbiter and Engineer Agent, validates the module, and stages it if checks pass.
6. **Prove before cancelling:** test the native capability against agreed requirements, verify data export/migration, permissions, reliability, and actual cost. A subscription should only be cancelled after the replacement demonstrably covers the user's needed workflow.

PBE is not designed to bypass subscriptions, licensing, access controls, or provider restrictions. The disruptive proposition is to build/orchestrate the business capability the user needs, so the user can stop paying for an external product when PBE genuinely replaces the required function—not to unlock paid features without authorization.

## Setup

1. Copy `.env.example` to `.env` and use a strong unique `JWT_SECRET`.
2. Set `DATABASE_URL`, `REDIS_URL`, `OPENROUTER_API_KEY`, and `COMPOSIO_API_KEY`.
3. Add the Composio auth-config IDs once in `COMPOSIO_AUTH_CONFIGS`. Example:

   ```env
   COMPOSIO_AUTH_CONFIGS={"canva":"ac_your_canva_auth_config","figma":"ac_your_figma_auth_config","notion":"ac_your_notion_auth_config","google_docs":"ac_your_google_docs_auth_config","google_sheets":"ac_your_google_sheets_auth_config","slack":"ac_your_slack_auth_config","gmail":"ac_your_gmail_auth_config"}
   ```

   These are administrator setup values, not end-user credentials. Use the IDs from your own Composio project. Do not commit `.env` or real API keys.
4. Initialize PostgreSQL with `infra/postgres/init.sql`, or set `PBE_AUTO_INIT_SCHEMA=true` where the database role has the necessary privileges. The schema includes additive v0.7 plan/execution tables.
5. Install `requirements.txt` and start the API with `uvicorn pbe.main:app --host 0.0.0.0 --port 8000`.
6. Log in, connect the service, authorize the account, select it for a goal, and create a plan. A plan must be approved before tool actions can run; each action then requires a separate confirmation.

## Composio API notes

The client uses the Composio v3.1 base URL by default. Tool discovery uses `GET /tools` with `toolkit_slug`, `search`, and `toolkit_versions=latest`; tool metadata is fetched with `version=latest`; execution uses `POST /tools/execute/{tool_slug}` with `user_id`, `connected_account_id`, `version`, and `arguments`. These paths and fields follow Composio's current reference documentation ([tool catalog](https://docs.composio.dev/reference/api-reference/tools/getTools), [execute tool](https://docs.composio.dev/reference/api-reference/tools/postToolsExecuteByToolSlug), [connected accounts](https://docs.composio.dev/reference/api-reference/connected-accounts)). Provider API behavior and auth-link response shapes can evolve, so verify against the version enabled in your Composio project before an investor demo. The current UI attempts to open the returned authorization URL; if the provider response differs, adapt the response normalizer.

## Run and validate

```bash
python -m compileall -q pbe celery_app.py tests
node --check pbe/static/app.js
pytest -q
```

The v0.7 validation report records the checks actually run. These are source-level/unit checks, not proof of a live Composio or OpenRouter integration.

## Remaining limitations

- No live Composio account or OpenRouter request was available during local validation. Real OAuth, tool discovery, tool execution, rate limits, scopes, and provider-specific payloads still require a live test.
- Some SaaS functions are proprietary, unavailable through public APIs, or dependent on paid plans. PBE cannot promise a complete replacement before feature-by-feature testing.
- The capability planner can submit a proposal into the existing Observation-to-Code pipeline; it does not silently hot-deploy generated code. With OpenRouter disabled, the pipeline intentionally emits a context-aware intake scaffold rather than pretending it has built a complete replacement. The existing registry approval is not the same as production runtime deployment.
- A real SaaS replacement needs implementation, migration/export, acceptance tests, security review, monitoring, backups, and a rollback path.
- Per-process rate limiting, full MFA/session revocation, complete hostile-code isolation, and production deployment automation remain outside this prototype pass.


## v0.7 reliability fixes

- Normalizes common Composio tool/account response envelopes and rejects malformed tool slugs.
- Validates requested service names, normalizes discovered tool definitions, and only keeps model-proposed actions whose exact slug was discovered for a selected service.
- Validates proposed arguments against fresh tool metadata before execution.
- Checks connected-account ownership where Composio returns it, and checks account/service matching when metadata is available.
- Prevents re-running an action index after a successful/recorded execution from the same plan. This is conservative duplicate protection, not a provider-wide exactly-once guarantee.
- Adds connected-tool execution audit events, integration readiness details in `/health`, restores saved plans in the dashboard, and fixes auth popups being blocked by browsers.
- Keeps generated native capabilities as PROPOSED until PBE's existing Observation-to-Code pipeline has actually generated and validated a module. The prototype still does not hot-deploy generated code.

## Verification limits

Automated local checks validate syntax, helper contracts, and safety guards. They do not prove live Composio/OpenRouter API compatibility or end-to-end execution; those require configured credentials and a running PostgreSQL/Redis environment.
