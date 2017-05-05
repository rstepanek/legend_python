from utilities.input_validator import validator as iv
from utilities.random_generator import RANDOM

test = iv.simple_clean
REQUIRED_KEYS = {'name':test,'transitions':iv.init_transitions}
OPTIONAL_KEYS = {}#TODO...implement optional keys as functionality comes online

class Process:
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
                #log.WARN("Invalid key when creating process: '" + key + "' will be ignored.","new process")
                
        iv.validate(self,REQUIRED_KEYS)
        #log.INFO(str(self.transitions),"process:"+self.name)
        self.ENTRANCE_TRANSITION = [x for x in self.transitions if x.xtype == "ENTRANCE_TRANSITION"]

    def __str__(self):
        return self.name + "\t" + str(self.transitions)

    #get all entrance transitions and return a state
    def get_initial_state(self):
        result = RANDOM.next_float() *0.01;
        for transition in self.ENTRANCE_TRANSITION:
            if result < transition.prob:
                return transition.final_state
            else:
                result = result - transition.prob

    #given a state, return the next state
    def get_next_state(self,state,message=None):
        if message:
            relevant_transitions = [x for x in relevant_transitions if message==x.message]
        else:
            relevant_transitions = [x for x in self.transitions if (x.initial_state == state.name and x.xtype!="MESSAGE_TRANSITION")]
        result = RANDOM.next_float() *0.01
        for transition in relevant_transitions:
            if result < transition.prob:
                return transition.final_state
            else:
                result = result - transition.prob

