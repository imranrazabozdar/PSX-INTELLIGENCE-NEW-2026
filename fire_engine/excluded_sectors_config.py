"""
PSX FIRE ENGINE - EXCLUDED SECTORS CONFIGURATION
=================================================

Official PSX stock exclusion list, as supplied to this project (source
cited by the caller as https://dps.psx.com.pk/sector-summary; not
independently re-verified against a live fetch in this task -- see
NOTE below).

Header claim vs. actual data (reported, not silently reconciled): the
source material's own docstring/print statement claims "Total: 519
stocks across 14 excluded sectors," but the 14 per-sector symbol lists
as originally supplied summed to exactly 244 symbols (each sector's own
declared `count` matched its own list length -- no per-sector error),
not 519. Whatever the remaining ~275 symbols are, they were not
included in what was supplied to this project. One further symbol
(YOUW) was then removed by explicit user instruction -- see
TEXTILE_WEAVING's own comment -- so EXCLUDED_SYMBOLS_FLAT below now
totals 243, not 244 and not the claimed 519. Treat this exclusion list
as INCOMPLETE until the remaining missing symbols are supplied or the
519 total is corrected.

Supplied: 2026-09-06

NOTE ON A SEPARATE DATA DISCREPANCY: the Tobacco sector's symbol list
here reads "KHtc" (unusual capitalization, mid-word), while the same
source's own YAML snippet for the identical sector instead reads
"KHTIC" for that entry. These are only consistent as PAKT/PMPK; the
third symbol differs by spelling/case between the two representations
in the same source. This module keeps the Python dict's literal value
("KHtc") since that's the executable data structure (not the prose YAML
block), but this entry should be confirmed against the live PSX
sector-summary page before relying on it for exclusion filtering.
"""

# ============================================================================
# EXCLUDED SECTORS STOCK LIST (519 TOTAL)
# ============================================================================

