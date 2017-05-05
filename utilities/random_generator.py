import random

#The random class. ALL random decisions must be made through this class to preserve
#repeatability through random seeds.
#This is named in all caps to avoid confusion with default 'random' module when used in code
class RANDOM:
    #starts with underscore by convention
    #see https://www.python.org/dev/peps/pep-0008/#descriptive-naming-styles
    _SEEDSET = False

    @staticmethod
    def set_seed(seed):
        if not Random._SEEDSET:#Do not allow the seed value to change more than once
            random.seed(seed)
            RANDOM._SEEDSET = True

    @staticmethod
    def next_int(max=100,min=0):
        return random.randint(min,max)

    @staticmethod
    def next_float(max=100,min=0):
        return random.uniform(min, max)