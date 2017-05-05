from thespian.actors import *

from datastructs.processes import Process
from utilities.logger import log
from datastructs.events import Event

class Process_System(Actor):
    def __init__(self):
        self.identity = "Process_System"
        self.parent = None
        self.process_loader = None
        self.state_system = None
        self.entity_system = None
        self.main_event_loop = None
        self.event_system = None
        self.processes = {}
        self.status = "LOADING"
        self.states = []
        self.current_events = set()


    def get_process_loader(self):
        self.send(self.parent, ("actor_request","process_loader"))

    def get_event_system(self):
        self.send(self.parent, ("actor_request","event_system"))

    def get_state_system(self):
        self.send(self.parent, ("actor_request","state_system"))

    def get_entity_system(self):
        self.send(self.parent, ("actor_request","entity_system"))

    def schedule_state_change(self,trigger_event,entity):
        basetime = trigger_event.time
        time_in_state = entity.state.get_time_in_state()
        e = Event({"time": time_in_state+basetime,
                   "event": "StateChange()",
                   "source": entity})
        self.send(self.event_system,("add_event",e))
        self.current_events.discard(trigger_event)
        self.check_events_finished()

    #assign the process object and state to the entity
    #then return the entity to the entity_system
    def handle_state_initialization(self,event):
        #convert name of process into a process object
        #this would make a statically typed language cry
        p = self.processes[event.source.process]
        event.source.process = p
        sname = p.get_initial_state()
        event.source.state = self.states[sname]
        #pass update back to entity system,
        self.send(self.entity_system,("update_entity_state",(event,event.source)))

        #if the state does not have an indefinite duration,
        #then schedule the next state
        if event.source.state.duration.min != -1:
            self.schedule_state_change(event,event.source)
        else:
            self.current_events.discard(event)
        self.check_events_finished()

        #update an entity's state
    def handle_state_change(self,event):
        p = event.source.process
        sname = p.get_next_state(event.source.state)
        if not sname:
            log.ERROR("No valid state transition detected for state: "+
                      str(event.source.state.name) + " in process: " + str(p.name),self.identity)
            self.current_events.discard(event)
            self.check_events_finished()
            return
        speed1 = event.source.state.speed
        speed2 = self.states[sname].speed
        s1 = event.source.state
        s2 = self.states[sname]
        event.source.state = s2
        self.send(self.entity_system,("update_entity_state",(event,event.source)))
        recalc_tta = bool(s1.speed!=s2.speed)#we need to recalc TTA IFF speed or destination change
        #Directives go straight into the event queue and are not tracked
        #as part of processing for the current time step until they are
        #removed from queue
        if getattr(s2,"directives",None):
            #give the main event loop a heads up that we will be activating an additional system
            for d in s2.directives:
                d.time = event.time
                d.source = event.source
                if d.event_type=="GoTo":
                    self.send(self.main_event_loop,("activating_system","geometry_system"))
                    recalc_tta = False
                self.send(self.event_system,("add_event",d))

        if recalc_tta: self.alert_recalc_TTA(event)

        #self.process_directives(event)
        ###GoTo directive gets added to the stack and passed to the geometry system when processed
        ##The geometry system will calculate TTA and schedule an arrival event
        ##in addition, the geometry system tracks the original arrival events so that
        ##they can be deleted from queue as necessary
        #if an entity is in transit and its speed changes, the geometry system needs to remove old event
        #and schedule new event
        #if the state does not have an indefinite duration,
        #then schedule the next state
        if event.source.state.duration.min != -1:
            self.schedule_state_change(event,event.source)
        else:
            self.current_events.discard(event)
        self.check_events_finished()
        #print(self.current_events)

    #a directive is an event that is triggered on state change
    #a single state change can trigger multiple directives
    # def process_directives(self,trigger_event):
    #     s = trigger_event.source.state
    #     if not getattr(s,"directives",None): return
    #     #Directives go straight into the event queue and are not tracked
    #     #as part of processing for the current time step until they are
    #     #removed from queue
    #
    #     #give the main event loop a heads up that we will be activating an additional system
    #     for d in s.directives:
    #         d.time = trigger_event.time
    #         d.source = trigger_event.source
    #         if d.event_type=="GoTo":
    #             self.send(self.main_event_loop,("activating_system","geometry_system"))
    #         self.send(self.event_system,("add_event",d))

    def alert_recalc_TTA(self,event):
        e = Event({"time": event.time,
                   "event": "VelocityChange()",
                   "source": event.source})
        self.send(self.main_event_loop,("activating_system","geometry_system"))
        self.send(self.event_system,("add_event",e))

    def process_event(self,event):
        self.current_events.add(event)
        if event.event_type == "InitializeState":
            self.handle_state_initialization(event)
        elif event.event_type == "StateChange":
            self.handle_state_change(event)


    def get_process_data(self):
        self.send(self.process_loader, "process_request")

    def get_state_data(self):
        self.send(self.state_system, "states_request")

    def print_status(self):
        return str(len(self.processes)) + " Processes"

    def check_events_finished(self):
        if not self.current_events:
            self.send(self.main_event_loop,("finished",self.identity.lower()))

    def validate_processes(self):
        while self.status == "LOADING": pass

        state_names = set([x.name for x in self.states])
        for name,p in self.processes.items():
            for x in p.transitions:
                if x.initial_state:
                    if not x.initial_state in state_names:
                        log.ERROR("Process " + p.name +
                                  " is invalid. Transition from state that does not exist: "
                                  +str(x.initial_state),self.identity)
                if x.final_state:
                    if not x.final_state in state_names:
                        log.ERROR("Process " + p.name +
                                  " is invalid. Transition to state that does not exist: "
                                  +str(x.final_state),self.identity)
        #Now convert states into dict for fast lookup
        sd = {}
        for s in self.states:
            sd[s.name] = s
        self.states = sd

        self.send(self.parent,"TASK_COMPLETE")

    def construct_processes(self,process_data):
        for process in process_data:
            p = Process(process_data[process])
            self.processes[p.name] = p
        log.INFO("Loaded " + self.print_status(),self.identity)
        self.status = "VERIFIYING"


    def receiveMessage(self, message, sender):
        context = None
        #print(message)
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_process_loader()
            self.get_state_system()
            self.get_entity_system()
            self.get_event_system()
        elif context == "event":
            if not self.main_event_loop:
                self.main_event_loop = sender
            self.process_event(message)
        elif context == "process_loader":
            self.process_loader = message
            self.get_process_data()
        elif context == "state_system":
            self.state_system = message
            self.get_state_data()
        elif context == "entity_system":
            self.entity_system = message
        elif context == "event_system":
            self.event_system = message
        elif context == "states":
            self.states = message
            self.validate_processes()#validate processes against states
        elif context == "process_data":
            self.construct_processes(message)