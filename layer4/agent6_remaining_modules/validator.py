from models import ExecutionRequest

class ValidationError(Exception):
    pass

class RequestValidator:
    def validate(self, request: ExecutionRequest):
        if not request.transaction_id:
            raise ValidationError("transaction_id required")

validator = RequestValidator()

def validate_request(request: ExecutionRequest):
    validator.validate(request)
