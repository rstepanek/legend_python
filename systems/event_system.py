import utilities.runtime_utils as runtime_utils
from datastructs.events import Event
from importlib import reload
from utilities.logger import log

from thespian.actors import *


SIM_START = Event({"time":1,"event":"SimStart()"})
REMOVED = '<removed-event>'      # placeholder for a removed event
class Event_System(Actor):
    def __init__(self):
        self.identity = "Event_System"
        self.parent = None
        self.event_loader = None
        self.entry_finder = {} # mapping of events to entries in the heap
        self.time_listener = None#used to forward events at a scheduled time
        self.event_dict = {}#dict of time: set(events)

    def get_event_loader(self):
        self.send(self.parent, ("actor_request","event_loader"))

    def get_event_data(self):
        self.send(self.event_loader, "event_request")
        
    def print_status(self):
        return str(len(self.event_dict)) + " Events"
        #return str(len(self.event_heap)) + " Events"

    def remove_event(self, event):
        self.event_dict[event.time].discard(event)

    def get_all_events_at_time(self, time):
        return list(self.event_dict[time])

    def remove_empty_events(self):
        lowest = sorted(self.event_dict.keys())[0]
        del(self.event_dict[lowest])

    def pop_event(self):
        return self.pop_event_at_time(sorted(self.event_dict.keys())[0])

    def pop_event_at_time(self, time):
        if not self.event_dict[time]: return
        return self.event_dict[time].pop()

    #add event to event dict
    def add_event(self, event):
        if event.time > runtime_utils.end_time: return
        #print("Added event " + str(event))
        if self.time_listener:
            if self.time_listener[0] == event.time:
                self.send(self.time_listener[-1],("event",event))
                return
        if not event.time in self.event_dict:
            self.event_dict[event.time] = set()
        self.event_dict[event.time].add(event)

    def initialize_queue(self,event_data):
        #Add SIMSTART
        self.add_event(SIM_START)

        #LOAD ALL user defined events
        #print(event_data)
        for event in event_data:
            for i in range(0,int(event["number"])):
                self.add_event(Event(event))
        
        try: runtime_utils.end_time
        except: reload(runtime_utils)

        #ADD SIM_END ... no events will be processed after SIM_END
        SIM_END = Event({"time": runtime_utils.end_time-runtime_utils.start_time, "event": "SimEnd()"})
        self.add_event(SIM_END)
        log.INFO("Loaded " + self.print_status(),self.identity)
        self.send(self.parent,"TASK_COMPLETE")

    def receiveMessage(self, message, sender):
        context = None
        #print(message)
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_event_loader()
        elif message == "next_event":
            self.send(sender, ("next_event",self.pop_event()))
        elif context == "add_event":
            #self.add_event(message)
            self.add_event(message)
        elif context == "remove_event":
            self.remove_event(message)
        elif context == "event_request":
            self.send(sender, ("events",self.get_all_events_at_time(message)))
            self.remove_empty_events()
        elif context == "time_listener":
            self.time_listener = (message,sender)
        elif context == "event_loader":
            self.event_loader = message
            self.get_event_data()
        elif context == "event_data":
            self.initialize_queue(message)