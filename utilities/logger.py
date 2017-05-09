import datetime
#import requests
from urllib.request import Request as requests
#from urllib.parse import urlencode

class log:
    error_file_loc = None
    warn_file_loc = None
    info_file_loc = None
    event_file_loc = None
    error_file = None
    warning_file= None
    info_file = None
    event_file = None
    error_buffer = []
    warn_buffer = []
    info_buffer = []
    event_buffer = []
    server_uri = None

    @staticmethod
    def ERROR(msg,source=""):
        out_msg = "\t".join(["ERROR",str(source),str(msg)])
        log.log_error(out_msg)

    @staticmethod
    def WARN(msg,source=""):
        out_msg = "\t".join(["WARNING",str(source),str(msg)])
        log.log_warning(out_msg)

    @staticmethod
    def INFO(msg,source=""):
        out_msg = "\t".join(["INFO",str(source),str(msg)])
        log.log_info(out_msg)

    @staticmethod
    def EVENT(event):
        if log.server_uri: log.post_event_to_server(event)
        log.log_event(str(event))

    @staticmethod
    def log_event(event):
        #print("logging event " + event)
        log.event_buffer.append(event)
        if not log.event_file:
            if log.event_file_loc:
                open(log.event_file_loc,'w').close()
                log.event_file = open(log.event_file_loc,'a')
        else:
            log.unload_events()

    @staticmethod
    def post_event_to_server(event):
        payload = {'key1':'value1','key2':'value2'}
        
        try:
            d = {'x':float(event.source.x),'y':float(event.source.y),'id':int(event.source.ID),'name':str(event.source.name),
            'process':str(event.source.process.name),'state':str(event.source.state.name),'time':int(event.time)}
            r = requests.post(log.server_uri,data=d)#event.source.__dict__)#data=event.__dict__)
            #print(r)
            #print(r.status_code,r.reason)
            #print(r.text)
        except: pass

    @staticmethod
    def unload_events():
        while log.event_buffer:
            log.unload_next_event()

    @staticmethod
    def unload_next_event():
        e = log.event_buffer.pop(0)
        print("EVENT\t" + e)
        log.event_file.write(e+'\n')

    @staticmethod
    def log_error(error):
        print("\n\n"+error.strip()+"\n\n")
        if not log.error_file:
            if log.error_file_loc:
                open(log.error_file_loc,'w').close()
                log.error_file = open(log.error_file_loc,'a')
            else:
                log.error_buffer.append(str(datetime.datetime.now()) + "\t" + error.strip()+'\n')
        else:
            log.error_file.write(str(datetime.datetime.now()) + "\t" + error.strip()+'\n')

    @staticmethod
    def log_warning(warning):
        print(warning.strip())
        if not log.warning_file:
            if log.warn_file_loc:
                open(log.warn_file_loc,'w').close()
                log.warning_file = open(log.warn_file_loc,'a')
            else:
                log.warn_buffer.append(str(datetime.datetime.now()) + "\t" + warning.strip()+'\n')
        else:
            log.warning_file.write(str(datetime.datetime.now()) + "\t" + warning.strip()+'\n')

    @staticmethod
    def log_info(info):
        print(info.strip())
        if log.info_buffer:
            if log.info_file:
                empty_info_buffer()
                
        if log.info_file:
            log.info_file.write(str(datetime.datetime.now()) + "\t" + info.strip()+'\n')
         
        elif log.info_file_loc:
            open(log.info_file_loc,'w').close()
            log.info_file = open(log.info_file_loc,'a')
        else:
            log.info_buffer.append(str(datetime.datetime.now()) + "\t" + info.strip()+'\n')
        
    @staticmethod
    def set_error_file(file_loc):
        log.error_file_loc = file_loc
        if log.error_buffer:
            open(log.error_file_loc,'w').close()
            log.error_file = open(log.error_file_loc,'a')
            for err in log.error_buffer:
                log.error_file.write(err)
            log.error_buffer = []
    
    @staticmethod
    def set_warn_file(file_loc):
        log.warn_file_loc = file_loc
        if log.warn_buffer:
            open(log.warn_file_loc,'w').close()
            log.warn_file = open(log.warn_file_loc ,'a')
            for warn in log.warn_buffer:
                log.warn_file.write(warn)
            log.warn_buffer = []

    @staticmethod
    def set_event_file(file_loc):
        log.event_file_loc = file_loc
        if log.event_buffer:
            open(log.event_file_loc,'w').close()
            log.event_file = open(log.event_file_loc ,'a')
            for event in log.event_buffer:
                log.event_file.write(event)
            log.event_buffer = []
    
    @staticmethod
    def empty_info_buffer():
        for i in range(0,len(log.info_buffer)):
            log.info_file.write(log.info_buffer.pop())
    
    @staticmethod
    def set_info_file(file_loc):
        log.info_file_loc = file_loc
        if log.info_buffer:
            open(log.info_file_loc,'w').close()
            log.info_file = open(log.info_file_loc,'a')
            empty_info_buffer()
