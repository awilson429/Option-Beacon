from __future__ import annotations

import json

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scalp_research_observations (
  id TEXT PRIMARY KEY, symbol TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL,
  strategy TEXT NOT NULL CHECK (strategy = 'SCALP_RESEARCH'), mode TEXT NOT NULL CHECK (mode = 'SHADOW'),
  direction TEXT, setup_family TEXT, setup_state TEXT NOT NULL, payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS scalp_observations_symbol_time ON scalp_research_observations(symbol, observed_at DESC);
"""


class ScalpResearchRepository:
    """Additive persistence adapter; never reads or writes production trade tables."""
    def __init__(self, connection_factory): self.connection_factory=connection_factory
    def initialize(self):
        with self.connection_factory() as connection:
            with connection.cursor() as cursor: cursor.execute(SCHEMA_SQL)
            connection.commit()
    def save_observation(self, opportunity):
        row=opportunity.to_dict()
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO scalp_research_observations
                  (id,symbol,observed_at,strategy,mode,direction,setup_family,setup_state,payload)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                  (row["opportunity_id"],row["symbol"],row["observed_at"],row["strategy"],row["mode"],row["direction"],row["setup_family"],row["state"],json.dumps(row,default=str)))
            connection.commit()
