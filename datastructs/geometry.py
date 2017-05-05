from utilities.logger import log
from utilities.random_generator import RANDOM


class Area:
    def __init__(self,data):
        #in the future these variables should be separated out into
        #another class. They are kept here to avoid the overhead
        #of creating and maintaining another object at runtime
        self.lat_min = None
        self.lon_min = None
        self.lat_max = None
        self.lon_max = None
        self.alt = 0
        self.initial_tags = set()
        self.tags = set()
        self.name = None#the tricky part is going to be allowing it to be non-unique

        try: self.load_from_kml(data)
        except: self.load_from_dict(data)

    def load_coordinates(self,coord_data):
        self.lon_min,self.lat_min,self.lon_max,self.lat_max = coord_data
        
    def load_name(self,name_data):
        for line in name_data.split('\n'):
            n = line.strip().lower()[:4]
            if n in ["area","site","name"]:
                split_point = line.find(":")
                self.name = line[split_point+1:].strip()
                return
        log.ERROR("Invalid KML entry, name not found in description tag " + str(name_data),"new_area")
        
    def load_tags(self,tag_data):
        for line in tag_data.split('\n'):
            n = line.strip().lower()[:4]
            if n == "tags":
                split_point = line.find(":")
                tag_string = line[split_point+1:].strip()
                for tag in tag_string.split(','):
                    self.initial_tags.add(tag.strip())
                self.tags = self.initial_tags
                return

    def load_from_kml(self,data): 
        self.load_name(data.description)
        self.load_tags(data.description)
        self.load_coordinates(data.geometry.bounds)

    def get_pos_in_site(self):
        return (RANDOM.next_float(self.lon_max,self.lon_min),
                RANDOM.next_float(self.lat_max,self.lat_min),
                self.alt)

    #currently unused, implement in conjunction with REST like insertion API
    def load_from_dict(self,data): pass
    
    def __str__(self):
        return(f"Name: {self.name}\nTags: {self.initial_tags}\nBounds: {self.lon_min,self.lat_min,self.lon_max,self.lat_max}")