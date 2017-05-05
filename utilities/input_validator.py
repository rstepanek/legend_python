from dateutil.parser import parse

from datastructs.transitions import SX
from system_configs.SystemLevelConfigs import ARG_DELIM
from datastructs import entities#necessary to import entities instead of entities.Entity to avoid circular imports
from datastructs.geometry import Area
from utilities.logger import log

#from utilities import unix_time_millis,start_time
import utilities.runtime_utils as runtime_utils
from importlib import reload

#Entity = entities.Entity
ph = "{}"#placeholder
class validator:

    @staticmethod
    def test(data):
        print("recieved test data: "+ data)

    @staticmethod
    def validate_time(data):
        return_data = None
        try: return_data = int(data)
        except: 
            if not runtime_utils.start_time: reload(runtime_utils)
            abs_event_time = runtime_utils.unix_time_millis(parse(data))
            return_data = int(abs_event_time - runtime_utils.start_time)
        try:
            if return_data < runtime_utils.current_time:
                log.ERROR("Causality error - Events cannot be scheduled prior to sim time: "+str(data))
                #throw error if time is before the current time. Backscheduling is not allowed.
        except: pass
        return return_data

    @staticmethod
    def simple_clean(data):
        if ARG_DELIM in data:
            r = []
            for arg in data.split(ARG_DELIM):
                r.append(data.strip())
            return r
        return data.strip()

    @staticmethod
    def check_numeric(x):
        try:
            if isinstance(x,float):
                return float(x)
            return int(x)
        except: log.ERROR("Invalid numeric: "+str(x))

    @staticmethod
    def init_transitions(data):
        return_data = []
        for d in data:
            return_data.append(SX(d))
        return return_data

    @staticmethod
    def validate(obj,REQUIRED_KEYS):
        for key in REQUIRED_KEYS:
            if not hasattr(obj,key):
                log.ERROR("Missing required key '" + key +"' for new state","new state")

    @staticmethod
    def parse_event_args(args):
        event_type = args.split(r"(")[0]
        param_start = args.find(r"(")
        params = args[param_start+1:-1]#remove the last element
        event_args = {}
        for a in params.split(ARG_DELIM):
            key = a.split("=")[0].strip()#.lower()
            value_start = a.find("=")
            value = a[value_start+1:].strip()#.lower()
            event_args[key] = value

        #args = args.replace("(",ph).replace(")",ph).replace(ARG_DELIM,ph)
        #event_type = args.split(ph)[0]
        #event_args = [x.strip() for x in args.split(ph)[1:]]
        return (event_type,event_args)

    @staticmethod
    def validate_source(source):
        if isinstance(source, entities.Entity) or isinstance(source,Area) or str(source) == "SYSTEM" :
            return source
            log.ERROR("Bad event generated: " + str(source) +" is not a valid event source.")


    time_to_mils = {'s':1000,'sec':1000,'secs':1000,'seconds':1000,'second':1000,
                   'm':60000,'min':60000,'mins':60000,'minutes':60000,'minute':60000,
                   'h':3600000,'hr':3600000,'hrs':3600000,'hours':3600000,'hour':3600000,
                   'd':86400000,'day':86400000,'days':86400000,
                   'w':604800000,'wk':604800000,'wks':604800000,'week':604800000,'weeks':604800000}

    @staticmethod
    def parse_duration(source):
        #a duration of -1 indicates an indefinite duration
        if source.strip() == "-1": return -1
        times = []
        return_times = []
        if "-" in source:
            times.append(source.split("-")[-1].strip().lower())
            times.append(source.split("-")[0].strip().lower())
        else:
            times.append(source.strip().lower())

        for t in times:
            ####seperate out numeric from time unit descriptors####
            num_part = ""
            t_part = ""
            for char in t:
                if char.isdigit() or char == '.': num_part += char
                else: t_part += char
            t_part=t_part.strip()

            ####convert descriptors into times############
            for key in validator.time_to_mils:
                if key == t_part:
                    return_times.append(int(validator.time_to_mils[key]*float(num_part)))
                    break
        if len(return_times) > 1:
            return (return_times[0],return_times[1])
        return (return_times[0],return_times[0])

    #convert speed to meters per second
    #these are all decimal values
    speed_to_mps = {'kph':0.277778,'mph':0.447040357632,'knot':0.514444855556,'knots':0.514444855556}

    @staticmethod
    def parse_speed(data):
        num_part = ""
        unit_part = ""
        for char in data:
            if char.isdigit() or char == '.': num_part += char
            else: unit_part += char
        unit_part=unit_part.strip()
        if not unit_part: unit_part = "kph"

        return (float(num_part)*validator.speed_to_mps[unit_part])

