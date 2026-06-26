from dataclasses import dataclass

@dataclass
class RetryResult:
    value: object
    attempts:int

class RetryManager:
    def run(self,fn,*a,**kw):
        return RetryResult(fn(*a,**kw),1)

retry_manager=RetryManager()

class RetryExhausted(Exception):
    pass
