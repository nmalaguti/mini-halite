import threading

import structlog
from decorator import decorator

log = structlog.get_logger()


@decorator
def background_thread(f, daemon=False, *args, **kwargs):
    log.debug("running as background thread", f=f, args=args, kwargs=kwargs)
    threading.Thread(target=f, daemon=daemon, args=args, kwargs=kwargs).start()
    return None
