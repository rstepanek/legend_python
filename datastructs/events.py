from utilities.input_validator import validator as iv
from utilities.runtime_utils import get_new_event_uuid

test = iv.simple_clean
REQUIRED_KEYS = {'time':iv.validate_time,'event':iv.parse_event_args,'source':iv.validate_source}
OPTIONAL_KEYS = {'location':test}#TODO...implement optional keys as functionality comes online

class Event:
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
                #TODO:put debug flag here
                #log.WARN("Invalid key when creating event: '" + key + "' will be ignored.","new event")

        self.__setattr__("source",getattr(self,"source","SYSTEM"))

        iv.validate(self,REQUIRED_KEYS)
        self.event_type = self.event[0]
        self.args = self.event[1]
        self.uuid = get_new_event_uuid()

    #needed for priority sorting
    def __lt__(self, other):
        return self.time < other.time

    #used for equality comparison
    def __eq__(self,other):
        return self.__hash__() == other.__hash__()

    #needed for equality comparison
    def __hash__(self):
        return self.uuid

    #used to output the event in a human readable format
    def __str__(self):
        try: s = str(self.source)
            #s = str(self.source.name)+":"+str(self.source.ID)
            #try: s += "\t" + str(self.source.state.name)
            #except: pass
        except: s = str(self.source)
        return "\t".join([self.event_type,str(self.time),str(self.args),s])