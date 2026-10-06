---
status: accepted
---

# LAN-only over plain HTTP, no authentication

The app holds phone-call audio, so exposure matters. It is reached only as `http://transcribe.lan` through the home Caddy proxy; it has no login, no sessions, and no public hostname. The trust boundary is the home network. Uploading from the phone therefore only works at home; the owner accepted that over the cost of running auth.

## Considered options

- **Public `transcribe.menning.cloud` behind Caddy with an in-app login.** Would allow uploads from anywhere and make a PWA share-target possible (which needs HTTPS). Rejected: every route gains an auth concern, and a password on a public URL is the only thing between the internet and call recordings.
- **Tailscale on phone and GPU box.** Cleanest security, but new infrastructure, and a VPN slot on GrapheneOS the owner would rather not spend.
- **LAN-only (chosen).** Zero auth code, zero exposure. Costs: no share-target, uploads only at home.

## Consequences

- Any future HTTPS need (PWA share-target, MCP from outside the LAN) should come via a Let's Encrypt DNS-01 certificate on a name that resolves to the LAN IP, not by exposing the app publicly. Adding auth later means touching every route, so decide deliberately.
- An MCP/HTTP API for Claude Code can be added later without auth as long as it is also LAN-only.
