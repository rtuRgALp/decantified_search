import { selectionMatches, splitNoteTerms, productMatchesExclusion, normalizeTerm } from './finder-core.js';

export const STORAGE_KEY = 'scent-compass-sample-cart-v2';
export const STALE_MS = 72 * 3600e3;
export const OVERDUE_MS = 36 * 3600e3;
export function compareText(a, b) { return String(a).localeCompare(String(b), 'en', { sensitivity: 'base' }); }
export function safeRetailerUrl(value, retailer) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && retailer?.approved_origins.includes(url.origin) ? url.href : '';
  } catch { return ''; }
}
export function stockState(offer, variant, now = Date.now()) {
  if (offer.listing_state === 'no_longer_listed' || variant.stock === 'no_longer_listed') return 'no_longer_listed';
  const observed = Date.parse(variant.observed_at || offer.observed_at);
  if (!Number.isFinite(observed) || now - observed > STALE_MS) return 'unknown';
  return ['in_stock', 'out_of_stock', 'backorder', 'unknown'].includes(variant.stock) ? variant.stock : 'unknown';
}
export function availableVariants(offer, now = Date.now()) {
  return offer.variants.filter(v => stockState(offer, v, now) === 'in_stock').sort((a,b) => a.size_ml - b.size_ml || compareText(a.id,b.id));
}
export function newlyListed(offer, now = Date.now()) {
  const age = now - Date.parse(offer.first_seen_at);
  return !offer.initial_import && Number.isFinite(age) && age >= 0 && age <= 30 * 86400e3;
}
export function sortOffers(offers, retailers, comparison = null) {
  const name = o => retailers.get(o.retailer_id)?.name || o.retailer_id;
  return [...offers].sort((a,b) => {
    if (comparison) {
      const price = o => availableVariants(o).filter(v => v.currency === comparison.currency && v.size_ml === comparison.size_ml).reduce((min,v) => Math.min(min,v.price_minor), Infinity);
      const ap=price(a), bp=price(b);
      if (ap !== bp) return ap < bp ? -1 : 1;
    }
    return compareText(name(a),name(b)) || compareText(a.id,b.id);
  });
}
export function groupFragrances(offers, retailers, selected, includeSoldOut = false, now = Date.now()) {
  const groups = new Map(), byName = new Map();
  const nameKey = fragrance => [fragrance.brand,fragrance.name].map(value=>String(value||'').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim()).join('|');
  for (const offer of offers) {
    if (!selected.has(offer.retailer_id) || (!includeSoldOut && !availableVariants(offer,now).length)) continue;
    if(offer.fragrance.brand){const key=nameKey(offer.fragrance);if(!byName.has(key))byName.set(key,[]);byName.get(key).push(offer);}
    const id = offer.fragrance_id;
    if (!groups.has(id)) groups.set(id, {id, name: offer.fragrance.name, brand: offer.fragrance.brand, concentration: offer.fragrance.concentration, offers: []});
    groups.get(id).offers.push(offer);
  }
  return [...groups.values()].map(group => ({...group, offers: sortOffers(group.offers,retailers), relatedOffers: sortOffers((byName.get(nameKey(group))||[]).filter(o=>o.fragrance_id!==group.id && (!group.concentration || !o.fragrance.concentration)),retailers)})).sort((a,b) => compareText(a.name,b.name) || compareText(a.id,b.id));
}
export function searchFragrances(groups, selections, mode='any') {
  if (!selections.length) return [];
  return groups.map(group => {
    const matches = selections.map(selection => ({...selection, evidence: group.offers.map(offer => ({offerId:offer.id, retailerId:offer.retailer_id, fields:selectionMatches(offer,selection)})).filter(e => e.fields.length)}));
    return {...group, matches, matchedCount:matches.filter(m => m.evidence.length).length};
  }).filter(group => mode === 'all' ? group.matchedCount === selections.length : group.matchedCount > 0)
    .sort((a,b) => b.matchedCount - a.matchedCount || compareText(a.name,b.name) || compareText(a.id,b.id));
}
export function buildNoteBank(groups) {
  const banks = {all:new Map(),top:new Map(),heart:new Map(),base:new Map()};
  for (const group of groups) {
    const all = new Set();
    for (const layer of ['top','heart','base']) {
      const terms = new Set(group.offers.flatMap(o => splitNoteTerms(o[layer] || '')));
      for (const term of terms) {banks[layer].set(term,(banks[layer].get(term)||0)+1);all.add(term);}
    }
    for (const term of group.offers.flatMap(o => splitNoteTerms(o.unlayered || ''))) all.add(term);
    for (const term of all) banks.all.set(term,(banks.all.get(term)||0)+1);
  }
  return Object.fromEntries(Object.entries(banks).map(([layer,counts]) => [layer,[...counts].map(([term,count])=>({term,count})).sort((a,b)=>b.count-a.count||compareText(a.term,b.term))]));
}
export function chooseVariant(offer, requestedSize = null, now=Date.now()) {
  const variants=availableVariants(offer,now);
  const requested=variants.find(v=>v.size_ml===Number(requestedSize));
  return {variant:requested || variants[0], fallback:requestedSize !== null && !requested};
}
export function selectionSnapshot(offer,variant,retailer) {
  return {offerId:offer.id,variantId:variant.id,snapshot:{name:offer.name,fragranceId:offer.fragrance_id,retailerId:offer.retailer_id,retailerName:retailer.name,url:offer.url,variant:{...variant},observedAt:offer.observed_at}};
}
export function reconcileCart(cart, offers, retailers, exclusions=[], ceilings={}, now=Date.now()) {
  return cart.map(item=>{
    const offer=offers.get(item.offerId), variant=offer?.variants.find(v=>v.id===item.variantId);
    const reasons=[];
    const status=offer && variant ? stockState(offer,variant,now) : offer ? 'no_longer_listed' : 'unknown';
    if(status!=='in_stock') reasons.push(status==='unknown'?'Availability unverified':status==='backorder'?'Backorder':status==='out_of_stock'?'Sold out':'No longer listed or catalog unavailable');
    if(offer) {
      const hits=exclusions.filter(rule=>productMatchesExclusion(offer,rule.term,rule.exact).length);
      if(hits.length) reasons.push(`Excluded: ${hits.map(r=>r.term).join(', ')}`);
    }
    if(variant && ceilings[variant.currency] != null && variant.price_minor > ceilings[variant.currency]) reasons.push(`Above ${variant.currency} limit`);
    const priceChanged=!!variant && (variant.price_minor!==item.snapshot?.variant?.price_minor || variant.currency!==item.snapshot?.variant?.currency);
    const retailer=retailers.get(offer?.retailer_id || item.snapshot?.retailerId);
    if(!offer || !safeRetailerUrl(offer.url,retailer)) reasons.push('Retailer link unavailable');
    return {...item,offer,variant:variant || item.snapshot?.variant,retailer,status,priceChanged,reasons,ready:reasons.length===0};
  });
}
export function alternativesFor(item, offers, retailers, now=Date.now()) {
  const fragranceId=item.offer?.fragrance_id || item.snapshot?.fragranceId;
  if(!fragranceId?.startsWith('fragrance:')) return [];
  return sortOffers([...offers.values()].filter(o=>o.fragrance_id===fragranceId && o.id!==item.offerId && availableVariants(o,now).length),retailers);
}
export function checkoutUrl(items, retailer) {
  if(!retailer?.checkout_verified_at || retailer.adapter!=='shopify') return '';
  const selected=items.filter(item=>item.ready && item.offer?.retailer_id===retailer.id);
  if(!selected.length || selected.some(item=>!/^\d+$/.test(item.variant.source_id))) return '';
  return safeRetailerUrl(`${retailer.origin}/cart/${selected.map(item=>`${item.variant.source_id}:1`).join(',')}?storefront=true&utm_source=scent_compass&utm_medium=referral`,retailer);
}
export function migrateCart(saved, offers, retailers) {
  if(!saved || !Array.isArray(saved.cart)) throw Error('Invalid saved cart');
  const byVariant=new Map();
  for(const offer of offers.values()) if(offer.retailer_id==='decantified') for(const variant of offer.variants) byVariant.set(variant.source_id,{offer,variant});
  const cart=saved.cart.map(item=>{
    const match=byVariant.get(String(item.variant?.id));
    if(!match) throw Error('A legacy selection could not be mapped safely; old cart retained');
    const migrated=selectionSnapshot(match.offer,match.variant,retailers.get('decantified'));
    if(item.variant.price!=null && Number.isFinite(Number(item.variant.price))) migrated.snapshot.variant.price_minor=Math.round(Number(item.variant.price)*100);
    return migrated;
  });
  return {cart,exclusions:Array.isArray(saved.exclusions)?saved.exclusions:[],ceilings:saved.maxPrice==null?{}:{USD:Math.round(Number(saved.maxPrice)*100)}};
}
export function formatMoney(variant) {
  return new Intl.NumberFormat('en',{style:'currency',currency:variant.currency,currencyDisplay:'code'}).format(variant.price_minor/100);
}
export function cartCsv(items, retailers) {
  const header=['fragrance_identity','product_name','retailer','currency','size_ml','price','variant_id','stock','last_checked','excluded_reason','product_url','checkout_url'];
  const rows=items.map(item=>[item.offer?.fragrance_id || item.snapshot?.fragranceId,item.offer?.name || item.snapshot?.name,item.retailer?.name || item.snapshot?.retailerName,item.variant?.currency,item.variant?.size_ml,item.variant ? (item.variant.price_minor/100).toFixed(2) : '',item.variantId,item.status,item.variant?.observed_at || item.snapshot?.observedAt,item.reasons.join('; '),safeRetailerUrl(item.offer?.url || item.snapshot?.url,item.retailer),item.ready?checkoutUrl(items,item.retailer):'']);
  return [header,...rows].map(row=>row.map(value=>`"${String(value??'').replace(/^[=+@\-]/,"'"+'$&').replaceAll('"','""')}"`).join(',')).join('\r\n');
}
