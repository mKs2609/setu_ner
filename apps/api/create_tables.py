"""
One-time setup: creates the roads and districts tables from the SQLAlchemy
models. Run this once before the first load_into_postgis.py run (or again
any time the schema in app/db/models.py changes).

    python create_tables.py
"""

from sqlalchemy import create_engine
from app.db.models import Base
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url)

Base.metadata.create_all(engine)
print("Tables created: roads, districts")