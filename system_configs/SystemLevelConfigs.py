from thespian.actors import *

asys = ActorSystem()
MAX_WAIT_TIME = 2#currently unused
ARG_DELIM = ','#delimited for lists in input files
LOCALITY_WIDTH = 6#The width (lon) of a locality worker, it must evenly divide into 360 to avoid errors
LOCALITY_HEIGHT = 6#The height (lat) of a locality worker, it must evenly divide into 180 to avoid errors
