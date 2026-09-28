# SquidStats Captive Portal Deployment Guide

This guide describes how to deploy the SquidStats captive portal with Squid ACLs, the external ACL helper, LDAP/Active Directory authentication, firewall redirection, and a production-safe network layout.

The feature is designed for controlled networks such as guest Wi-Fi or a lab VLAN. It identifies a session by the client's source IP address. It is not suitable for environments where many independent users share one NAT address unless all of them are intentionally treated as one session.

## 1. Architecture

The request flow is:

1. A client joins the controlled LAN or Wi-Fi network.
2. The firewall either sends HTTP traffic to Squid in intercept mode, or the client is configured to use Squid explicitly.
3. Squid asks the SquidStats external ACL helper whether the source IP has an active session.
4. The helper reads one IP per line from stdin and queries the SquidStats database.
5. The helper returns `OK` for an active session and `ERR` otherwise.
6. Squid redirects unauthenticated HTTP requests to `/portal/login`.
7. The portal authenticates the user against the LDAP/AD configuration stored in SquidStats.
8. SquidStats creates or renews a session for the client's IP.
9. Subsequent requests from that IP are allowed until the session expires or an administrator revokes it.

The relevant project components are:

- `services/captive_portal/session_service.py`: session creation, validation, revocation, and expiration.
- `services/captive_portal/helper/captive_portal_helper.py`: Squid `external_acl_type` protocol.
- `services/ldap/ldap_service.py`: LDAP/AD end-user authentication.
- `services/squid/captive_portal_config_service.py`: managed Squid configuration block.
- `routes/captive_portal_routes.py`: public portal routes.
- `routes/admin/captive_portal.py`: administrator configuration and active sessions.
- `alembic/versions/014_add_captive_portal.py`: database schema.

## 2. Important limitations

### Source-IP sessions

A session is keyed by the source IP address. If ten clients appear to Squid as `192.168.10.20`, authenticating one of them authenticates that address for all ten. Use explicit proxy authentication or a network gateway with per-client identity when this is unacceptable.

### HTTPS interception

A normal Squid `http_access` redirect can redirect HTTP requests. It cannot safely replace arbitrary HTTPS pages with an HTTP login page. Modern browsers also use HSTS, QUIC/HTTP3, certificate validation, and captive portal detection flows that make HTTPS interception fragile.

Recommended production behavior:

- Redirect port 80 to the captive portal.
- Do not blindly redirect port 443 to Squid's HTTP port.
- Allow the portal's own host and required DNS/DHCP services before the captive rule.
- Use a dedicated captive-network gateway or an OS-native captive portal solution if HTTPS interception is a requirement.
- If HTTPS proxying is explicitly configured in clients, Squid can authenticate the `CONNECT` request, but it still cannot show an arbitrary login page inside the encrypted tunnel.

### The helper must run where Squid runs

The generated directive uses the Python executable and helper path visible to the SquidStats process. Squid must be able to execute that path and access the same database.

The repository's current `docker-compose.yml` runs only `squidstats_app`; it does not run Squid. Therefore, when Squid runs on another host or container, do not point Squid at a helper path that exists only inside the Flask container. Install a copy of the helper and the required application modules on the Squid host, or expose a small local helper service with an audited transport. The simplest reliable arrangement is:

- Squid and the helper on the same host.
- The helper and Flask application use the same SQLite file, or both connect to the same MariaDB/PostgreSQL database.
- The helper runs as a restricted user with read-only database access where possible.

## 3. Prerequisites

Prepare the following before enabling the feature:

- Squid 4 or newer with `external_acl_type` support.
- Python 3.12+ recommended, matching the project's supported runtime.
- The SquidStats virtual environment and source tree available to the helper.
- A database migrated to revision `014_add_captive_portal`.
- LDAP or Active Directory connectivity from SquidStats.
- A public URL or internal DNS name for the portal, for example `https://portal.example.net`.
- A firewall/router where the captive client network can be isolated from the management network.
- DNS and DHCP available to unauthenticated clients.
- A TLS certificate if the portal is served over HTTPS.

