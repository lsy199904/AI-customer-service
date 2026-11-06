import unittest
from app.image_policy import validate_decision, select_images

class VisualRequestScopeTests(unittest.TestCase):
    def test_nonvisual_scope_overrides_flow_and_image_proposal(self):
        for flow in ('subscription','invoice','register'):
            source={'id':'s','image_ids':['img']}
            image={'id':'img','url':'/media/example.png','flow_ids':[flow]}
            for kind in ('rule','options','overview','local_followup'):
                with self.subTest(flow=flow,kind=kind):
                    d=validate_decision({'request_kind':kind,'need_images':True,'reason':'full_procedure',
                       'flow_ids':[flow],'image_ids':['img'],'multiple_flows':False},[source],[image])
                    images,log=select_images(d,[image],[source],[source])
                    self.assertEqual(images,[])
                    self.assertFalse(log['need_images'])
    def test_procedure_and_explicit_image_preserved(self):
        source={'id':'s','image_ids':['img']}
        image={'id':'img','url':'/media/example.png','flow_ids':['subscription']}
        for kind,reason in [('procedure','full_procedure'),('explicit_image','explicit_image')]:
            d=validate_decision({'request_kind':kind,'need_images':True,'reason':reason,
                'flow_ids':['subscription'],'image_ids':['img'],'multiple_flows':False},[source],[image])
            self.assertEqual(select_images(d,[image],[source],[source])[0],[image])
