import datetime

def get_col_headers(line):
    dict = {}
    for i,header in enumerate(line.split('\t')):
        dict[header.strip().lower()]=i
    return dict

#todo: cache this value
epoch = datetime.datetime.utcfromtimestamp(0)
global start_time
global current_time
global end_time

event_uuid = 0
entity_uuid = 0

def unix_time_millis(dt):
    return (dt - epoch).total_seconds() * 1000.0

def get_new_event_uuid():
    global event_uuid
    event_uuid = event_uuid + 1
    return event_uuid

def get_new_entity_uuid():
    global entity_uuid
    entity_uuid = entity_uuid + 1
    return entity_uuid