Do not expose the admin panel directly to the guest network. Put it behind a management VLAN, VPN, reverse proxy access policy, or a separate firewall rule.

## 4. Environment configuration

Copy the example file and set production values:

```sh
cd /opt/SquidStats/app
cp example.env .env
chmod 600 .env
```

At minimum, review these values:

```dotenv
VERSION=2.6
FLASK_DEBUG=False
LISTEN_HOST=127.0.0.1
LISTEN_PORT=5000

SECRET_KEY=replace-with-a-long-random-secret
JWT_SECRET_KEY=replace-with-another-long-random-secret
FIRST_PASSWORD=change-before-first-login

DATABASE_TYPE=SQLITE
DATABASE_STRING_CONNECTION=/opt/SquidStats/app/squidstats.db

SQUID_HOST=127.0.0.1
SQUID_PORT=3128
SQUID_CONFIG_PATH=/etc/squid/squid.conf
ACL_FILES_DIR=/etc/squid/squid.d
```

For a database server, use the project's existing database settings and make sure the helper receives the same environment variables. Never use a database file path that is inside a container but not mounted on the Squid host.

Generate secrets with a password manager or a command such as:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Do not set `FLASK_DEBUG=True` in production. Do not commit `.env`.

## 5. Install and migrate the database

From the project root:

```sh
python3 -m venv /opt/SquidStats/venv
/opt/SquidStats/venv/bin/pip install -r requirements.txt
cd /opt/SquidStats/app
/opt/SquidStats/venv/bin/python manage_db.py upgrade
/opt/SquidStats/venv/bin/python manage_db.py current
```

The current revision must include `014_add_captive_portal`. The application also runs migrations during startup, but running the command explicitly makes deployment failures visible before the service is enabled.

Do not use `manage_db.py init` on a database that has not been verified. `init` stamps the database and does not apply missing schema changes.

## 6. Configure LDAP or Active Directory

Open the administrator panel and configure **LDAP/AD y Grupos**. The following values are required:

- LDAP host and port.
- TLS/SSL choice.
- Authentication type: `SIMPLE` or `NTLM`.
- Service bind DN and password.
- Base DN.

The service account needs enough permission to search users. It does not need administrator privileges. The portal first searches the user and then attempts a bind using the submitted password.

Recommended LDAP settings:

- Use LDAPS or LDAP with StartTLS where supported.
- Use a certificate that the host can validate.
- Restrict the service account to directory search permissions.
- Restrict LDAP access to the SquidStats host with firewall rules.
- Test a real user login before enabling the Squid rule.
- For AD/NTLM, use a username format accepted by the directory, such as `DOMAIN\\user` or `user@domain`.

## 7. Prepare the portal URL and network access

Set the public portal URL in **Admin > Portal Cautivo**, for example:

```text
https://portal.example.net
```

The URL must be an HTTP or HTTPS URL without embedded credentials, query parameters, or fragments. The portal host must be reachable before authentication. Permit at least:

- DNS resolution for the portal hostname.
- TCP 80/443 to the portal reverse proxy.
- TCP 389/636 from SquidStats to LDAP/AD, as required.
- DHCP and gateway services for the client VLAN.
- The Squid listener port from the client VLAN.

If SquidStats and Squid run on separate machines, ensure the portal hostname resolves to the SquidStats application or reverse proxy, not to the Squid listener.

A typical reverse proxy should forward the portal routes to `127.0.0.1:5000` and should not expose `/admin` to the guest network.

## 8. Configure Squid

The generated managed block contains directives equivalent to:

```squid
external_acl_type squidstats_captive_portal ttl=60 negative_ttl=0 %SRC "/opt/SquidStats/venv/bin/python" "/opt/SquidStats/app/services/captive_portal/helper/captive_portal_helper.py"
acl squidstats_captive_portal_valid external squidstats_captive_portal
acl squidstats_captive_portal_domain dstdomain "portal.example.net"
deny_info 302:https://portal.example.net/portal/login?redirect=%s squidstats_captive_portal_valid
http_access allow squidstats_captive_portal_domain
http_access deny !squidstats_captive_portal_valid
```

