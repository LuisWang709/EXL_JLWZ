# infra (owner: A4)

Bicep for resource groups `rg-mrf-a-dev` / `rg-mrf-a-demo`: ACR, Container Apps env (api, ui, mcp), Container Apps Jobs (sandbox, scheduled monitoring), Blob, Cosmos DB (free tier), Key Vault, App Insights + Log Analytics, Azure AI Search (free), Azure ML + MLflow, Azure OpenAI.

Planned files: `main.bicep`, `modules/*.bicep`, `params/dev.bicepparam`, `params/demo.bicepparam`.
Container settings must match `.env.example` names.
