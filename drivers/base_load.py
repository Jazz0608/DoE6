from abc import ABC, abstractmethod


class BaseLoad(ABC):

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def get_id(self):
        pass

    @abstractmethod
    def set_cc(self):
        pass

    @abstractmethod
    def set_current(self, current):
        pass

    @abstractmethod
    def load_on(self):
        pass

    @abstractmethod
    def load_off(self):
        pass