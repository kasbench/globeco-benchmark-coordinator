import requests
import time
import locust_common.portal_client as portal_client
from threading import Lock

security_service_url = "http://globeco-security-service:8000"

class SecurityMeta(type):
    _instances = {}
    _lock = Lock()  # Thread safety

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

class SecuritySingleton(metaclass=SecurityMeta):
    def __init__(self):
        print("Initializing SecuritySingleton")
        self.securities = []

    def get_securities(self, client):
        while not self.securities:
            response = portal_client.get_securities(client)        
            if response.ok:
                # print(f"Got {len(response.json())} securities")
                self.securities= response.json()
            else:
                print(f"Failed to get securities: {response.status_code} {response.reason}")
            time.sleep(1)
        return self.securities
# Usage
# singleton1 = SecuritySingleton()
# singleton2 = SecuritySingleton()
# print(singleton1 is singleton2)  # True