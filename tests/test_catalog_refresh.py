import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.refresh_catalogs import normalize_product, merge_snapshot, fetch_shopify, fetch_woocommerce, identity, volume, minor_price, refresh_one

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=json.loads((ROOT/'retailers.json').read_text())['retailers']
R=next(r for r in REGISTRY if r['id']=='decantified')
NOW='2026-09-30T12:00:00+00:00'

def raw(pid=1,available=True):
    return {'id':pid,'title':'Night Smoke EDP by Example – Sample Decant','vendor':'Example','handle':f'night-{pid}','body_html':'<p>Top Notes: Bergamot</p><p>Base Notes: Vanilla</p>','tags':[], 'variants':[{'id':pid*10,'title':'1ml (2ml decant filled halfway)','price':'2.50','available':available},{'id':pid*10+1,'title':'100ml full bottle','price':'100.00','available':True}]}

class CatalogTests(unittest.TestCase):
    def test_registry_29_unique_and_neutral(self):
        self.assertEqual(len(REGISTRY),29)
        self.assertEqual(len({r['original_domain'] for r in REGISTRY}),29)
        self.assertEqual(sum(r['original_domain']=='bizescents.com' for r in REGISTRY),1)
        self.assertTrue(all(not r['original_domain'].startswith('*') for r in REGISTRY))
        self.assertTrue(all('rank' not in r and 'score' not in r for r in REGISTRY))
        self.assertEqual([r['name'].casefold() for r in REGISTRY],sorted(r['name'].casefold() for r in REGISTRY))

    def test_decant_volume_and_full_bottle_exclusion(self):
        product=normalize_product(raw(),R,NOW)
        self.assertEqual(len(product['variants']),1)
        self.assertEqual(product['variants'][0]['size_ml'],1)
        self.assertEqual(volume('2 ml sample (3ml vial)'),2)
        bottle=raw();bottle['title']='Example EDP';bottle['body_html']='';bottle['variants']=[{'id':1,'title':'5ml','price':'1.00','available':True}]
        self.assertIsNone(normalize_product(bottle,R,NOW))
        generic=raw();generic['title']='Sample 5 ml';generic['variants']=[{'id':1,'title':'5ml','price':'1.00','available':True}]
        self.assertIsNone(normalize_product(generic,R,NOW))

    def test_variant_stock_prices_and_missing_notes(self):
        item=raw(available=False);item['body_html']='Sample decant';item['variants'].append({'id':12,'title':'2ml','price':'4.70','available':True})
        product=normalize_product(item,R,NOW)
        self.assertEqual([v['stock'] for v in product['variants']],['out_of_stock','in_stock'])
        self.assertEqual(product['top'],'')
        self.assertEqual(product['variants'][1]['price_minor'],470)
        with self.assertRaises(ValueError):minor_price('NaN')

    def test_stable_scoped_ids(self):
        a=normalize_product(raw(),R,NOW)
        b=normalize_product(raw(),{**R,'id':'other'},NOW)
        self.assertNotEqual(a['id'],b['id'])
        self.assertNotEqual(a['variants'][0]['id'],b['variants'][0]['id'])
        self.assertEqual(a['id'],normalize_product(raw(),R,'2026-10-01T00:00:00Z')['id'])

    def test_identity_concentration_flankers_and_inspiration(self):
        edp=normalize_product(raw(),R,NOW)
        second=raw();second['title']='Night Smoke EDP – Example – Sample'
        self.assertEqual(edp['fragrance_id'],normalize_product(second,{**R,'id':'other'},NOW)['fragrance_id'])
        for name in ['Night Smoke Intense EDP by Example – Sample','Night Smoke EDT by Example – Sample']:
            other=raw();other['title']=name
            self.assertNotEqual(edp['fragrance_id'],normalize_product(other,R,NOW)['fragrance_id'])
        incomplete=raw();incomplete['title']='Night Smoke – Sample';incomplete['vendor']='Inspiration: Example'
        self.assertTrue(normalize_product(incomplete,R,NOW)['fragrance_id'].startswith('listing:'))

    def test_history_new_restocks_removed_and_collapse(self):
        a=normalize_product(raw(1,False),R,NOW);b=normalize_product(raw(2),R,NOW)
        initial=merge_snapshot(R,[a,b],None,NOW)
        self.assertTrue(all(p['initial_import'] for p in initial['products']))
        later='2026-10-01T12:00:00+00:00'
        next_snapshot=merge_snapshot(R,[normalize_product(raw(1),R,later),normalize_product(raw(3),R,later)],initial,later)
        by_id={p['id']:p for p in next_snapshot['products']}
        self.assertEqual(by_id[a['id']]['first_seen_at'],NOW)
        self.assertEqual(by_id[a['id']]['variants'][0]['stock'],'in_stock')
        self.assertEqual(by_id[b['id']]['listing_state'],'no_longer_listed')
        self.assertFalse(by_id['decantified:3']['initial_import'])
        with self.assertRaises(ValueError):merge_snapshot(R,[],initial,later)

    @patch('scripts.refresh_catalogs.time.sleep')
    def test_pagination_repeats_and_partial_failures(self,_):
        calls=[]
        def get(url,r):
            calls.append(url)
            return ({'products':[raw(1)]} if 'page=1&' in url else {'products':[]}),{}
        self.assertEqual(len(fetch_shopify(R,get)),1)
        self.assertEqual(len(calls),2)
        with self.assertRaises(ValueError):fetch_shopify(R,lambda u,r:({'products':[raw(1)]},{}))
        def partial(url,r):
            if 'page=2&' in url:raise TimeoutError('partial fetch')
            return {'products':[raw()]},{}
        with self.assertRaises(TimeoutError):fetch_shopify(R,partial)

    def test_failed_refresh_retains_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'decantified.json';snapshot=merge_snapshot(R,[normalize_product(raw(),R,NOW)],None,NOW);path.write_text(json.dumps(snapshot));before=path.read_bytes()
            with patch('scripts.refresh_catalogs.verify_shopify_currency'), patch('scripts.refresh_catalogs.fetch_shopify',side_effect=TimeoutError('timeout')):
                report=refresh_one(R,Path(folder))
            self.assertEqual(report['status'],'retained');self.assertEqual(path.read_bytes(),before)
            self.assertEqual(report['last_success_at'],NOW)

    @patch('scripts.refresh_catalogs.time.sleep')
    def test_woocommerce_variation_prices_and_stock(self,_):
        retailer=next(r for r in REGISTRY if r['id']=='scentswithsense')
        parent={'id':1,'name':'Example EDP Sample by House','type':'variable','permalink':retailer['origin']+'/product/example/','description':'<p>Sample decant</p>','variations':[{'id':11,'attributes':[{'name':'Size','value':'2ml'}]},{'id':12,'attributes':[{'name':'Size','value':'5ml'}]}]}
        records=[{'id':11,'is_in_stock':True,'prices':{'price':'470','currency_code':'USD','currency_minor_unit':2}}, {'id':12,'is_in_stock':False,'prices':{'price':'1200','currency_code':'USD','currency_minor_unit':2}}]
        def get(url,r):return (records if 'type=variation' in url else [copy.deepcopy(parent)]),{'X-WP-TotalPages':'1'}
        products=fetch_woocommerce(retailer,get);offer=normalize_product(products[0],retailer,NOW)
        self.assertEqual([v['price_minor'] for v in offer['variants']],[470,1200])
        self.assertEqual([v['stock'] for v in offer['variants']],['in_stock','out_of_stock'])
        with self.assertRaises(ValueError):fetch_woocommerce(retailer,lambda u,r: ([] if 'type=variation' in u else [copy.deepcopy(parent)],{'X-WP-TotalPages':'1'}))

if __name__=='__main__':unittest.main()
