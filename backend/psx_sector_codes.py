"""psx_sector_codes.py — PSX's official numeric sector code -> sector name map.

PSX's market-watch feed (and every downstream row built from it) carries a
SECTOR column, but it comes back as a numeric code (e.g. "0804"), not a name
-- the site itself only renders the name on each company's own profile page
(`quote__sector` div), never in the market-watch table. Scraped directly from
https://dps.psx.com.pk/company/<symbol> for one representative symbol per
code observed in a live market-watch snapshot, not guessed.

Codes are the file's ground truth; anything not in this table (a new sector
PSX adds later) falls back to the raw code in `name_for`, never a fabricated
name.
"""

CODES = {
    "0801": "Automobile Assembler",
    "0802": "Automobile Parts & Accessories",
    "0803": "Cable & Electrical Goods",
    "0804": "Cement",
    "0805": "Chemical",
    "0806": "Close - End Mutual Fund",
    "0807": "Commercial Banks",
    "0808": "Engineering",
    "0809": "Fertilizer",
    "0810": "Food & Personal Care Products",
    "0811": "Glass & Ceramics",
    "0812": "Insurance",
    "0813": "Inv. Banks / Inv. Cos. / Securities Cos.",
    "0814": "Jute",
    "0815": "Leasing Companies",
    "0816": "Leather & Tanneries",
    "0818": "Miscellaneous",
    "0819": "Modarabas",
    "0820": "Oil & Gas Exploration Companies",
    "0821": "Oil & Gas Marketing Companies",
    "0822": "Paper, Board & Packaging",
    "0823": "Pharmaceuticals",
    "0824": "Power Generation & Distribution",
    "0825": "Refinery",
    "0826": "Sugar & Allied Industries",
    "0827": "Synthetic & Rayon",
    "0828": "Technology & Communication",
    "0829": "Textile Composite",
    "0830": "Textile Spinning",
    "0831": "Textile Weaving",
    "0832": "Tobacco",
    "0833": "Transport",
    "0834": "Vanaspati & Allied Industries",
    "0835": "Woollen",
    "0836": "Real Estate Investment Trust",
    "0837": "Exchange Traded Funds",
    "0838": "Property",
    "0839": "Apparel",
}


def name_for(code):
    """PSX sector name for a raw numeric code, or the code itself if unknown
    (never fabricated -- an unmapped code means PSX added a sector this table
    doesn't have yet, which should be visible, not silently papered over)."""
    code = (code or "").strip()
    return CODES.get(code, code)
