## Output format

Respond with exactly this JSON structure and nothing else — no markdown fences, no preamble, no explanation:

{{
  "entities": [
    {{
      "type": "person",
      "name": "Michael Chen",
      "metadata": {{
        "email": "michael@acmecorp.com",
        "role": "VP Engineering"
      }}
    }},
    {{
      "type": "company",
      "name": "Acme",
      "metadata": {{
        "domain": "acmecorp.com"
      }}
    }}
  ],
  "facts": [
    {{
      "edge_label": "AFFILIATED",
      "fact_type": "employee",
      "fact": "works at Acme as VP Engineering",
      "from_entity": "Michael Chen",
      "to_entity": "Acme",
      "confidence": "stated",
      "valid_until": null
    }},
    {{
      "edge_label": "ASSERTED",
      "fact_type": "commitment",
      "fact": "contract renewal deadline is March 2026",
      "from_entity": "Acme",
      "to_entity": null,
      "confidence": "stated",
      "valid_until": "2026-03-01"
    }}
  ]
}}

For facts, set confidence to:
- **stated** — explicitly said in the record
- **inferred** — reasonably implied but not directly stated

If nothing meaningful can be extracted, return empty arrays.
