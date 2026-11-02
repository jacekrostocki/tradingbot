import unittest
from src.data_store import INTERVALS,validate

class TestStore(unittest.TestCase):
 def r(self,t):return {'timestamp_ms':t,'open':'100','high':'110','low':'90','close':'105','volume':'4'}
 def test_valid(self):self.assertEqual(validate([self.r(0),self.r(INTERVALS['1h']*1000)],INTERVALS['1h'],'test'),[])
 def test_gap(self):
  with self.assertRaises(ValueError): validate([self.r(0),self.r(INTERVALS['1h']*2000)],INTERVALS['1h'],'test')
 def test_ohlc(self):
  z=self.r(0);z['high']='99'
  with self.assertRaises(ValueError):validate([z],INTERVALS['1h'],'test')
 def test_duplicate(self):
  with self.assertRaises(ValueError):validate([self.r(0),self.r(0)],INTERVALS['1h'],'test')
if __name__=='__main__':unittest.main()
