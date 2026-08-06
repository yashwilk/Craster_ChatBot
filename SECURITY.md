# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it privately rather than opening a public GitHub issue.

**Contact:** yashwil.k@gmail.com

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept code or requests, if applicable)
- The affected version/commit

We'll acknowledge your report as soon as possible and follow up once the issue has been triaged.

## Scope

This policy covers the application code in this repository (API, agent, tools, infrastructure config). It does not cover third-party services this project integrates with (OpenAI, Acumatica, Langfuse, etc.) — please report issues in those services directly to their respective maintainers.

## Handling secrets

- Never commit real credentials, API keys, or `.env.*` files other than `.env.example` (enforced by `.gitignore` and the CI `detect-secrets` scan).
- If you find committed secrets, report them the same way as above so they can be rotated promptly.
