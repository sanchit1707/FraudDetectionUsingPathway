class CircuitBreakerOpen(Exception):
    pass

class Circuit:
    def call(self,fn):
        return fn()

class CircuitRegistry:
    def __init__(self):
        self.c={}
    def get(self,name):
        self.c.setdefault(name,Circuit())
        return self.c[name]

circuit_registry=CircuitRegistry()