The exact Python executable and helper path are generated from the running installation. Keep the captive portal block after Squid's basic safety ACL definitions and after the narrow Cache Manager exception, but before general `http_access allow` rules.

Before reloading Squid, validate the configuration:

```sh
sudo squid -k parse -f /etc/squid/squid.conf
sudo squid -k reconfigure
```

On a systemd installation:

```sh
sudo systemctl reload squid
sudo systemctl status squid --no-pager
```

The SquidStats admin action also attempts to reload Squid after applying the configuration. Treat the reload result as mandatory: a saved file without a successful Squid reload is not a working deployment.

### Managed and manual write modes

The Debian service intentionally sets:

```ini
Environment=SQUIDSTATS_SQUID_CONFIG_WRITE_MODE=manual
```

This protects `/etc/squid` from the web process. In this mode the panel shows a preview but does not write `squid.conf`. Copy the generated block into the approved Squid configuration workflow, validate it, and reload Squid as root.

For a controlled installation that explicitly permits panel-managed writes, set:

```ini
SQUIDSTATS_SQUID_CONFIG_WRITE_MODE=managed
```

Only use this when the service account has the exact filesystem permissions required and the host has an audited rollback process. Do not grant broad write access to `/etc`.

## 9. Install the helper on the Squid host

If Squid and SquidStats are on the same host, verify the helper directly:

```sh
sudo -u squid /opt/SquidStats/venv/bin/python \
  /opt/SquidStats/app/services/captive_portal/helper/captive_portal_helper.py
```

The command waits for input. Type an IP and press Enter. It should return `OK` or `ERR`; press `Ctrl-D` to exit.

For a helper on a separate Squid host:

1. Copy the required application package, virtual environment dependencies, and helper to a controlled path.
2. Copy the same `.env` values or use a dedicated environment file.
3. Verify the database is reachable from that host.
4. Set ownership and permissions so only the Squid runtime user can execute or read the helper and database credentials.
5. Use the absolute Python and helper paths in `external_acl_type`.

The helper must not print log messages to stdout. Squid uses stdout for the ACL protocol. Application diagnostics belong on stderr or in the application log.

### Squid in a container and SquidStats on the host

`external_acl_type` executes the helper locally inside the Squid environment; it does not make an HTTP request to Flask running on the host. Therefore, the Squid container must have access to:

- The Python executable and its dependencies.
- The helper code and the SquidStats modules it imports.
- The corresponding `.env` file.
- The same database, or connectivity to the host database.

If the host application generates the configuration that is later copied into the container, set the paths that exist inside the container before regenerating the block:

```dotenv
SQUIDSTATS_HELPER_PYTHON=/usr/bin/python3
SQUIDSTATS_HELPER_PATH=/opt/squidstats-helper/services/captive_portal/helper/captive_portal_helper.py
```

These variables only change the paths written to `squid.conf`; they do not copy files or install dependencies. Mount the code and database at those paths, install the Python dependencies inside the container, and test from there:

```sh
docker exec -it squid /usr/bin/python3 \
  /opt/squidstats-helper/services/captive_portal/helper/captive_portal_helper.py
```

Type an IP followed by Enter and confirm that it returns `OK` or `ERR`. If the helper uses SQLite, the mounted file must be the same database updated by SquidStats; two SQLite copies will make sessions appear to be missing.

## 10. Firewall redirection with iptables

The following is an example for a Linux gateway where:

- `LAN_IF=br-lan` is the guest interface.
- `WAN_IF=eth0` is the upstream interface.
- `LAN_CIDR=192.168.50.0/24` is the guest network.
- Squid listens on `3128` in intercept mode.
- SquidStats is reachable at `portal.example.net` on TCP 443.

Replace every value for your topology. Test from a maintenance session before making rules persistent.

### Enable forwarding

```sh
sudo sysctl -w net.ipv4.ip_forward=1
```

Persist it in `/etc/sysctl.d/99-captive-portal.conf`:

```ini
net.ipv4.ip_forward=1
```

Apply it:

```sh
sudo sysctl --system
```

