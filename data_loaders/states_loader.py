import copy
from thespian.actors import *

from utilities.logger import log

required_keys = ["states_location"]
class States_Loader(Actor):
    def __init__(self):
        self.configs = {}
        self.config_manager = None
        self.identity = "States_Loader"
        self.parent = None
        self.states = {}

    def load_states_file(self): 
        log.INFO("Loading "+  str(self.configs["states_location"])+"....",self.identity)
        self.parse_states()

    def parse_states(self): 
        with open(self.configs["states_location"], 'r') as f:
            current_state = {}
            for line in f:
                #TODO: currently this chokes on consecutive blank lines, fix it to enable any number of blank lines
                if not line.strip():
                    if current_state["name"] in self.states:
                        log.ERROR("Duplicate state name '"+current_state["name"]+
                        "'. All state names must be unique. Only the first entry will be kept.",self.identity)
                        current_state = {}
                    else:
                        self.states[current_state["name"]] = copy.deepcopy(current_state)
                        current_state = {}
                else:
                    current_state = self.get_kv(current_state,line)
            #needed to commit the last state to memory

            self.states[current_state["name"]] = copy.deepcopy(current_state)
            log.INFO("Successfully loaded states from "+self.configs["states_location"],self.identity )
            self.send(self.parent,"TASK_COMPLETE")
                    
    def get_kv(self,dict,line):
        try:
            split_point = line.find("=")
            if split_point > -1:
                key = line[:split_point]
                value = line[split_point+1:]
                dict[key.strip().lower()] = value.strip()
            else:
                log.WARN("INVALID entry in states file: "+line.strip()+"  Line will be skipped", self.identity)
        except:
            log.WARN("INVALID entry in states file: "+line.strip()+"  Line will be skipped", self.identity)
        return dict

    def get_required_keys(self):
        for key in required_keys:
            self.send(self.config_manager, key+"=")

    def get_configs(self):
        self.send(self.parent, ("actor_request","config_manager"))

    def update_key(self,key,value):
        self.configs[key]=value
        if len(self.configs)==len(required_keys):
            self.load_states_file()

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_configs()
        elif message == "state_request":
            self.send(sender,("state_data",self.states))
        elif context == "config_manager":
            self.config_manager = message
            self.get_required_keys()
        elif context in required_keys:
            self.update_key(context,message)
