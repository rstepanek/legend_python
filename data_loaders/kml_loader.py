from fastkml import kml
from thespian.actors import *

from utilities.logger import log

required_keys = ["kml_location"]
class KML_Loader(Actor):
    def load_kml_file(self): 
        log.INFO("Loading "+self.configs["kml_location"]+"....",self.identity)
        self.parse_kml()

    def parse_kml(self): 
        with open(self.configs["kml_location"], 'r') as f:
            k = kml.KML()
            k.from_string(f.read())
            self.kml_features = self.unroll_features(k)
            log.INFO("Successfully loaded kml from "+self.configs["kml_location"],self.identity )
            self.send(self.parent,"TASK_COMPLETE")

    def unroll_features(self,f):
        all_features = []
        try: f.features()
        except: return [f]
        if len(list(f.features())) > 0:
            for t in f.features():
                all_features.extend(self.unroll_features(t))
        return all_features


    def __init__(self):
        self.configs = {}
        self.config_manager = None
        self.identity = "KML_Loader"
        self.parent = None
        self.kml_features = None

    def get_required_keys(self):
        for key in required_keys:
            self.send(self.config_manager, key+"=")

    def get_configs(self):
        self.send(self.parent, ("actor_request","config_manager"))

    def update_key(self,key,value):
        self.configs[key]=value
        if len(self.configs)==len(required_keys):
            self.load_kml_file()

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_configs()
        elif message == "kml_request":
            self.send(sender,("kml_data",self.kml_features))
        elif context == "config_manager":
            self.config_manager = message
            self.get_required_keys()
        elif context in required_keys:
            self.update_key(context,message)
