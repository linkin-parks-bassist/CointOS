import unittest
from ecosystem.queries import answer

class QueryTest(unittest.TestCase):
    def test_last_role_spawn_is_exact(self):
        facts={"timezone":"Australia/Sydney","latest_by_role":{"steward":{"agent_name":"Silas","created_at":"2026-09-03T20:16:32+10:00"}}}
        result=answer("last_role_spawn","steward",facts)
        self.assertEqual(result,"The last steward was Silas, spawned at 8:16:32 PM on 3 September 2026 (Australia/Sydney).")
