from thespian.actors import *

from utilities.logger import log
from utilities.random_generator import RANDOM

valid_config_keys = ["start_date","end_date","out_file","warn_file",
"error_file","event_file","kml_location","states_location",
"process_location","entity_location","event_location","random_seed",
"server_uri"]

class Config_Loader(Actor):
    def send_time(self):
        self.send(self.parent, ("start_time",self.configs["start_date"]))
        self.send(self.parent, ("end_time",self.configs["end_date"]))

    def load_configs(self,file_loc):
        with open(file_loc,'r') as f:
            for line in f:
                try:
                    arg = line.split("=")[0]
                    param = "=".join(line.split("=")[1:])
                    if arg.lower().strip() in valid_config_keys:
                        self.configs[arg.lower().strip()]=param.strip()
                    else:
                        pass
                        #log.WARN("Skipping Invalid key: {}".format(arg),self.identity)#throw invalid key error
                except:
                    pass
        self.configure_logger()
        self.set_random_seed()
        log.INFO("Loaded configs:\n" + str(self.configs),self.identity)
        self.send_time()
        self.send(self.parent,"TASK_COMPLETE")

    def receiveMessage(self, message, sender):
        if message=="init":
            self.parent = sender
            self.load_configs("input_files/Sim.config")
        elif message[-1]=="=":
            try: self.handle_key_request(sender,message[:-1])
            except:
                log.ERROR("Bad key request from {0}  Key not specified in configs: {1} ".format(
                            str(sender),message[:-1]),self.identity)

    def handle_key_request(self,sender,key):
        self.send(sender, (key,self.configs[key.lower().strip()]))

    def set_random_seed(self):
        if "random_seed" in self.configs:
            RANDOM.set_seed(int(self.configs["random_seed"]))

    def configure_logger(self):
        log.set_error_file(self.configs["error_file"])
        log.set_warn_file(self.configs["warn_file"])
        log.set_info_file(self.configs["out_file"])
        log.set_event_file(self.configs["event_file"])
        log.server_uri = self.configs["server_uri"]
        
    def __init__(self):
        self.configs = {}
        self.parent = None
        self.identity = "config_manager"
