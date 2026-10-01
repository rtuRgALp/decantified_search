import { resolveBankQuery, splitNoteTerms } from './finder-core.js';
import { STORAGE_KEY, OVERDUE_MS, STALE_MS, groupFragrances, searchFragrances, buildNoteBank, availableVariants, stockState, chooseVariant, selectionSnapshot, reconcileCart, alternativesFor, checkoutUrl, migrateCart, formatMoney, cartCsv, safeRetailerUrl, sortOffers, newlyListed } from './catalog-core.js';

const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const state={retailers:new Map(),reports:new Map(),offers:new Map(),selected:new Set(),groups:[],selections:[],activeSearch:null,cart:[],exclusions:[],ceilings:{},mood:'all',query:'',visible:12,loadedAt:0,loadFailures:new Map(),storageBlocked:false,replaceOfferId:null};
const moods={fresh:['citrus','bergamot','lemon','orange','mint','aquatic'],warm:['vanilla','amber','tonka','caramel','honey','spice'],bold:['tobacco','leather','oud','smoky','incense','patchouli'],smooth:['musk','sandalwood','creamy','iris','orris','cedar']};
const stockLabels={in_stock:'Available',out_of_stock:'Sold out',unknown:'Availability unverified',backorder:'Backorder',no_longer_listed:'No longer listed'};
function checkedAt(value){return value?new Date(value).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}):'Not checked successfully';}
function showToast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>$('#toast').classList.remove('show'),4500);}
function persist(){if(state.storageBlocked)return;try{localStorage.setItem(STORAGE_KEY,JSON.stringify({cart:state.cart,exclusions:state.exclusions,ceilings:state.ceilings}));}catch{showToast('Your browser could not save these samples. Download CSV to keep them.');}}
function hydrate(){
  try{
    const current=localStorage.getItem(STORAGE_KEY);
    const legacy=current?null:localStorage.getItem('scent-compass-sample-cart-v1')||localStorage.getItem('decantified-edit-v1');
    const saved=current?JSON.parse(current):legacy?migrateCart(JSON.parse(legacy),state.offers,state.retailers):{cart:[],exclusions:[],ceilings:{}};
    if(!Array.isArray(saved.cart)||!saved.cart.every(item=>typeof item.offerId==='string'&&typeof item.variantId==='string'&&item.snapshot?.variant))throw Error('Saved selections are unreadable; original storage retained.');
    state.cart=saved.cart;state.exclusions=Array.isArray(saved.exclusions)?saved.exclusions.filter(r=>typeof r.term==='string'):[];
    state.ceilings=Object.fromEntries(Object.entries(saved.ceilings||{}).filter(([currency,value])=>/^[A-Z]{3}$/.test(currency)&&Number.isFinite(value)&&value>=0));
    if(legacy)persist();
  }catch(error){state.storageBlocked=true;showToast(error.message+' Original saved data has been retained.');}
}
async function jsonFetch(path){const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),30000);try{const response=await fetch(path,{cache:'no-cache',signal:controller.signal});if(!response.ok)throw Error('Catalog request failed ('+response.status+')');return await response.json();}finally{clearTimeout(timeout);}}
async function loadCatalogs(initial=false){
  const [registry,manifest]=await Promise.all([jsonFetch('retailers.json'),jsonFetch('catalogs/manifest.json')]);
  if(registry.schema_version!==2||manifest.schema_version!==2)throw Error('Unsupported catalog version');
  state.retailers=new Map(registry.retailers.map(r=>[r.id,r]));state.reports=new Map(manifest.retailers.map(r=>[r.retailer_id,r]));
  const next=new Map(),failures=new Map(),queue=manifest.retailers.filter(r=>r.catalog_path);let cursor=0;
  await Promise.all(Array.from({length:Math.min(4,queue.length)},async()=>{
    while(cursor<queue.length){
      const report=queue[cursor++],retailer=state.retailers.get(report.retailer_id);
      try{
        if(report.catalog_path!==`catalogs/${retailer.id}.json`)throw Error('Invalid catalog path');
        const data=await jsonFetch(report.catalog_path);
        if(data.schema_version!==2||data.retailer_id!==retailer.id||!Array.isArray(data.products))throw Error('Invalid retailer snapshot');
        for(const offer of data.products){
          if(offer.retailer_id!==retailer.id||typeof offer.id!=='string'||!safeRetailerUrl(offer.url,retailer)||!offer.fragrance||!Array.isArray(offer.variants)||offer.variants.some(v=>!Number.isInteger(v.price_minor)||v.price_minor<0||!Number.isFinite(v.size_ml)||!/^[A-Z]{3}$/.test(v.currency)))throw Error('Malformed offer');
        }
        for(const offer of data.products)next.set(offer.id,offer);
      }catch(error){failures.set(report.retailer_id,error.message);for(const offer of state.offers.values())if(offer.retailer_id===report.retailer_id)next.set(offer.id,offer);}
    }
  }));
  state.offers=next;state.loadFailures=failures;state.loadedAt=Date.now();
  if(initial){state.selected=new Set([...next.values()].map(o=>o.retailer_id));hydrate();}
  renderCoverage();refreshViews();updateCartCount();
}
function reportMessage(r){
  const report=state.reports.get(r.id),failure=state.loadFailures.get(r.id),age=Date.now()-Date.parse(report?.last_success_at);
  if(failure)return 'Catalog download failed: '+failure+'. Previous observations retained if available.';
  const reason=report?.reason?.includes('connection verification')?'Retailer connection verification prevented the latest catalog refresh.':report?.reason;
  if(!report?.catalog_path)return reason||r.fallback_reason||'Catalog not available.';
  const suffix=age>STALE_MS?' · stock unverified':age>OVERDUE_MS?' · refresh overdue':'';
  return `${report.offer_count??0} decant offers · last checked ${checkedAt(report.last_success_at)}${suffix}${reason?' · '+reason:''}`;
}
function renderCoverage(){
  const loaded=new Set([...state.offers.values()].map(o=>o.retailer_id));
  $('#coverageStatus').textContent=`${loaded.size} retailer catalogs loaded · ${state.retailers.size-loaded.size} without searchable offers${state.loadFailures.size?' · '+state.loadFailures.size+' catalog downloads failed':''}. Daily catalog checks; final price and availability are confirmed at each retailer.`;
  $('#retailerFilters').innerHTML=[...state.retailers.values()].map(r=>`<label class="retailer-filter"><span><input type="checkbox" data-retailer="${esc(r.id)}" ${state.selected.has(r.id)?'checked':''} ${loaded.has(r.id)?'':'disabled'}> ${esc(r.name)}</span><small>${esc(reportMessage(r))}</small></label>`).join('');
  $('#retailerDirectory').innerHTML=[...state.retailers.values()].map(r=>`<article class="directory-card"><h3>${esc(r.name)}</h3><p>${esc(reportMessage(r))}</p><a href="${esc(safeRetailerUrl(r.origin,r))}" target="_blank" rel="noopener">Visit retailer ↗</a></article>`).join('');
  const currencies=[...new Set([...state.offers.values()].flatMap(o=>o.variants.map(v=>v.currency)))].sort(),existing=$('#budgetCurrency').value;
  $('#budgetCurrency').innerHTML=currencies.map(c=>`<option ${c===existing?'selected':''}>${c}</option>`).join('');
}
function refreshViews(){state.groups=groupFragrances([...state.offers.values()],state.retailers,state.selected,$('#includeSoldOut').checked);refreshNoteSuggestions();renderSelections();renderBrowse();if(state.activeSearch)renderResults();}
function searchable(group){return group.offers.map(o=>`${o.name} ${o.fragrance.brand||''} ${o.inspired_by} ${o.top} ${o.heart} ${o.base} ${o.unlayered}`).join(' ').toLowerCase();}
function mood(group){const text=searchable(group);return Object.entries(moods).map(([name,terms])=>[name,terms.filter(t=>text.includes(t)).length]).sort((a,b)=>b[1]-a[1])[0][0];}
function visual(group){return `<span class="mini-bottle"><span>${esc(group.name)}</span></span>`;}
function card(group){
  const notes=[...new Set(group.offers.flatMap(o=>[o.top,o.heart,o.base,o.unlayered].flatMap(splitNoteTerms)))],ready=group.offers.filter(o=>availableVariants(o).length).length,fresh=group.offers.some(o=>newlyListed(o));
  return `<article class="product-card"><button class="card-visual visual-${mood(group)}" data-view="${esc(group.id)}" aria-label="Compare samples for ${esc(group.name)}"><span class="card-arrow">↗</span>${visual(group)}</button><div class="card-copy"><p class="card-kicker">${esc([group.brand,group.concentration].filter(Boolean).join(' · ')||'Retailer listing')}${fresh?' · Newly listed':''}</p><h3>${esc(group.name)}</h3><p class="card-notes">${esc(notes.slice(0,4).join(' · ')||'Notes not supplied')}</p><p class="card-meta">${ready} available retailer offer${ready===1?'':'s'} · ${group.offers.length} listed${group.relatedOffers?.length?' · '+group.relatedOffers.length+' additional matching listings; concentration needs review':''}</p><button class="mini-action" data-view="${esc(group.id)}">Compare samples and choose retailer →</button></div></article>`;
}
function browseFiltered(){const words=state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);return state.groups.filter(g=>(state.mood==='all'||moods[state.mood].some(t=>searchable(g).includes(t)))&&words.every(w=>searchable(g).includes(w)));}
function renderBrowse(){
  const matches=browseFiltered();$('#resultCount').textContent=matches.length;$('#offerCount').textContent=matches.reduce((n,g)=>n+g.offers.length,0);$('#productGrid').innerHTML=matches.slice(0,state.visible).map(card).join('');$('#emptyState').hidden=matches.length!==0;$('#loadMore').hidden=matches.length<=state.visible;$('#clearFilters').hidden=state.mood==='all'&&!state.query;$('#catalogTitle').textContent=`Explore ${state.groups.length} fragrances.`;
}
function refreshNoteSuggestions(){const entries=buildNoteBank(state.groups)[$('#noteLayer').value]||[];$('#noteSuggestions').innerHTML=entries.map(e=>`<option value="${esc(e.term)}">${e.count} fragrances</option>`).join('');$('#popularNotes').innerHTML=entries.slice(0,10).map(e=>`<button type="button" data-popular="${esc(e.term)}">${esc(e.term)} <small>${e.count}</small></button>`).join('');}
function addSelection(term=$('#noteInput').value){
  term=term.trim().toLowerCase();if(!term)return showToast('Enter a note first.');const layer=$('#noteLayer').value,matches=resolveBankQuery(buildNoteBank(state.groups)[layer],term);
  if(!matches.length)return showToast('No matching notes in the selected retailer and availability filters.');
  for(const entry of matches)if(!state.selections.some(s=>s.layer===layer&&s.term===entry.term))state.selections.push({layer,term:entry.term});$('#noteInput').value='';renderSelections();
}
function renderSelections(){$('#selectedNotes').innerHTML=state.selections.length?state.selections.map((s,i)=>`<button type="button" data-remove-note="${i}"><span>${s.layer==='all'?'Anywhere':esc(s.layer)}</span>${esc(s.term)} ×</button>`).join(''):'<p class="muted">No notes selected yet.</p>';}
function renderResults(){
  const groups=searchFragrances(state.groups,state.activeSearch.selections,state.activeSearch.mode);state.results=groups;
  $('#resultsSummary').textContent=`${groups.length} fragrances · ${groups.reduce((n,g)=>n+g.offers.length,0)} retailer offers · matching ${state.activeSearch.mode} selected notes. Inspect offers for note sources.`;
  $('#matchGrid').innerHTML=groups.slice(0,120).map(g=>`<div class="search-result">${card(g)}<p class="match-reason">${g.matches.filter(m=>m.evidence.length).map(m=>esc(m.term)).join(' · ')}</p></div>`).join('');$('#searchEmpty').hidden=groups.length!==0;
  const sizes=[...new Set(groups.flatMap(g=>g.offers.flatMap(o=>availableVariants(o).map(v=>v.size_ml))))].sort((a,b)=>a-b),oldSize=$('#batchSize').value;
  $('#batchSize').innerHTML='<option value="">Smallest available</option>'+sizes.map(s=>`<option value="${s}" ${String(s)===oldSize?'selected':''}>${s}ml</option>`).join('');
  const oldRetailer=$('#batchRetailer').value,ids=new Set(groups.flatMap(g=>g.offers.filter(o=>availableVariants(o).length).map(o=>o.retailer_id)));
  $('#batchRetailer').innerHTML='<option value="">Choose a retailer</option>'+[...state.retailers.values()].filter(r=>ids.has(r.id)).map(r=>`<option value="${esc(r.id)}" ${r.id===oldRetailer?'selected':''}>${esc(r.name)}</option>`).join('');
  if(groups.length>120)$('#resultsSummary').textContent+=' Showing the first 120; refine your notes to narrow results.';
}
function offerRows(group,comparison=null){
  return sortOffers(group.offers,state.retailers,comparison).map(o=>{
    const r=state.retailers.get(o.retailer_id),ready=availableVariants(o),chosen=$('#batchSize').value?Number($('#batchSize').value):null;
    const provenance=[['Top',o.top],['Heart',o.heart],['Base',o.base],['Unlayered',o.unlayered]].filter(([,text])=>text).map(([layer,text])=>`<span><b>${layer}</b> ${esc(text)}</span>`).join('');
    return `<article class="offer-row"><h3>${esc(r.name)}</h3><p class="offer-listing">${esc(o.name)}</p><p class="freshness">${esc(o.fragrance.concentration||'Concentration unverified')}</p><p class="freshness">Last checked ${esc(checkedAt(o.observed_at))}${newlyListed(o)?' · Newly listed':''}</p><div class="offer-notes">${provenance||'<span>Notes not supplied</span>'}</div><small>Note evidence: ${esc(r.name)} listing</small><div class="variant-list">${o.variants.map(v=>`<span class="variant-pill ${stockState(o,v)==='in_stock'?'':'unavailable'}">${esc(v.title)} · ${esc(formatMoney(v))} · ${stockLabels[stockState(o,v)]}</span>`).join('')}</div>${ready.length?`<label>Sample size<select data-offer-size="${esc(o.id)}">${ready.map(v=>`<option value="${esc(v.id)}" ${v.size_ml===chosen?'selected':''}>${esc(v.title)} · ${esc(formatMoney(v))}</option>`).join('')}</select></label><button class="button secondary compact" data-add="${esc(o.id)}">${state.replaceOfferId?'Replace selection with':'Add sample from'} ${esc(r.name)}</button>`:''}<a class="text-button" href="${esc(safeRetailerUrl(o.url,r))}" target="_blank" rel="noopener">View product ↗</a></article>`;
  }).join('');
}
function openProduct(id,allOffers=false){
  let group=state.groups.find(g=>g.id===id);if(allOffers){const offers=[...state.offers.values()].filter(o=>o.fragrance_id===id);if(offers.length)group={id,...offers[0].fragrance,offers};}if(!group)return;state.dialogGroup=group;
  const comparisons=[...new Set(group.offers.flatMap(o=>availableVariants(o).map(v=>`${v.currency}|${v.size_ml}`)))].sort();
  $('#dialogContent').innerHTML=`<div class="dialog-body"><p class="eyebrow">Choose your retailer</p><h2 id="dialogTitle">${esc(group.name)}</h2><p>${esc([group.brand,group.concentration].filter(Boolean).join(' · '))}</p><p>Retailers appear alphabetically. Price comparisons use the same volume and currency. Prices exclude shipping.</p><label>Offer ordering<select id="offerOrdering"><option value="">Retailer name (A–Z)</option>${comparisons.map(pair=>{const[currency,size]=pair.split('|');return `<option value="${pair}">${currency} · ${size}ml · lowest price first</option>`;}).join('')}</select></label><div id="offerRows">${offerRows(group)}</div>${!allOffers&&group.relatedOffers?.length?`<section class="related-offers"><h3>Other retailers with a matching name</h3><p>These listings match the brand and fragrance name. At least one listing omits concentration, so equivalence has not been verified. They are shown separately. Review the product before choosing a sample.</p>${offerRows({offers:group.relatedOffers})}</section>`:''}</div>`;$('#scentDialog').showModal();
}
function addOffer(offerId,variantId=null,requestedSize=null){
  const offer=state.offers.get(offerId);if(!offer)return;const choice=variantId?{variant:availableVariants(offer).find(v=>v.id===variantId),fallback:false}:chooseVariant(offer,requestedSize);if(!choice.variant)return showToast('This sample is no longer verified available.');
  const item=selectionSnapshot(offer,choice.variant,state.retailers.get(offer.retailer_id)),index=state.cart.findIndex(i=>i.offerId===offerId);
  if(state.replaceOfferId){const former=state.cart.find(i=>i.offerId===state.replaceOfferId),fid=former?.snapshot.fragranceId;if(!fid?.startsWith('fragrance:')||fid!==offer.fragrance_id)return showToast('This listing is not a verified match for the original fragrance.');state.cart=state.cart.filter(i=>i.offerId!==state.replaceOfferId&&i.offerId!==offerId);state.cart.push(item);state.replaceOfferId=null;$('#scentDialog').close();renderCart();}
  else if(index>=0)state.cart[index]=item;else state.cart.push(item);
  persist();updateCartCount();showToast(`${offer.name} saved from ${state.retailers.get(offer.retailer_id).name}${choice.fallback?' in '+choice.variant.size_ml+'ml (smallest fallback)':''}.`);
}
function addAll(){const id=$('#batchRetailer').value;if(!id)return showToast('Choose a retailer for this batch first.');let count=0,skipped=0;for(const group of state.results||[]){const offers=group.offers.filter(o=>o.retailer_id===id&&availableVariants(o).length);if(offers.length===1){addOffer(offers[0].id,null,$('#batchSize').value?Number($('#batchSize').value):null);count++;}else if(offers.length>1)skipped++;}showToast(`${count} samples saved from your chosen retailer.${skipped?' '+skipped+' ambiguous matches require individual selection.':''}`);}
function updateCartCount(){$('#cartCount').textContent=state.cart.length;$('#clearCart').hidden=state.cart.length===0;}
function cartItems(){return reconcileCart(state.cart,state.offers,state.retailers,state.exclusions,state.ceilings);}
function renderCart(){
  const items=cartItems(),groups=new Map();for(const item of items){const key=`${item.retailer?.id||item.snapshot.retailerId}|${item.variant.currency}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
  $('#cartItems').innerHTML=[...groups.values()].sort((a,b)=>(a[0].retailer?.name||a[0].snapshot.retailerName).localeCompare(b[0].retailer?.name||b[0].snapshot.retailerName)||a[0].variant.currency.localeCompare(b[0].variant.currency)).map(group=>{
    const r=group[0].retailer,ready=group.filter(i=>i.ready),total=ready.reduce((n,i)=>n+i.variant.price_minor,0),url=checkoutUrl(group,r);
    return `<section class="retailer-cart"><h3>${esc(r?.name||group[0].snapshot.retailerName)} · ${group[0].variant.currency}</h3>${group.map(item=>{
      const alternatives=!item.ready?alternativesFor(item,state.offers,state.retailers):[],variantOptions=item.offer?.variants||[],external=safeRetailerUrl(item.offer?.url||item.snapshot.url,r);
      return `<article class="cart-item ${item.ready?'':'needs-review'}"><div class="cart-item-copy"><h4>${esc(item.offer?.name||item.snapshot.name)}</h4><p>${esc(item.variant.title)} · ${esc(formatMoney(item.variant))}</p><p>${stockLabels[item.status]} · checked ${esc(checkedAt(item.variant.observed_at||item.snapshot.observedAt))}</p>${item.priceChanged?`<p class="price-notice">Price changed from ${esc(formatMoney(item.snapshot.variant))} to ${esc(formatMoney(item.variant))}.</p>`:''}${item.reasons.length?`<small>${esc(item.reasons.join(' · '))}</small>`:''}${external?`<a href="${esc(external)}" target="_blank" rel="noopener">View product ↗</a>`:''}${alternatives.length?`<button class="text-button" data-alternatives="${esc(item.offerId)}">Choose an available alternative (${alternatives.length})</button>`:''}</div><label>Size<select data-item-size="${esc(item.offerId)}"><option value="${esc(item.variantId)}">${esc(item.variant.title)} (selected)</option>${variantOptions.filter(v=>v.id!==item.variantId).map(v=>`<option value="${esc(v.id)}" ${stockState(item.offer,v)==='in_stock'?'':'disabled'}>${esc(v.title)} · ${esc(formatMoney(v))} · ${stockLabels[stockState(item.offer,v)]}</option>`).join('')}</select></label><button class="remove-item" data-remove-item="${esc(item.offerId)}">Remove</button></article>`;
    }).join('')}<div class="retailer-cart-footer"><strong>${formatMoney({price_minor:total,currency:group[0].variant.currency})}</strong><span>${ready.length} ready sample${ready.length===1?'':'s'}</span>${url?`<a class="button primary compact" href="${esc(url)}" target="_blank" rel="noopener">Open ${esc(r.name)} cart ↗</a>`:`<span class="freshness">${ready.length?'Use individual product links; prefilled cart integration is not verified.':'No samples ready for checkout.'}</span>`}</div></section>`;
  }).join('')||'<div class="cart-empty"><h3>Your sample list is empty.</h3><p>Compare offers and choose a retailer to add samples.</p></div>';
  $('#exclusionChips').innerHTML=state.exclusions.map((r,i)=>`<button data-remove-exclusion="${i}">${r.exact?'Exact':'Contains'}: ${esc(r.term)} ×</button>`).join('');$('#maxPrice').value=state.ceilings[$('#budgetCurrency').value]==null?'':state.ceilings[$('#budgetCurrency').value]/100;
  const excluded=items.filter(i=>!i.ready).length;$('#removedSummary').textContent=excluded?`${excluded} selections need review and are excluded from checkout. They remain saved.`:'';$('#cartSubhead').textContent=`${items.length} selected · ${items.length-excluded} ready. Each retailer has a separate checkout.`;$('#cartTotal').textContent=`${items.length-excluded} ready samples`;$('#cartTotalLabel').textContent='Totals shown separately by retailer and currency';return items;
}
async function openCart(){if(Date.now()-state.loadedAt>3600e3){showToast('Checking the latest published catalogs…');try{await loadCatalogs();}catch{showToast('Catalog update unavailable. Previous observations retained.');}}renderCart();$('#cartDialog').showModal();}
function exportCsv(){const url=URL.createObjectURL(new Blob([cartCsv(cartItems(),state.retailers)],{type:'text/csv'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`scent-compass-samples-${new Date().toISOString().slice(0,10)}.csv`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function applyBudget(){const value=$('#maxPrice').value,currency=$('#budgetCurrency').value;if(value==='')delete state.ceilings[currency];else if(Number.isFinite(Number(value))&&Number(value)>=0)state.ceilings[currency]=Math.round(Number(value)*100);persist();renderCart();}

document.addEventListener('click',event=>{
  const closest=s=>event.target.closest(s);
  if(closest('[data-view]')){state.replaceOfferId=null;openProduct(closest('[data-view]').dataset.view);}
  if(closest('[data-add]')){const id=closest('[data-add]').dataset.add;addOffer(id,$(`[data-offer-size="${CSS.escape(id)}"]`)?.value);}
  if(closest('[data-popular]'))addSelection(closest('[data-popular]').dataset.popular);
  if(closest('[data-remove-note]')){state.selections.splice(Number(closest('[data-remove-note]').dataset.removeNote),1);renderSelections();}
  if(closest('[data-remove-item]')){state.cart=state.cart.filter(i=>i.offerId!==closest('[data-remove-item]').dataset.removeItem);persist();updateCartCount();renderCart();}
  if(closest('[data-remove-exclusion]')){state.exclusions.splice(Number(closest('[data-remove-exclusion]').dataset.removeExclusion),1);persist();renderCart();}
  if(closest('[data-alternatives]')){const item=cartItems().find(i=>i.offerId===closest('[data-alternatives]').dataset.alternatives);state.replaceOfferId=item.offerId;openProduct(item.offer?.fragrance_id||item.snapshot.fragranceId,true);}
});
document.addEventListener('change',event=>{
  if(event.target.matches('[data-retailer]')){const id=event.target.dataset.retailer;event.target.checked?state.selected.add(id):state.selected.delete(id);state.visible=12;refreshViews();}
  if(event.target.id==='includeSoldOut'){state.visible=12;refreshViews();}
  if(event.target.id==='offerOrdering'){const pair=event.target.value.split('|');$('#offerRows').innerHTML=offerRows(state.dialogGroup,event.target.value?{currency:pair[0],size_ml:Number(pair[1])}:null);}
  if(event.target.matches('[data-item-size]')){addOffer(event.target.dataset.itemSize,event.target.value);renderCart();}
});
$('#selectAllRetailers').addEventListener('click',()=>{state.selected=new Set([...state.offers.values()].map(o=>o.retailer_id));renderCoverage();refreshViews();});$('#selectNoRetailers').addEventListener('click',()=>{state.selected.clear();renderCoverage();refreshViews();});
$('#finderForm').addEventListener('submit',event=>{event.preventDefault();if(!state.selections.length)return showToast('Add at least one note.');state.activeSearch={selections:state.selections.map(s=>({...s})),mode:$('input[name=matchMode]:checked').value};renderResults();$('#results').hidden=false;$('#results').scrollIntoView({behavior:'smooth'});});
$('#addNote').addEventListener('click',()=>addSelection());$('#noteInput').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();addSelection();}});$('#noteLayer').addEventListener('change',refreshNoteSuggestions);
$('#resetFinder').addEventListener('click',()=>{state.selections=[];state.activeSearch=null;$('#results').hidden=true;$('#noteLayer').value='all';$('input[name=matchMode][value=any]').checked=true;refreshNoteSuggestions();renderSelections();});$('#addAllResults').addEventListener('click',addAll);
$('#moodFilters').addEventListener('click',event=>{const button=event.target.closest('[data-mood]');if(!button)return;state.mood=button.dataset.mood;state.visible=12;$$('[data-mood]').forEach(b=>b.classList.toggle('active',b===button));renderBrowse();});$('#searchInput').addEventListener('input',event=>{state.query=event.target.value;state.visible=12;renderBrowse();});$('#loadMore').addEventListener('click',()=>{state.visible+=12;renderBrowse();});
$('#clearFilters').addEventListener('click',()=>{state.query='';state.mood='all';state.visible=12;$('#searchInput').value='';$$('[data-mood]').forEach(b=>b.classList.toggle('active',b.dataset.mood==='all'));renderBrowse();});$('#emptyReset').addEventListener('click',()=>$('#clearFilters').click());
$('#openCart').addEventListener('click',openCart);$('[data-close-cart]').addEventListener('click',()=>$('#cartDialog').close());$('[data-close-dialog]').addEventListener('click',()=>{$('#scentDialog').close();state.replaceOfferId=null;});$('#scentDialog').addEventListener('close',()=>{state.replaceOfferId=null;});$('#clearCart').addEventListener('click',()=>{state.cart=[];persist();updateCartCount();renderCart();});
$('#addExclusion').addEventListener('click',()=>{const term=$('#exclusionInput').value.trim().toLowerCase(),exact=$('#exclusionMode').value==='exact';if(term&&!state.exclusions.some(r=>r.term===term&&r.exact===exact))state.exclusions.push({term,exact});$('#exclusionInput').value='';persist();renderCart();});$('#maxPrice').addEventListener('change',applyBudget);$('#maxPrice').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();applyBudget();}});$('#budgetCurrency').addEventListener('change',renderCart);$('#exportCsv').addEventListener('click',exportCsv);
$('#surpriseHero').addEventListener('click',()=>{if(state.groups.length){state.replaceOfferId=null;openProduct(state.groups[Math.floor(Math.random()*state.groups.length)].id);}});
loadCatalogs(true).catch(error=>{console.error(error);$('#coverageStatus').textContent='Catalogs could not be loaded. Please reload to try again.';$('#productGrid').innerHTML='<p>Catalogs are temporarily unavailable.</p>';$('#loadMore').hidden=true;});