EXCLUDED_SECTORS_CONFIG = {
    "SUGAR_AND_ALLIED_INDUSTRIES": {
        "sector_name": "Sugar and Allied Industries",
        "count": 35,
        "symbols": [
            "AGSML", "ADAMS", "AABS", "ALNRS", "ANSM", "ANSMR", "BAFS", "CHAS",
            "DWSM", "FRSM", "HABSM", "HAL", "HWQS", "HSM", "IMSL", "JDWS",
            "JSML", "KPUS", "MRNS", "MIRKS", "MZSM", "NONS", "PNGRS", "PMRS",
            "SKRS", "SLSO", "SLSOPP", "SLSOPVI", "SANSM", "SHSML", "SHJS",
            "SML", "SASML", "TSML", "TICL"
        ]
    },

    "TEXTILE_COMPOSITE": {
        "sector_name": "Textile Composite",
        "count": 56,
        "symbols": [
            "COST", "COTT", "AHTM", "ADMM", "ARUJ", "ANLPS", "ANL", "ANLNV",
            "BHAT", "BTL", "CHBL", "CLCPS", "CRTM", "DLL", "FASM", "FSWL",
            "FTHM", "GFIL", "GATM", "HAFL", "HAEL", "HATM", "HUSI", "INKL",
            "ISTM", "JUBS", "KAKL", "KHYT", "KOIL", "KML", "KTML", "MSOTPS",
            "MSOT", "MEHT", "MTIL", "MFTM", "MUBT", "NINA", "NCL", "NML",
            "PASM", "QUET", "REDCO", "REWM", "SFLL", "SFAT", "SFL", "SAPT",
            "SCHT", "STML", "SURC", "TAJT", "TOWL", "USMT", "ZAHID", "ZHCM"
        ]
    },

    "TOBACCO": {
        "sector_name": "Tobacco",
        "count": 3,
        "symbols": [
            "KHtc", "PAKT", "PMPK"
        ]
    },

    "VANASPATI_AND_ALLIED_INDUSTRIES": {
        "sector_name": "Vanaspati and Allied Industries",
        "count": 6,
        "symbols": [
            "UNITY", "EXTR", "MOIL", "POML", "SSOM", "SURAJ"
        ]
    },

    "WOOLEN": {
        "sector_name": "Woolen",
        "count": 2,
        "symbols": [
            "BNWM", "MOON"
        ]
    },

    "PAPER_AND_BOARD": {
        "sector_name": "Paper & Board",
        "count": 10,
        "symbols": [
            "ABSON", "BPBL", "CEPB", "CPPL", "DBSL", "MERIT", "PKGS", "PPP",
            "RPL", "SEPL"
        ]
    },

    "CLOSE_END_MUTUAL_FUNDS": {
        "sector_name": "Close End Mutual Funds",
        "count": 8,
        "symbols": [
            "DOMF", "FDMF", "GASF", "INMF", "PGF", "PIF", "PUDF", "TSMF"
        ]
    },

    "JUTE": {
        "sector_name": "Jute",
        "count": 2,
        "symbols": [
            "CJPL", "SUHJ"
        ]
    },

    "LEASING_COMPANIES": {
        "sector_name": "Leasing Companies",
        "count": 10,
        "symbols": [
            "CPAL", "ENGL", "GRYL", "OLPL", "PGLC", "PICL", "SLL", "SPLC",
            "SLCL", "SLCPA"
        ]
    },

    "LEATHER_AND_TANNERIES": {
        "sector_name": "Leather and Tanneries",
        "count": 5,
        "symbols": [
            "BATA", "FIL", "LEUL", "PAKL", "SRVI"
        ]
    },

    "REAL_ESTATE_INVESTMENT_TRUST": {
        "sector_name": "Real Estate Investment Trust",
        "count": 1,
        "symbols": [
            "DCR"
        ]
    },

    "SYNTHETIC_AND_RAYON": {
        "sector_name": "Synthetic & Rayon",
        "count": 11,
        "symbols": [
            "AASM", "DSFL", "GATI", "IBFL", "NAFL", "NSRM", "NORS", "PSYL",
            "RUPL", "SGABL", "TRPOL"
        ]
    },

    "TEXTILE_SPINNING": {
        "sector_name": "Textile Spinning",
        "count": 81,
        "symbols": [
            "ADTM", "AZTM", "AQTM", "AATM", "AWTX", "AMTEX", "ANNT", "APOT",
            "ASTM", "AYTM", "AZMT", "BCML", "BILF", "BROT", "CWSM", "CTM",
            "CCM", "CFL", "DMTX", "DSIL", "DSML", "DATM", "DFSM", "DKTM",
            "DMTM", "DWTM", "DINT", "ELCM", "ELSM", "FAEL", "FZCM", "GADT",
            "GLAT", "GOEM", "GLOT", "GUSM", "GUTM", "GSPM", "HMIM", "HAJT",
            "HIRAT", "IDSM", "IDRT", "IDYM", "ISHT", "ILTM", "JATM", "JKSM",
            "JDMT", "KACM", "KSTM", "KHSM", "KOHTM", "KOSM", "LMSM", "MQTM",
            "MDTM", "MUKT", "NPSM", "NATM", "NAGC", "NCML", "OML", "PRET",
            "RAVT", "RCML", "RUBY", "SAIF", "SJTM", "SALT", "SLYT", "SANE",
            "SNAI", "SRSM", "SSML", "SERT", "SHDT", "SHCM", "SZTM", "SUTM",
            "SUCM"
        ]
    },

    "TEXTILE_WEAVING": {
        "sector_name": "Textile Weaving",
        # count intentionally left at the source material's original 14
        # even though the symbols list below has 13 -- YOUW was removed
        # from this sector's exclusion list per explicit user instruction
        # (it's also in this project's own WATCHLIST_SYMBOLS and the user
        # wants it tracked, not filtered out). Do not silently re-add it.
        "count": 14,
        "symbols": [
            "ASHT", "FML", "HKKT", "ICCT", "MOHE", "PRWM", "PCML", "SDOT",
            "SDIL", "SMTM", "SERF", "STJT", "ZTL"
        ]
    }
}

# ============================================================================
# FLAT EXCLUSION LIST (All 519 symbols)
# ============================================================================

EXCLUDED_SYMBOLS_FLAT = []
for _sector_key, _sector_data in EXCLUDED_SECTORS_CONFIG.items():
    EXCLUDED_SYMBOLS_FLAT.extend(_sector_data["symbols"])

# Sort and deduplicate
EXCLUDED_SYMBOLS_FLAT = sorted(set(EXCLUDED_SYMBOLS_FLAT))
