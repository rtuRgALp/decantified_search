import fs from "node:fs/promises";
import path from "node:path";
import { Workbook } from "@oai/artifact-tool";

const inputPath = path.resolve("decantified_tobacco_in_stock.csv");
const outputDir = path.resolve("outputs/eau-fraiche-gender-filtered-20260926");
const outputPath = path.join(outputDir, "decantified_tobacco_filtered_with_gender_metadata.csv");
const metadataPath = path.resolve("decantified_product_metadata.json");

const brightOpeningPattern = /\b(?:lemon|bergamot|carambola|star\s*fruit)\b/gi;
const aromaticPattern = /\b(?:cardamom|tarragon|sage|pepper|rosemary|lavender|geranium)\b/gi;
const cleanWoodPattern = /\b(?:cedar(?:wood)?|woods?|woody|musk|amber|sycamore|cypress)\b/gi;
const gourmandPattern = /\b(?:honey|vanilla|tonka|caramel|coffee|mocha|marshmallow|cacao|rum|dates?)\b/gi;

const csvText = await fs.readFile(inputPath, "utf8");
const metadata = JSON.parse(await fs.readFile(metadataPath, "utf8"));
const metadataByUrl = new Map(metadata.map((item) => [item.url, item]));
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Tobacco" });
const sheet = workbook.worksheets.getItem("Tobacco");
const usedRange = sheet.getUsedRange(true);
const values = usedRange.values;

const headers = values[0].map((value) => String(value ?? ""));
const requiredColumns = ["product_name", "inspired_by", "top", "heart", "base"];
const columnIndexes = Object.fromEntries(requiredColumns.map((name) => [name, headers.indexOf(name)]));
if (Object.values(columnIndexes).some((index) => index < 0)) {
  throw new Error("Expected fragrance columns were not found.");
}

const dataRows = values.slice(1).filter((row) => row.some((value) => String(value ?? "").trim() !== ""));
const profileRemovedRows = [];
const profileKeptRows = [];

function uniqueMatches(text, pattern) {
  return [...new Set([...text.matchAll(pattern)].map((match) => match[0].toLowerCase()))];
}

for (const row of dataRows) {
  const product = String(row[columnIndexes.product_name] ?? "");
  const inspiredBy = String(row[columnIndexes.inspired_by] ?? "");
  const notes = ["top", "heart", "base"]
    .map((name) => String(row[columnIndexes[name]] ?? ""))
    .join(" | ");
  const bright = uniqueMatches(notes, brightOpeningPattern);
  const aromatic = uniqueMatches(notes, aromaticPattern);
  const cleanWoods = uniqueMatches(notes, cleanWoodPattern);
  const gourmand = uniqueMatches(notes, gourmandPattern);

  const directFreshAquaticReference = /\bcool water\b/i.test(inspiredBy);
  const clusteredEauFraicheProfile = bright.length > 0
    && gourmand.length < 2
    && (aromatic.length >= 2 || cleanWoods.length >= 2);

  if (directFreshAquaticReference || clusteredEauFraicheProfile) {
    profileRemovedRows.push({
      product,
      inspiredBy,
      matchingTraits: [...bright, ...aromatic, ...cleanWoods].join(", "),
      reason: directFreshAquaticReference
        ? "Fresh aquatic reference (Cool Water)"
        : "Clustered bright citrus, aromatic, and/or clean woody notes",
    });
  } else {
    profileKeptRows.push(row);
  }
}

const urlIndex = headers.indexOf("url");
const enrichedHeaders = [
  ...headers,
  "website_description",
  "gender_label",
  "gender_evidence",
  "website_vendor",
  "website_product_type",
];
const genderRemovedRows = [];
const keptRows = [];
for (const row of profileKeptRows) {
  const url = String(row[urlIndex] ?? "");
  const item = metadataByUrl.get(url);
  if (!item) {
    throw new Error(`Missing website metadata for ${url}`);
  }
  if (item.fetch_status !== "ok") {
    throw new Error(`Website metadata retrieval failed for ${url}`);
  }
  if (item.gender_label === "women") {
    genderRemovedRows.push({ product: row[0], evidence: item.gender_evidence });
    continue;
  }
  keptRows.push([
    ...row,
    item.website_description,
    item.gender_label,
    item.gender_evidence,
    item.website_vendor,
    item.website_product_type,
  ]);
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

const outputRows = [enrichedHeaders, ...keptRows];
const outputCsv = `${outputRows.map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, outputCsv, "utf8");

console.log(JSON.stringify({
  inputRows: dataRows.length,
  keptRows: keptRows.length,
  profileRemovedRows: profileRemovedRows.length,
  genderRemovedRows: genderRemovedRows.length,
  outputPath,
  profileRemoved: profileRemovedRows,
  genderRemoved: genderRemovedRows,
}, null, 2));
