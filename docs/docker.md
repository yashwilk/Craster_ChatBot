# Docker

`docker-compose.yml` brings up: Postgres+pgvector, optional Valkey, the app,
Prometheus (`:9090`), and Grafana (`:3000`, admin/admin default).

```bash
make docker-up
```
