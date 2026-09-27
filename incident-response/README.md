# Incident responder

Start the responder on the host so it can use the authenticated local Codex CLI:

```powershell
uv run uvicorn responder:app --app-dir incident-response --host 0.0.0.0 --port 8001
```

Grafana reaches it through `http://host.docker.internal:8001/alerts`. Each webhook creates a
redacted, bounded packet under `incidents/` and starts `codex exec` in read-only mode. Only the
known homework 5xx alert, labelled `allow_fix=true`, receives a workspace-write sandbox. The agent
cannot commit, push, deploy, restart Docker, or access credentials.

Query progress with `GET /incidents/{incident_id}`. The final structured answer is stored as
`response.json`. Raw agent events and stderr are retained locally for debugging but ignored by Git;
the bounded evidence packet, structured response, and status are the submission audit trail.
