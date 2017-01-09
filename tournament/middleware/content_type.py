class ContentTypeMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.

        response = self.get_response(request)

        if request.path.endswith('.hlt.gz'):
            response._headers['content-type'] = ('Content-Type', 'application/json')

        # Code to be executed for each request/response after
        # the view is called.

        return response
