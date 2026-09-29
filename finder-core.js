export const EAU_FRAICHE_REFERENCE = {
  top: { lemon: ["lemon"], bergamot: ["bergamot"], carambola: ["carambola", "star fruit"], cardamom: ["cardamom"], "brazilian rosewood": ["brazilian rosewood", "rosewood"] },
  heart: { cedar: ["cedar", "cedarwood"], tarragon: ["tarragon"], sage: ["sage"], pepper: ["pepper", "black pepper", "white pepper", "pink pepper"] },
  base: { musk: ["musk", "white musk"], amber: ["amber"], sycamore: ["sycamore", "sycamore wood"], saffron: ["saffron"] },
};
export const SEARCH_FIELDS = ["name", "inspired_by", "top", "heart", "base"];
export const NOTE_LAYERS = ["top", "heart", "base"];

export function normalizeTerm(value = "") {
  return value.toLowerCase().replace(/&/g, " and ").replace(/\([^)]*\)/g, " ").replace(/[^a-z0-9' -]+/g, " ").replace(/\s+/g, " ").trim();
}
export function splitNoteTerms(value = "") {
  return [...new Set(value.split(/\s*(?:,|;|\/|\||•|\band\b)\s*/i).map(normalizeTerm).map(term => term.replace(/^(?:notes? of|a hint of|touch of)\s+/, "")).filter(term => term && !["note", "notes"].includes(term)))];
}
export function resolveBankQuery(entries, query) {
  const normalized = normalizeTerm(query);
  if (!normalized) return [];
  const exact = entries.find(entry => entry.term === normalized);
  if (exact) return [exact];
  return entries.filter(entry => entry.term.includes(normalized));
}
export function containsTerm(text, term) {
  const haystack = ` ${normalizeTerm(text)} `;
  const needle = normalizeTerm(term);
  if (!needle) return false;
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[^a-z0-9])${escaped}(?:$|[^a-z0-9])`).test(haystack);
}
export function selectionMatches(product, selection) {
  const fields = selection.layer === "all" ? SEARCH_FIELDS : ["name", "inspired_by", selection.layer];
  return fields.filter(field => containsTerm(product[field] || "", selection.term));
}
export function eauFraicheSimilarity(product) {
  if (/\b(?:versace\s+)?man\s+eau\s+fraiche\b/i.test(`${product.name} ${product.inspired_by}`)) return { score: 100, traits: ["direct Versace Man Eau Fraiche reference"] };
  const traits = [];
  let total = 0;
  Object.entries(EAU_FRAICHE_REFERENCE).forEach(([layer, references]) => {
    Object.entries(references).forEach(([canonical, aliases]) => {
      total += 1;
      if (aliases.some(alias => containsTerm(product[layer], alias))) traits.push(`${layer}: ${canonical}`);
    });
  });
  return { score: Math.round(100 * traits.length / total), traits };
}
export function filterProducts(products, selections, matchMode = "any", maxScore = 25) {
  if (!selections.length) return [];
  return products.map(product => {
    const matches = selections.map(selection => ({ ...selection, fields: selectionMatches(product, selection) }));
    const matchedCount = matches.filter(match => match.fields.length).length;
    const similarity = eauFraicheSimilarity(product);
    return { ...product, matches, matchedCount, similarity };
  }).filter(product => (matchMode === "all" ? product.matchedCount === selections.length : product.matchedCount > 0) && product.similarity.score <= maxScore)
    .sort((a, b) => b.matchedCount - a.matchedCount || a.similarity.score - b.similarity.score || a.name.localeCompare(b.name));
}
export function variantSortKey(variant) {
  const size = variant.title.match(/(\d+(?:\.\d+)?)\s*ml\b/i);
  const price = Number(variant.price);
  return [size ? 0 : 1, size ? Number(size[1]) : Number.isFinite(price) ? price : Infinity, Number.isFinite(price) ? price : Infinity];
}
export function sortVariants(variants = []) {
  return [...variants].sort((a, b) => { const ak = variantSortKey(a), bk = variantSortKey(b); return ak[0] - bk[0] || ak[1] - bk[1] || ak[2] - bk[2]; });
}
export function selectBatchVariant(product, requestedTitle) {
  const variants = sortVariants(product.variants);
  const requested = variants.find(variant => variant.title.toLowerCase() === requestedTitle.toLowerCase());
  return { variant: requested || variants[0], fallback: !requested };
}
export function productMatchesExclusion(product, term, exact = false) {
  const normalized = normalizeTerm(term);
  if (!normalized) return [];
  if (!exact) return SEARCH_FIELDS.filter(field => containsTerm(product[field] || "", normalized));
  const fields = NOTE_LAYERS.filter(layer => splitNoteTerms(product[layer]).includes(normalized));
  if (normalizeTerm(product.name) === normalized) fields.push("name");
  if (normalizeTerm(product.inspired_by) === normalized) fields.push("inspired_by");
  return fields;
}
export function applyCartRules(cart, productsById, exclusions = [], maxPrice = null) {
  const kept = [], removed = [];
  cart.forEach(item => {
    const product = productsById.get(item.productId);
    const termHits = exclusions.map(rule => ({ ...rule, fields: productMatchesExclusion(product, rule.term, rule.exact) })).filter(rule => rule.fields.length);
    const price = Number(item.variant.price);
    const overPrice = maxPrice !== null && (!Number.isFinite(price) || price > maxPrice);
    if (termHits.length || overPrice) removed.push({ ...item, product, termHits, overPrice }); else kept.push(item);
  });
  return { kept, removed };
}
export function buildCartUrl(cart) {
  if (!cart.length) return "";
  return `https://decantified.com/cart/${cart.map(item => `${item.variant.id}:1`).join(",")}?storefront=true&utm_source=scent_finder&utm_medium=referral&utm_campaign=guided_cart`;
}