### Squid intercept listener

The Squid listener must use intercept mode on the port receiving redirected HTTP traffic:

```squid
http_port 3128 intercept
```

Do not use `http_port ... intercept` for clients that are already configured with an explicit proxy unless the deployment intentionally separates those listeners.

### HTTP redirection

```sh
LAN_IF=br-lan
WAN_IF=eth0
LAN_CIDR=192.168.50.0/24
SQUID_PORT=3128

sudo iptables -t nat -A PREROUTING -i "$LAN_IF" -s "$LAN_CIDR" \
  -p tcp --dport 80 -j REDIRECT --to-ports "$SQUID_PORT"
```

Do not redirect traffic destined for the gateway's own portal service. If the portal is hosted on the same machine, use an early ACCEPT rule or route it through a dedicated reverse proxy address. A common layout is to place the portal on a separate host or load balancer so that the client bypasses the interception path naturally.

### Forwarding policy

A restrictive example is:

```sh
sudo iptables -A FORWARD -i "$LAN_IF" -o "$WAN_IF" -s "$LAN_CIDR" \
  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A FORWARD -i "$LAN_IF" -o "$WAN_IF" -s "$LAN_CIDR" \
  -j ACCEPT
```

If the firewall uses a default-deny policy, add explicit rules for DNS, DHCP, the portal, LDAP from the application host, and the Squid listener. Do not allow the guest network to reach the administration interface.

### NAT for authenticated traffic

If this host is also the Internet gateway:

```sh
sudo iptables -t nat -A POSTROUTING -s "$LAN_CIDR" -o "$WAN_IF" -j MASQUERADE
```

Do not combine these examples blindly with an existing firewall manager. `ufw`, firewalld, nftables, Docker, and Kubernetes may install their own chains and ordering rules.

### Do not redirect HTTPS blindly

This rule is intentionally not recommended:

```sh
# Do not add this for a normal HTTP captive portal:
# iptables -t nat -A PREROUTING -i "$LAN_IF" -p tcp --dport 443 \
#   -j REDIRECT --to-ports "$SQUID_PORT"
```

Redirecting TCP 443 to a plain HTTP intercept listener produces TLS errors or unusable CONNECT requests. Use a dedicated captive portal gateway with a proper walled garden if HTTPS onboarding is required.

## 11. nftables alternative

On systems using nftables, the equivalent HTTP redirect is conceptually:

```nft
table ip nat {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        iifname "br-lan" ip saddr 192.168.50.0/24 tcp dport 80 redirect to :3128
    }
}
```

Integrate this with the host's existing nftables ruleset instead of creating a conflicting table. Persist it with the distribution's nftables service.

## 12. Enable the feature

After LDAP, the portal URL, the helper, and Squid have been tested:

1. Open **Admin > Portal Cautivo**.
2. Set the portal title.
3. Set the public portal URL.
4. Set the session duration. Start with 480 minutes or less.
5. Set `ACL TTL` to a low value such as 30-60 seconds.
6. Keep `negative_ttl=0` while troubleshooting so a newly authenticated client is recognized immediately.
7. Enable the portal.
8. Apply the generated Squid configuration according to the managed/manual mode.
9. Validate and reload Squid.
10. Test from an unauthenticated client.

Suggested starting values:

```text
Session TTL: 480 minutes
ACL TTL: 30 seconds
Negative ACL TTL: 0 seconds
```

Lower the session TTL for public guest networks. Lower the ACL TTL when immediate revocation matters. Higher values reduce helper/database load but delay session changes.

## 13. Persistence and service startup

For the Debian package installation:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now squidstats
sudo systemctl status squidstats --no-pager
sudo journalctl -u squidstats -n 100 --no-pager
```

The service runs as `squidstats` with `ProtectSystem=full` and no privilege escalation. This is why the packaged service uses manual Squid configuration mode.

For Docker:

```sh
docker compose up -d --build
docker compose logs -f squidstats
```

Mount the database and `.env` consistently, and ensure the helper's execution environment is available to Squid. A separate Squid container needs its own helper path and shared database connectivity.

## 14. Verification checklist

Run these checks in order:

```sh
# Database schema
/opt/SquidStats/venv/bin/python manage_db.py current

