from collections import defaultdict
from datetime import datetime
from models import EventMessage

class EventBus:
    def __init__(self):
        self.s=defaultdict(list)
    def subscribe(self,topic,handler):
        self.s[topic].append(handler)
    def publish(self,event):
        for h in self.s[event.topic]:
            h(event)
    def publish_simple(self,topic,key,payload):
        self.publish(EventMessage(topic,key,payload,datetime.utcnow()))

event_bus=EventBus()
