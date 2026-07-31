"""
validator.py
------------
Validates ExecutionRequest.
"""

from typing import Any, Dict

class ValidationError(Exception):
    pass

class RequestValidator:
    def validate_request(self, request_dict: Dict[str, Any]) -> None:
        """Validate the incoming execution request."""
        required_fields = [
            "transaction_id",
            "account_id",
            "customer_id",
            "verdict",
            "confidence",
            "risk_score",
            "tier"
        ]
        
        for field in required_fields:
            if field not in request_dict:
                raise ValidationError(f"Missing required field: {field}")
                
        if not request_dict["transaction_id"]:
            raise ValidationError("transaction_id cannot be empty")
            
    def validate(self, request) -> None:
        """Helper for dataclass/object inputs."""
        if not hasattr(request, "transaction_id") or not request.transaction_id:
            raise ValidationError("transaction_id cannot be empty")


def validate_request(request) -> None:
    validator = RequestValidator()
    if isinstance(request, dict):
        validator.validate_request(request)
    else:
        validator.validate(request)
