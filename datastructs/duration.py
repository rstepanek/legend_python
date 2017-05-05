from utilities.input_validator import validator
from utilities.random_generator import RANDOM

class Duration:

    def __init__(self,data):
        self.origin_str = data
        (self.min ,self.max) = validator.parse_duration(data)

    def get_next_time(self):
        return RANDOM.next_float(self.max,self.min)

    def __str__(self):
        return self.origin_str



