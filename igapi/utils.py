import logging

def req_auth(func):
    logger = logging.getLogger(func.__name__)
    def wrapper(self, *args, **kwargs):
        if not self.authd:
            logger.warning('Attempted to run without authentication')
            return
        return func(self, *args, **kwargs)
    return wrapper