from django.apps import AppConfig
import threading
import requests
import time

def keep_alive():
    while True:
        time.sleep(10 * 60)  # every 10 minutes
        try:
            requests.get("https://sun-backend2.onrender.com/health/")
            print("✅ Self ping successful")
        except Exception as e:
            print(f"❌ Self ping failed: {e}")

class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        t = threading.Thread(target=keep_alive, daemon=True)
        t.start()