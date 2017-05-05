"""
Name = State:test
Require_Tags = testing,one
Banned_Tags = production
Duration = 1Days-2 Days
Yields = successful test + 1; split test = 10
Cost = None
PoolRestrictions = None
TimeFreq = 1-2,3d-4d
On_Start_Message = Test has began.
On_Entrance_Message = Activated.
On_Exit_Message = Test has ended.
On_Hibernate_Message = Deactivated.
Concurrent = True
onmeta_tags = testingon, one-on
offmeta_tags = testingoff,one-off
tags = s1
"""
from utilities.input_validator import validator as iv
from datastructs.duration import Duration
from datastructs.directives import Directive
import utilities.runtime_utils as rt

simple_clean = iv.simple_clean
REQUIRED_KEYS = {'name':simple_clean, 'duration':simple_clean}
OPTIONAL_KEYS = {'directives':simple_clean,'speed':iv.parse_speed}#TODO...implement optional keys as functionality comes online

class State:
    def __init__(self,dict):
        for key in dict:
            if (key.strip().lower() in REQUIRED_KEYS):
                self.__setattr__(key.strip().lower(),
                    REQUIRED_KEYS[key.strip().lower()](dict[key]))
            elif (key.strip().lower() in OPTIONAL_KEYS):
                self.__setattr__(key.strip().lower(),
                    OPTIONAL_KEYS[key.strip().lower()](dict[key]))
            else:
                pass
                #log.WARN("Invalid key when creating state: '" + key + "' will be ignored.","new state")

        iv.validate(self,REQUIRED_KEYS)
        self.duration = Duration(getattr(self, "duration", None))
        #verify directives
        #The time and source will be updated prior to insertion into event queue
        #use getattr because it is significantly quicker than hasattr
        if getattr(self,"directives",None):
            dirs = getattr(self,"directives")
            if isinstance(dirs,str):
                self.directives = [Directive({"event":dirs,"time":rt.end_time,"source":"SYSTEM"})]
            else:
                self.directives = [Directive({"event":x,"time":rt.end_time,"source":"SYSTEM"}) for x in dirs]
        self.speed = getattr(self,"speed",0)#default speed to 0

    def get_time_in_state(self):
        return self.duration.get_next_time()

