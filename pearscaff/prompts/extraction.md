Given this {record_type} record, extract all entities, relationships, and facts.
Respond in JSON only, no other text.

Entity types to extract:
{entity_types_block}

Record ({record_id}):
{content}

Respond with exactly this JSON structure:
{{
  "entities": [
    {{"type": "person", "name": "Full Name", "metadata": {{"email": "...", "role": "..."}}}}
  ],
  "relationships": [
    {{"from": "Entity Name", "to": "Entity Name", "type": "relationship_type"}}
  ],
  "facts": [
    {{"entity": "Entity Name", "attribute": "attribute_name", "value": "value"}}
  ]
}}

If no entities, relationships, or facts can be extracted, return empty arrays.
