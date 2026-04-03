from django.apps import AppConfig

class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        import threading
        import requests
        import time

        def keep_alive():
            while True:
                time.sleep(10 * 60)
                try:
                    requests.get("https://sun-backend2-2.onrender.com/health/")
                    print("✅ Self ping successful")
                except Exception as e:
                    print(f"❌ Self ping failed: {e}")

        t = threading.Thread(target=keep_alive, daemon=True)
        t.start()