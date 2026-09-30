import assert from "node:assert/strict";
import test from "node:test";
import { applyCartRules, buildCartUrl, containsTerm, eauFraicheSimilarity, filterProducts, productMatchesExclusion, resolveBankQuery, selectBatchVariant, splitNoteTerms } from "../finder-core.js";

const product={id:1,name:"Night Smoke",inspired_by:"Tobacco Vanille",top:"Bergamot, Black Pepper",heart:"Tobacco and Honey",base:"Vanilla, Cedarwood",variants:[{id:"101",title:"1ml",price:"2.50"},{id:"102",title:"5ml",price:"8.50"}]};

test("splits and matches normalized note terms",()=>{assert.deepEqual(splitNoteTerms("Saffron, Nutmeg and Orange."),["saffron","nutmeg","orange"]);assert.equal(containsTerm("Cedarwood, Musk","cedar"),false);assert.equal(containsTerm("Cedar, Musk","cedar"),true)});
test("searches the exhaustive bank and expands broad queries",()=>{const bank=[{term:"watermelon",count:5},{term:"watery notes",count:4},{term:"water lily",count:2},{term:"vanilla",count:20}];assert.deepEqual(resolveBankQuery(bank,"water").map(item=>item.term),["watermelon","watery notes","water lily"]);assert.deepEqual(resolveBankQuery(bank,"water lily").map(item=>item.term),["water lily"])});
test("supports all and any matching",()=>{assert.equal(filterProducts([product],[{layer:"all",term:"tobacco"},{layer:"base",term:"vanilla"}],"all",100).length,1);assert.equal(filterProducts([product],[{layer:"top",term:"lemon"},{layer:"heart",term:"honey"}],"any",100).length,1)});
test("scores Eau Fraiche overlap",()=>{const fresh={...product,top:"Lemon, Bergamot, Star Fruit, Cardamom",heart:"Cedarwood, Tarragon, Sage, Pepper",base:"Musk, Amber, Sycamore Wood"};assert.ok(eauFraicheSimilarity(fresh).score>25)});
test("general search does not apply personal similarity filtering",()=>{const fresh={...product,top:"Lemon, Bergamot, Star Fruit, Cardamom",heart:"Cedarwood, Tarragon, Sage, Pepper",base:"Musk, Amber, Sycamore Wood"};assert.equal(filterProducts([fresh],[{layer:"top",term:"lemon"}],"any").length,1)});
test("batch size falls back to smallest available",()=>{assert.equal(selectBatchVariant(product,"10ml").variant.id,"101");assert.equal(selectBatchVariant(product,"10ml").fallback,true);assert.equal(selectBatchVariant(product,"5ml").variant.id,"102")});
test("exact exclusions do not match longer notes",()=>{assert.deepEqual(productMatchesExclusion({...product,base:"Rose Water, Musk"},"rose",true),[]);assert.deepEqual(productMatchesExclusion({...product,base:"Rose, Musk"},"rose",true),["base"])});
test("cart rules and URL preserve selected variants",()=>{const cart=[{productId:1,variant:product.variants[0]}];assert.equal(applyCartRules(cart,new Map([[1,product]]),[],2).kept.length,0);assert.match(buildCartUrl(cart),/101:1/)});
