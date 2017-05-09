from utilities.input_validator import validator as iv
from copy import deepcopy

test = iv.simple_clean
num = iv.check_numeric
REQUIRED_KEYS = {'name':test,'process':test}
OPTIONAL_KEYS = {'state':test,'tags':test,"x":num,"y":num,"alt":num}#TODO...implement optional keys as functionality comes online

class Entity:
    def __init__(self, ID, entity_dict):
        self.ID = ID#Unique identifier
        for key in entity_dict:
            if entity_dict[key] == None: continue
            if (key.strip().lower() in REQUIRED_KEYS):
                self.__setattr__(key.strip().lower(),
                                 REQUIRED_KEYS[key.strip().lower()](entity_dict[key]))
            elif (key.strip().lower() in OPTIONAL_KEYS):
                self.__setattr__(key.strip().lower(),
                                 OPTIONAL_KEYS[key.strip().lower()](entity_dict[key]))
            else:
                pass
                #log.WARN("Invalid key when creating entity: '" + key + "' will be ignored.","new state")
                
        iv.validate(self,REQUIRED_KEYS)
        self.state = getattr(self, "state", None)
        self.process = getattr(self,"process",None)
        #These options to be implemented in feature extensions
        #self.parent = None
        #self.tags = None
        #self.children = None
        #self.VISIBLE = True
        #self.TANGIBLE = True
        self.ent_type = None
        self.x = getattr(self, "x", None)
        self.y = getattr(self, "y", None)
        self.alt = getattr(self, "alt", None)

    @property
    def location(self): return (self.x,self.y,self.alt)

    def update_location(self,loc):
        (self.x,self.y,self.alt) = loc

    #a factory method for creating entities from a template entity
    @staticmethod
    def create_entity_of_type(entity,id,args):
        obj_dict = deepcopy(entity.__dict__)
        for key in args:
            obj_dict[key] = args[key]
        return Entity(id,obj_dict)

    def __str__(self):
        try: pname = self.process.name
        except: pname = self.process
        try: sname = self.state.name
        except: sname = self.state
        return "\t".join([str(self.name)+":"+str(self.ID),str(pname),str(sname),str(self.x),str(self.y),str(self.alt)])
        #return str(self.__dict__)
        #return "\t".join([str(x) for x in [self.uuid,self.process,self.state,self.x,self.y,self.alt]])