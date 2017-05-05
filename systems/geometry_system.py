from thespian.actors import *

from datastructs.geometry import Area
from utilities.logger import log
from system_configs.SystemLevelConfigs import ARG_DELIM
from datastructs.events import Event
from utilities import haversine
from system_configs.SystemLevelConfigs import LOCALITY_WIDTH,LOCALITY_HEIGHT
from utilities.haversine import haversine


class Geometry_System(Actor):
    def __init__(self):
        self.identity = "Geometry_System"
        self.parent = None
        self.kml_loader = None
        self.areas = set()
        self.area_rel_map = {}#dict of areas that contain other areas
        self.leaf_nodes = set()#set of areas that contain no other areas
        self.geometry_tags = {}
        self.main_event_loop = None
        self.event_system = None
        self.ents_to_loalities = {}#dict of entities to their respective localities
        self.current_events = set()
        self.entity_transit_table = {}#dict of entities to events

        #This is not yet implemented
        #it should have references to the entire grid of localities when finished
        #a locality is a child worker for the geometry system that is responsible
        #for distance, TTA, tagging, and finding calculations within its influence
        #the locality system provides a simple, but generally effective way of
        #distributing computational load based on physical area. It has the added
        #benefit of reducing the computational burden for finding operations as
        #distance-limited searches need to only check N number of the locality's
        #neighbors instead of the entire space
        #TODO: implement localities
        self.localities = [[None] * LOCALITY_WIDTH for i in range(LOCALITY_HEIGHT)]


    def get_kml_loader(self):
        self.send(self.parent, ("actor_request","kml_loader"))

    def get_event_system(self):
        self.send(self.parent, ("actor_request","event_system"))

    def get_kml_data(self):
        self.send(self.kml_loader, "kml_request")

    def get_entity_system(self):
        self.send(self.parent, ("actor_request","entity_system"))

    def print_status(self):
        return str(len(self.areas)) + " Areas"

    def create_locality(self,x,y):
        pass#self.localities[x][y] =  Locality(x1,y1,x2,y2)

    #Low priority improvement
    #load time is not significant, but this could be speed up
    #by caching (pickling or storing the data) on disk after
    #verification, along with a hash code of the input kml data.
    #This would allow consecutive runs to check against the hash
    #and skip verification if no changes have been made.
    def construct_geometries(self, kml_data):
        for k_data in kml_data:
            self.areas.add(Area(k_data))
        self.construct_inclusion_table()
        #print(self.area_rel_map)
        self.build_tag_table()
        self.leaf_nodes = self.areas.difference(self.area_rel_map.keys())
        log.INFO("Loaded " + self.print_status(),self.identity)
        self.send(self.parent,"TASK_COMPLETE")


    #constructs the nested map of geometry inclusions
    #used for tag propagation and eventually
    #for quick pathfinding between areas (not yet implemented)
    #TODO, implement divide and conquer strategy to speed it up
    #speed up is low priority since this is only used prior to sim-run
    def construct_inclusion_table(self):
        for a in self.areas:
            contains = None
            for b in self.areas:
                if a == b: continue
                if a.lon_min > b.lon_min: continue
                if a.lat_min > b.lat_min: continue
                if a.lon_max < b.lon_max: continue
                if a.lat_max < b.lat_max: continue

                if contains:
                    contains.append(b)
                else: contains = [b]
            if contains:
                self.area_rel_map[a]= contains


    def build_tag_table(self):
        for area in self.area_rel_map:
            for sub_area in self.area_rel_map[area]:
                for tag in sub_area.initial_tags:
                    self.add_tag(tag,sub_area)
                    self.add_tag(tag,area)
                    area.tags.add(tag)


    def add_tag(self,tag,object):
        try: self.geometry_tags[tag].add(object)
        except: 
            self.geometry_tags[tag] = set()
            self.geometry_tags[tag].add(object)

    def process_GoTo(self,event):
        loc = event.source.location
        if not "location" in event.args:
            alt = 0
            if "alt" in event.args: alt = event.args["alt"]
            dest = (event.args["x"],event.args["y"],alt)
        else:
            tags = event.args["location"]
            if ARG_DELIM in tags:
                tags = [x.strip() for x in tags.split(ARG_DELIM)]
            chosen_site = self.find_site_by_tags(tags)
            dest = chosen_site.get_pos_in_site()

            #get TTA alt,dest
            #schedule "Arrival"event
        dist = self.calc_distance(loc,dest) * 1000
        tta = self.calc_tta(event.source.state.speed,dist)

        #a value of -1 indicates the entity will never arrive at current velocity
        if tta != -1:

            #create an arrival event
            e = Event({"time": event.time+tta,
                       "event": "Arrival("+ARG_DELIM.join([x+"="+event.args[x] for x in event.args])+")",#this is slow, redundant, needs to be fixed
                       "source": event.source})
            if not event.source in self.entity_transit_table:
                self.entity_transit_table[event.source] = {}
            self.entity_transit_table[event.source][e] = (dest,event.time)
            self.send(self.event_system,("add_event",e))

        self.current_events.discard(event)
        self.check_events_finished()

    #takes speed in m/s and distance in meters
    #returns a time till arrival in ms
    def calc_tta(self,mps,dm):
        try: return (dm/mps)*1000
        except: return -1

    def calc_distance(self,a,b):
        return haversine((float(a[1]),float(a[0])),(float(b[1]),float(b[0])))

    #remove the event from the transit table and remove the entry for
    #the entity if its event set is empty
    def remove_event_from_transit_table(self,event):
        if event in self.entity_transit_table[event.source]:
            del(self.entity_transit_table[event.source][event])
        if len(self.entity_transit_table[event.source]) == 0:
            del(self.entity_transit_table[event.source])

    #log an arrival event
    def process_arrival(self,event):
        loc = self.entity_transit_table[event.source][event][0]
        event.source.update_location(loc)
        self.remove_event_from_transit_table(event)
        self.current_events.discard(event)
        #log.EVENT(event)
        #send a location update to the entity system
        self.send(self.entity_system,("update_entity_state",(event,event.source)))
        self.check_events_finished()

    def process_velocitychange(self,event):
        if event.source in self.entity_transit_table:
            del_event = None
            time_in_transit = 0
            dest = None
            expected_time = -1
            for e in self.entity_transit_table[event.source]:
                if e.event_type == "Arrival":
                    del_event = e
                    break
            if del_event:
                dest = self.entity_transit_table[event.source][del_event][0]
                time_in_transit = del_event.time - self.entity_transit_table[event.source][del_event][1]
                event.args = del_event.args
                del(self.entity_transit_table[event.source][del_event])

            #interpolate distance moved as function of time
            #suitable for basic, short range movement on flat terrain
            journey_completion = 1.0 - float(time_in_transit)/float(del_event.time)
            starting_point = event.source.location
            x = (float(dest[0]) - starting_point[0])*journey_completion
            y = (float(dest[1]) - starting_point[1])*journey_completion
            loc = (x,y,0)
            event.source.update_location(loc)
            self.send(self.event_system,("remove_event",del_event))
            self.send(self.entity_system,("update_entity_state",(event,event.source)))
            self.process_GoTo(event)
        self.current_events.discard(event)
        self.check_events_finished()

    def process_event(self,event):
        self.current_events.add(event)
        if event.event_type == "GoTo":
            self.process_GoTo(event)
        if event.event_type == "Arrival":
            self.process_arrival(event)
        if event.event_type == "VelocityChange":
            self.process_velocitychange(event)

    def check_events_finished(self):
        if not self.current_events:
            self.send(self.main_event_loop,("finished",self.identity.lower()))

    #given a set of tags, return a site (leaf node) that has those tags
    #TODO: Since run-time site insertion is not yet supported, add memoization to speed up this code
    def find_site_by_tags(self,tags):
        rset = set()
        if not isinstance(tags,list):
            tags = [tags]
        for tag in tags:
            if tag in self.geometry_tags:
                if len(rset) == 0:
                    rset.update(self.geometry_tags[tag])
                else:
                    rset = rset.intersection(self.geometry_tags[tag])
        if len(rset) == 0: return None

        #prefer to return leaf nodes (sites that do not contain other sites) if possible
        base_sites = rset.intersection(self.leaf_nodes)
        if len(base_sites) > 0:
            while len(base_sites) > 0:
                rsite = base_sites.pop()
                for tag in tags:
                    if not tag in rsite.initial_tags: continue
                return rsite
        return rset.pop()


    def find_site_request(self,sender,tags,message):
        chosen_site = self.find_site_by_tags(tags)
        self.send(sender,("found_site",(message,chosen_site)))


    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_kml_loader()
            self.get_event_system()
            self.get_entity_system()
        elif message == "check_status":
            self.check_events_finished()
        elif context == "event":
            if not self.main_event_loop:
                self.main_event_loop = sender
            self.process_event(message)
        elif context == "event_system":
            self.event_system = message
        elif context == "entity_system":
            self.entity_system = message
        elif context == "kml_loader":
            self.kml_loader = message
            self.get_kml_data()
        elif context == "kml_data":
            self.construct_geometries(message)
        elif context == "site_by_tags":
            self.find_site_request(sender,message.args["location"],message)