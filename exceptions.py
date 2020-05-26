class BadRequestError(Exception):
    pass

class UnauthorisedError(Exception):
    pass

class ForbiddenError(Exception):
    pass

class NotFoundError(Exception):
    pass

status_code_exceptions = {
    400: BadRequestError,
    401: UnauthorisedError,
    403: ForbiddenError,
    404: NotFoundError
}