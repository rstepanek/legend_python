from thespian.actors import *
from utilities import runtime_utils
from utilities.logger import log
import time

#The main event loop, coordinates and synchronizes communication across all the different systems.

#TODO: Make every system inherit from Abstract Base Class "system", use import of ABC "system" to get list of all systems
#TODO:Merge state and process systems, currently state system is a shell, its functionality should be moved into its loader
systems = ['state_system','process_system','geometry_system','entity_system','event_system']
event_sys = {"Spawn":'entity_system',
             "InitializeState":'process_system',
             "StateChange":'process_system',
             "GoTo":'geometry_system',
             "Arrival":'geometry_system',
             "VelocityChange":'geometry_system'}
class Main_Event_Loop(Actor):
    def __init__(self):
        self.identity = "Main_Event_Loop"
        self.parent = None
        self.event_loader = None
        self.event_heap = []
        self.active_systems = set()
        self.status = "INITIALIZING"
        
        #TODO:Loop over dict, if "system" in dict, request system from parent.

    def shutdown_event_loop(self):
        self.send(self.parent,"TASK_COMPLETE")

    def request_next_timestep(self):
        #get the next event from the event system
        self.send(self.event_system,"next_event")

    def update_time_step(self,event):
        runtime_utils.current_time = event.time
        self.get_events_for_current_time()
        self.process_event(event)


    def get_events_for_current_time(self):
        self.send(self.event_system,("time_listener",runtime_utils.current_time))
        self.send(self.event_system,("event_request",runtime_utils.current_time))

    def process_event(self,event):
        #track which systems are processing events and which have finished
        #pass the event to the relevant system
        #print(str(event))
        if event.event_type == "SimStart":
            log.EVENT(event)
            if self.status == "WAITING":
                self.system_finished("")
            return
        if event.event_type == "SimEnd":
            while self.active_systems:
                log.INFO("...Waiting on " +str(self.active_systems)+ " to finish processing.",self.identity)
                for sys in self.active_systems: self.send(sys,"check_status")
                time.sleep(1)
            log.EVENT(event)
            self.send(self.parent,"TASK_COMPLETE")
            return
        try:
            sys = event_sys[event.event_type]
            if not sys in self.active_systems:
                #print(sys + " STARTED at time " +str(event.time))
                self.active_systems.add(sys)
            self.send(getattr(self,sys),('event',event))
        except: log.ERROR("Unrecognized event type: "+str(event.event_type),self.identity)
        #when all systems have finished processing and there are no more events
        #at the current time, then get the next event from the queue, update current time
     #then start over

    def system_finished(self,sys):
        if sys in self.active_systems:
            self.active_systems.discard(sys)
        if not bool(self.active_systems):#if there are no active systems
            #print("requesting next timestep")
            self.request_next_timestep()

    def start_event_loop(self):
        self.request_next_timestep()

    def get_systems(self):
        for sys in systems:
            self.send(self.parent, ("actor_request",sys))

    def check_all_systems_loaded(self):
        all_sys_loaded = True
        for sys in systems:
            if not getattr(self,sys,False):
                all_sys_loaded = False
                break
        if all_sys_loaded:
            self.start_event_loop()

    def register_system(self,sysname,system):
        setattr(self,sysname,system)
        self.check_all_systems_loaded()

        #print(sysname + ": " + str(getattr(self,sysname)))

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message
            #print(context + ": " + str(message))

        if message == "init":
            self.parent = sender
            self.get_systems()
        elif context in systems:
            self.register_system(context,message)#replace with single function to assign data
        elif context == "state_data":
            self.construct_states(message)
        elif context == "next_event":
            if message:
                self.update_time_step(message)
        elif context == "events":
            self.status = "PROCESSING"
            for event in message: self.process_event(event)
            self.status = "WAITING"
        elif context == "activating_system":
            self.active_systems.add(message)
        elif context == "event":
            self.process_event(message)
        elif context == "finished":
            self.system_finished(message)