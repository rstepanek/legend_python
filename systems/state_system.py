from thespian.actors import *

from datastructs.states import State
from utilities.logger import log


class State_System(Actor):
    def __init__(self):
        self.identity = "State_System"
        self.parent = None
        self.states_loader = None
        self.state_list = []
        self.pending_requests = []#tracks queued requests for state objects
        self.status = "LOADING"

    def get_state_loader(self):
        self.send(self.parent, ("actor_request","states_loader"))

    def get_state_data(self):
        self.send(self.states_loader, "state_request")

    def print_status(self):
        return str(len(self.state_list)) + " States"

    def handle_states_request(self,sender):
        if self.status == "LOADING":
            self.pending_requests.append(sender)
        else:
            self.send(sender,("states",self.state_list))

    def process_pending_requests(self):
        while self.pending_requests:
            self.send(self.pending_requests.pop(),("states",self.state_list))
        self.send(self.parent,"TASK_COMPLETE")

    def construct_states(self,state_data):
        for state in state_data:
            self.state_list.append(State(state_data[state]))
        self.status = "EXECUTING"
        log.INFO("Loaded " + self.print_status(),self.identity)
        self.process_pending_requests()

    def receiveMessage(self, message, sender):
        context = None
        if isinstance(message, tuple):
            context,message = message

        if message == "init":
            self.parent = sender
            self.get_state_loader()
        elif message == "states_request":
            self.handle_states_request(sender)
        elif context == "states_loader":
            self.states_loader = message
            self.get_state_data()
        elif context == "state_data":
            self.construct_states(message)