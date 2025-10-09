Firewall (Lightweight in-process)

Overview
--------
This project now includes a small, in-process "firewall" middleware implemented at `app/security/firewall.py` and initialized during app creation. It's a simple, low-overhead IP rate limiter and temporary ban list intended to: 

- Defend against simple abusive clients and scripted DoS attempts.
- Be cheap in CPU and memory (pure in-memory dicts, per-process).
- Fail-open where needed so it never crashes the app.

Important limitations
---------------------
- This is an in-process, per-Python-process firewall. When the app is run with multiple worker processes (gunicorn/Waitress/etc.) each process keeps its own counters and bans. For robust DDoS protection use a centralized store (Redis) or a network-level service (nginx, Cloudflare, AWS Shield).
- It is not a replacement for a production-grade WAF or DDoS mitigation service.

How it works (summary)
----------------------
- On every HTTP request the middleware updates a per-IP counter within a sliding time window (configurable). If the counter exceeds the configured limit, the IP is temporarily banned.
- Bans are time-limited and removed lazily when expired.
- There are whitelist and blacklist config options to permanently allow or block specific IPs.
- Socket.IO connect events are also checked and rejected if the IP is currently banned.

Configuration keys
------------------
Set these keys in instance `config.py` or via environment variables passed to Flask.
- FIREWALL_ENABLED (bool): Enable/disable the firewall. Default: True
- FIREWALL_RATE_LIMIT (int): Allowed requests per window. Default: 60
- FIREWALL_WINDOW (int): Window size in seconds. Default: 60
- FIREWALL_BAN_TIME (int): Seconds to ban an IP after exceeding the rate limit. Default: 300
- FIREWALL_WHITELIST (list): IPs to always allow (e.g. internal proxies)
- FIREWALL_BLACKLIST (list): IPs to always block
- FIREWALL_TRUSTED_PROXIES (list): If you sit behind trusted proxies, add their IPs and the firewall will try to honor X-Forwarded-For. See notes below.

Deploying for low server load (recommendations)
----------------------------------------------
1. Prefer upstream protection: put nginx, HAProxy, or a cloud CDN/WAF (Cloudflare, Fastly) in front of your app. This stops most malicious traffic before it reaches Python and is the most effective way to mitigate DDoS with minimal server load.

2. If you cannot use an upstream service, consider using a centralized rate limiter (Redis) and a shared ban list so multiple processes/servers coordinate. This project documents only in-process logic; adding Redis is a recommended follow-up.

3. Tune limits conservatively. Lower the `FIREWALL_RATE_LIMIT` and `FIREWALL_WINDOW` to match expected client behavior. For example, APIs used by mobile apps commonly use 30 req/min or less.

4. Use a dedicated proxy to terminate slow/large requests and offload TLS. Python should not be the first line of defense for large-scale attacks.

Operation and monitoring
------------------------
- The firewall exposes no admin UI. You can inspect `app.firewall.counters` and `app.firewall.banned` from Python shell or integrate a small diagnostic endpoint if needed.
- Logs are written via `app.logger` when an IP is banned or if the firewall fails to initialize.

Next steps (optional improvements)
----------------------------------
- Move counters and ban lists to Redis for cross-process coordination.
- Add a small administrative endpoint to view and modify the ban list.
- Integrate with existing WAF products or upstream rate-limiting features in nginx.

Security note
-------------
This is a defensive, best-effort component. For real operational DDoS protection use a multi-layer strategy: network/CDN, edge WAF, reverse proxy rate-limiting, then application-level protection.
