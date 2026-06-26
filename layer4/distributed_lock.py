class InMemoryLockStore:
    def __init__(self):
        self._locks=set()

class DistributedLockService:
    def __init__(self,store):
        self.store=store
    def acquire(self,execution_key,execution_id):
        if execution_key in self.store._locks:
            raise RuntimeError("lock exists")
        self.store._locks.add(execution_key)
    def release(self,execution_key,execution_id):
        self.store._locks.discard(execution_key)

store=InMemoryLockStore()
distributed_lock=DistributedLockService(store)
