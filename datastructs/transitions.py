from utilities.logger import log
# forms 
# _ => x =
# 0.8 => x
# x -- 0.8 => y
# x -- some_msg => y
# x -- some_msg -- 0.8 => y

SYMBOLS = ["--","=>"]
ENTRANCE_SYMBOL = '_'

class SX:#state transition
    def __init__(self,data):
        if len(data) > 4: log.ERROR("Invalid transition in process file: " +str(data)+" new transition")
        self.xtype = None
        self.initial_state = None
        self.final_state = None
        self.message = None
        self.prob = None
        self.parse_data(data)

    def parse_data(self,data):
        form = []
        if data[0] == ENTRANCE_SYMBOL:
            self.xtype = "ENTRANCE_TRANSITION"
            self.final_state = data[1]
            self.prob = 1.00
            return;
        elif len(data)==2:
            self.xtype = "ENTRANCE_TRANSITION"
            self.final_state = data[-1]
            self.prob = float(data[0])
        else:
            self.initial_state = data[0]
            self.final_state = data[-1]
            if len(data) == 3:
                try: 
                    self.prob = float(data[1])
                    self.xtype = "PROB_TRANSITION"
                except: 
                    self.message = data[1]
                    self.prob = 1.0
                    self.xtype = "MESSAGE_TRANSITION"
            else:
                self.message = data[1]
                self.prob = float(data[2])
                self.xtype = "MESSAGE_TRANSITION"