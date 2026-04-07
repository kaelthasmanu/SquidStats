from typing import TypedDict


class ACLTypeInfo(TypedDict):
    category: str
    slow: bool
    desc: str


ACL_TYPES_INFO: dict[str, ACLTypeInfo] = {
    # Network ACLs
    "src": {
        "category": "network",
        "slow": False,
        "desc": "Source IP address",
    },
    "dst": {
        "category": "network",
        "slow": True,
        "desc": "Destination IP address",
    },
    "localip": {
        "category": "network",
        "slow": False,
        "desc": "Local IP client connected to",
    },
    "arp": {
        "category": "network",
        "slow": False,
        "desc": "MAC address (EUI-48)",
    },
    "eui64": {
        "category": "network",
        "slow": False,
        "desc": "EUI-64 address",
    },
    "client_connection_mark": {
        "category": "network",
        "slow": False,
        "desc": "CONNMARK of connection",
    },
    # Domain ACLs
    "srcdomain": {
        "category": "domain",
        "slow": True,
        "desc": "Reverse DNS lookup of client IP",
    },
    "dstdomain": {
        "category": "domain",
        "slow": False,
        "desc": "Destination domain from URL",
    },
    "srcdom_regex": {
        "category": "domain",
        "slow": True,
        "desc": "Regex match on client name",
    },
    "dstdom_regex": {
        "category": "domain",
        "slow": False,
        "desc": "Regex match on server domain",
    },
    # AS Number ACLs
    "src_as": {
        "category": "network",
        "slow": False,
        "desc": "Source Autonomous System number",
    },
    "dst_as": {
        "category": "network",
        "slow": False,
        "desc": "Destination AS number",
    },
    # Time ACLs
    "time": {
        "category": "time",
        "slow": False,
        "desc": "Time of day and day of week",
    },
    # URL ACLs
    "url_regex": {
        "category": "url",
        "slow": False,
        "desc": "Regex match on full URL",
    },
    "urllogin": {
        "category": "url",
        "slow": False,
        "desc": "Regex match on URL login field",
    },
    "urlpath_regex": {
        "category": "url",
        "slow": False,
        "desc": "Regex match on URL path",
    },
    # Port ACLs
    "port": {
        "category": "port",
        "slow": False,
        "desc": "Destination TCP port",
    },
    "localport": {
        "category": "port",
        "slow": False,
        "desc": "TCP port client connected to",
    },
    "myportname": {
        "category": "port",
        "slow": False,
        "desc": "Port name from *_port directive",
    },
    # Protocol & Method ACLs
    "proto": {
        "category": "protocol",
        "slow": False,
        "desc": "Request protocol (HTTP, FTP, etc)",
    },
    "method": {
        "category": "protocol",
        "slow": False,
        "desc": "HTTP request method",
    },
    "http_status": {
        "category": "protocol",
        "slow": False,
        "desc": "HTTP status code in reply",
    },
    # Header ACLs
    "browser": {
        "category": "content",
        "slow": False,
        "desc": "User-Agent header pattern",
    },
    "referer_regex": {
        "category": "content",
        "slow": False,
        "desc": "Referer header pattern",
    },
    "req_header": {
        "category": "content",
        "slow": False,
        "desc": "Request header pattern",
    },
    "rep_header": {
        "category": "content",
        "slow": False,
        "desc": "Reply header pattern",
    },
    # Authentication ACLs
    "proxy_auth": {
        "category": "auth",
        "slow": True,
        "desc": "Proxy authentication username",
    },
    "proxy_auth_regex": {
        "category": "auth",
        "slow": True,
        "desc": "Proxy auth username regex",
    },
    "ext_user": {
        "category": "auth",
        "slow": True,
        "desc": "External ACL helper username",
    },
    "ext_user_regex": {
        "category": "auth",
        "slow": True,
        "desc": "External ACL helper username regex",
    },
    # MIME Type ACLs
    "req_mime_type": {
        "category": "content",
        "slow": False,
        "desc": "Request MIME type",
    },
    "rep_mime_type": {
        "category": "content",
        "slow": False,
        "desc": "Reply MIME type",
    },
    # Connection ACLs
    "maxconn": {
        "category": "connection",
        "slow": False,
        "desc": "Max TCP connections from IP",
    },
    "max_user_ip": {
        "category": "connection",
        "slow": False,
        "desc": "Max IPs per user",
    },
    # SSL/TLS ACLs
    "ssl_error": {
        "category": "ssl",
        "slow": False,
        "desc": "SSL certificate validation error",
    },
    "server_cert_fingerprint": {
        "category": "ssl",
        "slow": False,
        "desc": "Server cert fingerprint",
    },
    "ssl::server_name": {
        "category": "ssl",
        "slow": False,
        "desc": "TLS SNI server name",
    },
    "ssl::server_name_regex": {
        "category": "ssl",
        "slow": False,
        "desc": "TLS SNI regex match",
    },
    "connections_encrypted": {
        "category": "ssl",
        "slow": False,
        "desc": "All connections over TLS",
    },
    # Advanced ACLs
    "external": {
        "category": "advanced",
        "slow": True,
        "desc": "External ACL helper lookup",
    },
    "random": {
        "category": "advanced",
        "slow": False,
        "desc": "Random probability match",
    },
    "note": {
        "category": "advanced",
        "slow": False,
        "desc": "Transaction annotation",
    },
    "annotate_transaction": {
        "category": "advanced",
        "slow": False,
        "desc": "Add transaction annotation",
    },
    "annotate_client": {
        "category": "advanced",
        "slow": False,
        "desc": "Add client annotation",
    },
    "peername": {
        "category": "advanced",
        "slow": False,
        "desc": "Cache peer name",
    },
    "peername_regex": {
        "category": "advanced",
        "slow": False,
        "desc": "Cache peer name regex",
    },
    "hier_code": {
        "category": "advanced",
        "slow": False,
        "desc": "Squid hierarchy code",
    },
    # Group ACLs
    "any-of": {
        "category": "group",
        "slow": False,
        "desc": "Match any of the ACLs",
    },
    "all-of": {
        "category": "group",
        "slow": False,
        "desc": "Match all of the ACLs",
    },
}

PREDEFINED_ACLS: list[str] = [
    "all",
    "manager",
    "localhost",
    "to_localhost",
    "to_linklocal",
    "CONNECT",
]
