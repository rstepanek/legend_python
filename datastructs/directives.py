from datastructs.events import Event

#A directive is an event that is scheduled as a result of a state change
#Directives are the primary way that an entity interacts with the world
#subclassing from Event allows the directive to be scheduled in the queue
class Directive(Event):
    def __init__(self,data):
        Event.__init__(self,data)
