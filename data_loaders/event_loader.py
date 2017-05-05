import copy
from utilities.runtime_utils import get_col_headers
from thespian.actors import *

from utilities.logger import log

required_keys = ["event_location"]
file_keys = ["time","event","number","location"]
class Event_Loader(Actor):
    def load_entity_file(self): 
        log.INFO("Loading "+  str(self.configs["event_location"])+"....",self.identity)
        self.parse_events()

    #load the events from the file
    def parse_events(self): 
        with open(self.configs["event_location"], 'r') as f:
            cols = get_col_headers(f.readline())
            current_entity = {}
            for rawline in f:
                line = rawline.split('\t')
                current_event = self.get_kv(current_entity,line,cols)
                self.event_data.append(copy.deepcopy(current_event))
            log.INFO("Successfully loaded events from "+self.configs["event_location"],self.identity )
            self.send(self.parent,"TASK_COMPLETE")

    def get_kv(self,dict,line,cols):
        dict = {}
        for key in file_keys:
            try: dict[key] = line[cols[key]]
            except: pass
        return dict

    def __init__(self):
        self.configs = {}
        self.config_manager = None
        self.identity = "Event_Loader"
        self.parent = None
        self.event_data = []

    def get_required_keys(self):
        for key in required_keys:
            self.send(self.config_manager, key+"=")

    def get_configs(self):
        self.send(self.parent, ("actor_request","config_manager"))

    def update_key(self,key,value):
        self.configs[key]=value
        if len(self.configs)==len(required_keys):
            self.load_entity_file()

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_configs()
        elif message == "event_request":
            self.send(sender,("event_data",self.event_data))
        elif context == "config_manager":
            self.config_manager = message
            self.get_required_keys()
        elif context in required_keys:
            self.update_key(context,message)
