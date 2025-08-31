class ContentTypeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith(".hlt.gz") or request.path.endswith(".hlt.br"):
            response["Content-Type"] = "application/json"

        return response
