"""ssl_compat.py — Compatibility shim for the ported V1 modules.

The original V1 environment sat behind a TLS-intercepting proxy, so it shipped
an `ssl_compat.enable()` that pointed requests/urllib at the OS trust store.
That module did not survive the port (same as config/database/data_fetcher), so
`import ssl_compat` raised ModuleNotFoundError and fundamentals_fetcher.py could
not run at all.

Most machines do NOT need any of this — Python's bundled certifi bundle works
fine. So enable() is a no-op by default and only attempts the OS trust store
when it is actually available and requested.

If you are behind a corporate/AV TLS interceptor and see SSLCertVerificationError,
either:
  * pip install pip-system-certs      (transparently uses the Windows store), or
  * set PSX_SSL_TRUSTSTORE=1          (uses Python 3.10+ truststore if present)

Never disable verification to make an error go away — that would silently expose
every request this app makes.
"""

import logging
import os

log = logging.getLogger("ssl_compat")

_ENABLED = False


def enable():
    """Point HTTPS at the OS trust store when asked and available. No-op otherwise."""
    global _ENABLED
    if _ENABLED:
        return True
    if os.environ.get("PSX_SSL_TRUSTSTORE", "").strip() in ("1", "true", "yes"):
        try:
            import truststore
            truststore.inject_into_ssl()
            _ENABLED = True
            log.info("ssl_compat: using OS trust store via truststore")
            return True
        except ImportError:
            log.warning("ssl_compat: PSX_SSL_TRUSTSTORE set but `truststore` is "
                        "not installed — run `pip install truststore`. "
                        "Falling back to the default certifi bundle.")
        except Exception as e:
            log.warning("ssl_compat: truststore injection failed (%s) — "
                        "falling back to the default certifi bundle.", e)
    _ENABLED = True
    return False


def status():
    return {"enabled": _ENABLED,
            "truststore_requested": os.environ.get("PSX_SSL_TRUSTSTORE", ""),
            "note": "Default certifi verification is active unless the OS trust "
                    "store was successfully injected. Verification is never "
                    "disabled by this module."}
