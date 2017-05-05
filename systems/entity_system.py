from thespian.actors import *

from datastructs.entities import Entity
from utilities.logger import log
from utilities.random_generator import RANDOM
from datastructs.events import Event

class Entity_System(Actor):
    def __init__(self):
        self.identity = "Entity_System"
        self.parent = None
        self.entity_loader = None
        self.geometry_system = None
        self.main_event_loop = None
        self.event_system = None
        self.entity_types = {}
        self.entity_set = set()
        self.current_id = 0
        self.current_events = set()
        self.geom_proccessing = set()


    def get_entity_loader(self):
        self.send(self.parent, ("actor_request","entity_loader"))

    def get_geometry_system(self):
        self.send(self.parent, ("actor_request","geometry_system"))

    def get_event_system(self):
        self.send(self.parent, ("actor_request","event_system"))

    def get_entity_data(self):
        self.send(self.entity_loader, "entity_request")
        
    def print_status(self):
        return str(len(self.entity_types)) + " Entity types"
        
    def construct_entities_types(self, entity_data):
        #construct dummy entities out of each entity type
        #this ensures that each entity type can be instantiated into a valid entity
        for entity in entity_data:
            self.current_id = self.current_id + 1
            e = Entity(self.current_id, entity_data[entity])
            self.entity_types.update({e.name: e})
        log.INFO("Loaded " + self.print_status(),self.identity)
        self.send(self.parent,"TASK_COMPLETE")


    #this throws a request for entity state initialization into the queue
    def request_initialize_state(self,triggerEvent,entity):
        #print("requesting init of state for " + str(entity))
        e = Event({"time": triggerEvent.time,
                   "event": "InitializeState()",
                   "source": entity})
        self.current_events.add(e)
        self.send(self.event_system,("add_event",e))

    #handles simple spawning at a random location
    def get_spawn_location(self,args):
        ######if an exact coordinate is specified for spawning#####
        if "x" in args and "y" in args:
            if not alt in args: args["alt"] = 0#default altitude to 0
        ####if no location is specified at all#########
        else:
            #throw warning
            log.WARN("No location specified for spawning event with args " + str(args) + " entity will spawn at a random location.")
            args["x"] = RANDOM.next_float(180,-180)
            args["y"] = RANDOM.next_float(90,-90)
            args["alt"] = 0
        return args



    #handles simple spawning at random or pre-defined coords
    def spawn(self,event):
        #log.EVENT(event)
        if not "location" in event.args:
            self.current_id = self.current_id + 1
            event.args = self.get_spawn_location(event.args)
            ent = Entity.create_entity_of_type(self.entity_types[event.args["entity"]],self.current_id,event.args)
            self.entity_set.add(ent)
            self.current_events.discard(event)
            self.request_initialize_state(event,ent)
            self.check_events_finished()
        else:
            #if we need to spawn the entity at a site by tags
            #request a site from the geometry system.
            #The response is handled in spawn_at_site
            self.geom_proccessing.add(event)
            self.send(self.geometry_system,("site_by_tags",event))


    #handles spawning at a site chosen by tags
    def spawn_at_site(self,event,site):
        self.current_id = self.current_id + 1
        current_pos = site.get_pos_in_site()
        (event.args["x"],event.args["y"],event.args["alt"]) = current_pos
        event.args["x"] = current_pos[0]

        ent =  Entity.create_entity_of_type(self.entity_types[event.args["entity"]],self.current_id,event.args)
        self.entity_set.add(ent)
        self.current_events.discard(event)
        self.geom_proccessing.discard(event)
        log.EVENT(event)

        #initialize the entity's state and then check if we're done
        self.request_initialize_state(event,ent)
        self.check_events_finished()

        #discard the older version of the entity, update to the new version
        #this works because entities are compared by UUID, not object values
        #This method is the last to be called when initializing an entity
    def update_entity_state(self,event,entity):
        log.EVENT(event)
        self.entity_set.discard(entity)
        self.entity_set.add(entity)
        self.current_events.discard(event)
        self.check_events_finished()

    def process_event(self,event):
        self.current_events.add(event)
        if event.event_type == "Spawn":
            self.spawn(event)

    def check_events_finished(self):
        if not self.current_events:
            self.send(self.main_event_loop,("finished",self.identity.lower()))

    def receiveMessage(self, message, sender):
        context = None
        #print(message)
        if isinstance(message, tuple):
            context,message = message
        if message == "init":
            self.parent = sender
            self.get_entity_loader()
            self.get_geometry_system()
            self.get_event_system()
        elif context == "event":
            self.main_event_loop = sender
            self.process_event(message)
        elif context == "entity_loader":
            self.entity_loader = message
            self.get_entity_data()
        elif context == "geometry_system":
            self.geometry_system = message
        elif context == "event_system":
            self.event_system = message
        elif context == "entity_data":
            self.construct_entities_types(message)
        elif context == "update_entity_state":
            #message should be a tuple of (event, entity)
            self.update_entity_state(*message)
        elif context == "found_site":
            #message should be a tuple of (event, site)
            self.spawn_at_site(*message)