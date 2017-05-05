from collections import OrderedDict
from data_loaders.config_loader import Config_Loader
from data_loaders.kml_loader import KML_Loader
from data_loaders.process_loader import Process_Loader
from data_loaders.event_loader import Event_Loader
from data_loaders.states_loader import States_Loader
from data_loaders.entity_loader import Entity_Loader
from systems.entity_system import Entity_System
from systems.event_system import Event_System
from systems.geometry_system import Geometry_System
from systems.state_system import State_System
from systems.main_event_loop import Main_Event_Loop
from systems.process_system import Process_System
from system_configs.SystemLevelConfigs import asys
from thespian.actors import *

from utilities import runtime_utils
from utilities.logger import log

from dateutil import parser


phase_map = OrderedDict({"Initializing": {"config_manager":Config_Loader},
                          "Loading":{"kml_loader":KML_Loader,
                                    "states_loader":States_Loader,
                                    "process_loader":Process_Loader,
                                    "entity_loader":Entity_Loader,
                                    "event_loader":Event_Loader},
                          "Verifying":{"geometry_system":Geometry_System,
                                        "state_system":State_System,
                                        "process_system":Process_System,
                                        "entity_system":Entity_System,
                                        "event_system":Event_System},
                           "Executing":{"main_event_loop":Main_Event_Loop}})

class Main_Actor(Actor):
    def execute_phase(self):
        phase_dict = phase_map[self.phase]
        for act in phase_dict:
            self.actors[act] = self.createActor(phase_dict[act])
            self.send(self.actors[act], "init")
            self.active_phase_actors.append(self.actors[act])

    def __init__(self):
        self.phase = None
        self.actors = {}
        self.active_phase_actors = []
        self.identity = "SIM_DRIVER"
        self.configs = None
        self.start_date = None
        self.end_date = None
        runtime_utils.current_time = 0#always start at SimTime=0

    def init_start_time(self):
        runtime_utils.start_time = runtime_utils.unix_time_millis(parser.parse(self.start_date))

    def init_end_time(self):
        runtime_utils.end_time = runtime_utils.unix_time_millis(parser.parse(self.end_date))
        #print("END TIME " + str(runtime_utils.end_time))

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message
        
        if context == None:
            if isinstance(message,str):
                if message == "config_request":
                    log.INFO("Received config request from " + str(sender),self.identity)
                    self.send(sender,("config_manager",self.actors["config_manager"]))
                elif message in phase_map:
                    self.phase = message
                    self.execute_phase()
                elif message == "TASK_COMPLETE":
                    self.active_phase_actors.remove(sender)
                    if not self.active_phase_actors:
                        self.change_phase()
        elif isinstance(context,str):
            if context == "actor_request":
                #log.INFO("Received actor request '"+message+"' from " + str(sender),self.identity)
                self.send(sender,(message,self.actors[message]))
            if context == "start_time" and not self.start_date:
                self.start_date = message
                self.init_start_time()
            if context == "end_time" and not self.end_date:
                self.end_date = message
                self.init_end_time()


    def change_phase(self):
        current_phase_num = list(phase_map.keys()).index(self.phase)
        try:
            next_phase = list(phase_map.keys())[current_phase_num+1]
            log.INFO("Moving to next phase: "+next_phase,self.identity)
            self.receiveMessage(next_phase,self)
        except:
            log.INFO("Simulation complete.")


if __name__ == "__main__":
    main_actor = asys.createActor(Main_Actor)
    asys.tell(main_actor, "Initializing")