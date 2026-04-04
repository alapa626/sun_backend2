from django.apps import AppConfig

class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        import threading
        import requests
        import time
        import os

        if os.environ.get('RUN_MAIN') == 'true':
            return

        def keep_alive():
            time.sleep(30)
            while True:
                try:
                    requests.get(
                        "https://sun-backend2-2.onrender.com/health/",
                        timeout=10
                    )
                    print("✅ Self ping successful")
                except Exception as e:
                    print(f"❌ Self ping failed: {e}")
                time.sleep(5 * 60)

        t = threading.Thread(target=keep_alive, daemon=True)
        t.start()