# Application import
/opt/SquidStats/venv/bin/python -c 'import app; print("app import OK")'

# Squid configuration
sudo squid -k parse -f /etc/squid/squid.conf

# SquidStats service
sudo systemctl status squidstats --no-pager

# Squid service
sudo systemctl status squid --no-pager

# Helper protocol
sudo -u squid /opt/SquidStats/venv/bin/python \
  /opt/SquidStats/app/services/captive_portal/helper/captive_portal_helper.py
```

Functional test:

1. Connect a test client to the guest VLAN.
2. Confirm it receives an IP, gateway, and DNS.
3. Browse to an ordinary HTTP URL.
4. Confirm Squid redirects to the portal.
5. Log in with a test LDAP user.
6. Confirm the admin panel lists the IP as active.
7. Browse again and verify access is allowed.
8. Revoke the session from the admin panel.
9. Confirm the next request is challenged after the ACL cache expires.
10. Confirm an HTTPS destination is not being incorrectly redirected.

## 15. Troubleshooting

### The helper returns nothing

- Confirm stdout is not being used by logging.
- Run it manually as the Squid user.
- Verify the helper path and Python executable in `squid.conf`.
- Verify the helper can load `.env` and connect to the database.
- Check file permissions and SELinux/AppArmor policy.

### Squid reports `BH` or helper errors

- Check the `external_acl_type` syntax and quoted paths.
- Ensure the helper returns exactly one `OK` or `ERR` line for every input line.
- Confirm the helper process does not crash on database errors.
- Read Squid cache logs and the SquidStats service journal.

### Login succeeds but access remains blocked

- Confirm the database row was created for the client's real source IP.
- Check whether a reverse proxy or NAT changes the source address.
- Wait for the configured ACL TTL or set negative TTL to zero.
- Verify the helper and Flask application use the same database.
- Verify the portal is enabled in the database configuration.

### The portal redirects in a loop

- Ensure the portal hostname is allowed before `http_access deny !squidstats_captive_portal_valid`.
- Ensure DNS and the portal reverse proxy are reachable without an active session.
- Confirm the portal URL is not itself being redirected to Squid.
- Confirm the public URL points to SquidStats, not to Squid's proxy port.

### HTTPS fails

- Remove any 443-to-3128 REDIRECT rule.
- Confirm the client is not using QUIC/HTTP3 if the network policy requires TCP-only testing.
- Use a supported captive portal gateway for HTTPS onboarding.
- For explicit proxy clients, verify CONNECT policy separately from HTTP redirects.

### Configuration cannot be written

- Check `SQUIDSTATS_SQUID_CONFIG_WRITE_MODE`.
- The Debian service is intentionally `manual`.
- Use the preview, apply the block through the privileged change process, run `squid -k parse`, and reload Squid.

## 16. Security checklist

- Use HTTPS for the portal.
- Keep `FLASK_DEBUG=False`.
- Use unique `SECRET_KEY` and `JWT_SECRET_KEY` values.
- Change the initial admin password immediately.
- Do not expose `/admin` to guest clients.
- Protect `.env`, database files, LDAP credentials, and Squid configuration.
- Restrict the helper and database permissions.
- Use a dedicated LDAP service account with minimal permissions.
- Rate-limit and monitor portal login attempts.
- Keep ACL TTLs short enough for the network's revocation requirements.
- Back up the database and Squid configuration before changes.
- Do not use source-IP sessions where shared NAT identity is unacceptable.
- Review firewall rules after every network topology change.

## 17. Rollback

To disable the feature safely:

1. Disable **Portal Cautivo** in the admin panel, or remove the managed block manually.
2. Validate the Squid configuration.
3. Reload Squid.
4. Remove the HTTP redirect rule from the firewall if it is no longer needed.
5. Keep the database migration in place unless the feature is being permanently removed from the codebase.
6. Revoke active sessions if required.

Never remove a live Squid configuration block without validating the resulting file. Keep the last known-good configuration backup available.
