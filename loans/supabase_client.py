"""
Supabase client initialization
Make sure SUPABASE_URL and SUPABASE_SERVICE_KEY are set in settings.py
"""

from supabase import create_client
from django.conf import settings

# Initialize Supabase client with service key
supabase = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_SERVICE_KEY
)