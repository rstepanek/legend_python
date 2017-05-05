import copy
from thespian.actors import *

from utilities.logger import log

required_keys = ["entity_location"]
class Entity_Loader(Actor):
    def load_entity_file(self): 
        log.INFO("Loading "+  str(self.configs["entity_location"])+"....",self.identity)
        self.parse_states()

    def parse_states(self): 
        with open(self.configs["entity_location"], 'r') as f:
            current_entity = {}
            for line in f:
                if line:
                    current_entity = self.get_kv(current_entity,line)
                else:
                    if current_entity["name"] in self.entities:
                        log.ERROR("Duplicate entity name '"+current_entity["name"]+
                        "'. All entity names must be unique. Only the first entry will be kept.",self.identity)
                    else:
                        self.entities[current_entity["name"]] = copy.deepcopy(current_entity)
                        current_entity = {}
            #needed to commit the last state to memory
            self.entities[current_entity["name"]] = copy.deepcopy(current_entity)
            log.INFO("Successfully loaded entities from "+self.configs["entity_location"],self.identity )
            self.send(self.parent,"TASK_COMPLETE")
                    
    def get_kv(self,dict,line):
        try:
            split_point = line.find("=")
            if split_point > -1:
                key = line[:split_point]
                value = line[split_point+1:]
                dict[key.strip().lower()] = value.strip()
            else:
                log.WARN("INVALID entry in entity file: "+line.strip()+"  Line will be skipped", self.identity)
        except:
            log.WARN("INVALID entry in entity file: "+line.strip()+"  Line will be skipped", self.identity)
        return dict

    def __init__(self):
        self.configs = {}
        self.config_manager = None
        self.identity = "Entity_Loader"
        self.parent = None
        self.entities = {}

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
        elif message == "entity_request":
            self.send(sender,("entity_data",self.entities))
        elif context == "config_manager":
            self.config_manager = message
            self.get_required_keys()
        elif context in required_keys:
            self.update_key(context,message)
