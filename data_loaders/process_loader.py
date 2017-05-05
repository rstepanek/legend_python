import copy
from thespian.actors import *

from utilities.logger import log

required_keys = ["process_location"]
class Process_Loader(Actor):
    def load_process_file(self): 
        log.INFO("Loading "+  str(self.configs["process_location"])+"....",self.identity)
        self.parse_process()

    def parse_process(self): 
        with open(self.configs["process_location"], 'r') as f:
            current_process = {}
            for line in f:
                if line:
                    current_process = self.get_kv(current_process,line)
                else:
                    if current_process["name"] in self.processes:
                        log.ERROR("Duplicate process name '"+current_process["name"]+
                        "'. All process names must be unique. Only the first entry will be kept.",self.identity)
                    else:
                        self.processes[current_process["name"]] = copy.deepcopy(current_process)
                        current_process = {}
            #needed to commit the last process to memory
            self.processes[current_process["name"]] = copy.deepcopy(current_process)
            log.INFO("Successfully loaded processes from "+self.configs["process_location"],self.identity )
            self.send(self.parent,"TASK_COMPLETE")
                    
    def get_kv(self,dict,line):
        if line[0:2]=="//": return dict

        delims = ["--","=>"]
        line = line.strip()
        if line.lower()[:4] == "name":
            dict["name"] = line[line.find("=")+1:].strip()
            dict["transitions"] = list()
            return dict

        try:
            last_index = 0
            arguments = []
            for i in range(0,len(line)-1):
                if line[i:i+2] in delims:
                    arguments.append(line[last_index:i].strip())
                    last_index = i+2
            if arguments:
                arguments.append(line[last_index:].strip())
                
            #log.INFO(str(arguments),self.identity)
            
            if not dict["transitions"]:
                #log.INFO("Resetting transitions",self.identity)
                #log.INFO(str(dict["transitions"]))
                dict["transitions"] = [arguments]
            else:
                dict["transitions"].append(arguments)
        except:
            log.WARN("INVALID entry in process file: "+line.strip()+"  Line will be skipped", self.identity)
        return dict

    def __init__(self):
        self.configs = {}
        self.config_manager = None
        self.identity = "Process_Loader"
        self.parent = None
        self.processes = {}

    def get_required_keys(self):
        for key in required_keys:
            self.send(self.config_manager, key+"=")

    def get_configs(self):
        self.send(self.parent, ("actor_request","config_manager"))

    def update_key(self,key,value):
        self.configs[key]=value
        if len(self.configs)==len(required_keys):
            self.load_process_file()

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_configs()
        elif message == "process_request":
            self.send(sender,("process_data",self.processes))
        elif context == "config_manager":
            self.config_manager = message
            self.get_required_keys()
        elif context in required_keys:
            self.update_key(context,message)