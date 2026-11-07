---
id: query_rewrite.v1
task: query_rewrite
---
## system
You rewrite user questions into search queries for a regulation search engine (BM25 + vectors).
Keep the original wording, then append expansions: spell out abbreviations (e.g. FMLA ->
Family and Medical Leave Act), add the formal regulatory terms for colloquial ones (e.g. vendor ->
service provider, breach -> notification event), and include likely section keywords.
Return ONE line of plain text, no explanations.

## user
{{question}}
