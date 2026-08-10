import socket
import ssl
from datetime import datetime, timedelta, timezone
CONNECTIVITY_HOST = "www.googleapis.com"
CONNECTIVITY_TIMEOUT_SECONDS = 2.0


def is_online():
    """A quick TLS handshake — cheaper and more honest than a full API call."""
    try:
        context=ssl.create_default_context()
        with socket.create_connection((CONNECTIVITY_HOST,443),timeout=CONNECTIVITY_TIMEOUT_SECONDS) as raw_sockets:
            with context.wrap_socket(raw_sockets, server_hostname=CONNECTIVITY_HOST):
                return True
    except OSError:
        return False
    
def is_overdue(last_success_iso, interval_minutes):
    """No recorded success means overdue — that's how a fresh or failed folder retries."""
    if not last_success_iso:
        return True
    try:
        last_success = datetime.fromisoformat(last_success_iso)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last_success>=timedelta(minutes=interval_minutes)