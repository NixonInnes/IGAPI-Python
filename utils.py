import logging

def req_auth(func):
    logger = logging.getLogger(func.__name__)
    def wrapper(self, *args, **kwargs):
        if not self.authd:
            self.msg_out(f'You need to be logged in to use this command')
            logger.warning(f'{func.__name__}: Attempted run without authentication')
            return
        return func(self, *args, **kwargs)
    return wrapper