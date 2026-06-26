import hashlib

class IdempotencyStore:
    def __init__(self):
        self._cache={}

class IdempotencyService:
    def __init__(self, store):
        self.store=store

    def check(self, request):
        key=hashlib.sha256(
            f"{request.transaction_id}:{request.verdict.value}".encode()
        ).hexdigest()
        if key in self.store._cache:
            return True,self.store._cache[key],key
        return False,None,key

    def store_result(self,key,result):
        self.store._cache[key]=result

store=IdempotencyStore()
idempotency=IdempotencyService(store)
