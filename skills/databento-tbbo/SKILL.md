---
name: databento-tbbo
description: Interpret, validate, and derive candles or metrics from Databento TBBO trades and pre-trade top-of-book quotes across DBN, JSON, CSV, and Python clients. Use for TBBO ingestion, research features, and data-quality work; not for reconstructing a full order book.
---

# Databento TBBO

Use the current [TBBO schema](https://databento.com/docs/schemas-and-data-formats/tbbo) and [field conventions](https://databento.com/docs/standards-and-conventions/common-fields-enums-types) when implementing or changing a parser. Check the actual dataset, schema, encoding, price/timestamp formatting, and symbol mapping before interpreting a file. TBBO contains each trade with the best bid and ask **immediately before** that trade affects the book. It is trade-sampled L1 data, not every quote update, full depth, or individual order events. Do not substitute TCBBO's consolidated quote semantics for TBBO.

## Decode the actual representation

- In JSON and Python record objects, `ts_event`, `rtype`, `publisher_id`, and `instrument_id` are under `hd`; `ts_recv` is a top-level field. A JSONL record may look like `{"ts_recv":"...Z","hd":{"ts_event":"...Z","rtype":1,"instrument_id":42031754},"action":"T","levels":[{"bid_px":"4507.5","ask_px":"4507.8"}],"symbol":"MGCZ6"}`. Here `hd.ts_event` is market event time and `ts_recv` is Databento receive time.
- In JSON, C++/Rust, and Python record interfaces, top-of-book quote fields are in `levels[0]`: `bid_px`, `ask_px`, `bid_sz`, `ask_sz`, `bid_ct`, and `ask_ct`. In CSV and the Python DataFrame API, read `bid_px_00`, `ask_px_00`, etc. Do not expect both layouts in one record or confuse `depth: 0` with a price/size field.
- DBN prices are signed fixed-point integers in units of 1e-9. JSON and CSV may show decimal strings when pretty prices are selected. Decode according to the actual encoding and keep exact integer/decimal values through normalization; do not divide a decimal string by 1e9 again. Null/undefined quote prices need their format's sentinel handling.
- Preserve nanosecond timestamps, original row order, `publisher_id`, `instrument_id`, raw symbol, `sequence`, `flags`, `ts_in_delta`, and source-file metadata. `ts_in_delta` is relative to `ts_recv`; it is not generally `ts_recv - ts_event`. Test flags with bitwise AND.

## Keep instruments and events distinct

- Select the **exact raw contract symbol** requested. A stream may interleave `MGCZ6`, `MGCV6`, and the calendar spread `MGCV6-MGCZ6`; these are distinct instruments. A spread trade price such as `-35.2` can be valid. Do not reject all nonpositive prices or merge outright and spread trades into one candle series. Confirm contract metadata and any roll policy separately.
- `instrument_id` is only guaranteed unique within a day. Keep the date, publisher, and symbol mapping with it; do not assume one ID identifies a contract throughout a year. Resolve symbols from the file's mapping or Databento symbology data when absent.
- TBBO has `action: "T"` and `rtype: 1`. For trades, `side: "B"` means buyer aggressor, `"A"` seller aggressor, and `"N"` unknown. Keep unknown volume separate; do not infer it solely from a quoted midpoint unless a separately named inference method is requested.
- Multiple trades may share `ts_recv`, `ts_event`, and `sequence`, including separate prices for the same symbol. Do not deduplicate on those fields alone. Keep each actual trade record unless a documented source identity proves duplication.
- Databento's index timestamp is `ts_recv` for TBBO; historical range filtering uses it. `ts_event` can be nonmonotonic in source data. Preserve input/receive order, report event-time inversions, and state the chosen ordering when deriving bars. For causal replay, a trade and its attached BBO are available no earlier than receipt, even if an event-time chart places them earlier.

## Derive and validate

Build trade OHLCV from observed `price` and `size` for one instrument at a time. Leave intervals without trades missing unless the user specifies an explicit fill policy. Calculate spread, midpoint, displayed top-of-book size/count imbalance, or signed volume only at trade events and only when the needed fields are valid. The attached BBO is pre-trade; do not treat it as the post-trade book or a continuous quote path. A trade outside the attached BBO is a quality signal to inspect, not automatic proof of a bad record.

Validate schema/format, file checksums, symbol mapping, timestamp precision, trade/quote bounds appropriate to the instrument, flags indicating bad receive time or uncertain book, record counts, gaps, and coverage. Report excluded or unknown records. Keep raw files and provenance so candles and metrics can be reproduced. In this trading repository, check `docs/project/data.md` and the current importer before modifying it; the existing CSV minute-bar path may not support JSONL, negative-price spreads, or tick-level metrics.

For DBN conversion, the official [encoding documentation](https://databento.com/docs/api-reference-historical/basics/encodings) describes `DBNStore.to_csv(pretty_ts=True, pretty_px=True, map_symbols=True)`. Confirm the resulting columns instead of assuming the JSON object shape survives conversion.
